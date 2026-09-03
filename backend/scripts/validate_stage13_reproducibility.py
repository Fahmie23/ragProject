from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"

PINNED_IMAGE_PATTERNS = {
    "postgres": r"pgvector/pgvector:0\.8\.6-pg16-bookworm",
    "python": r"FROM python:3\.12\.14-slim-bookworm",
    "node": r"FROM node:24\.19\.0-bookworm-slim",
    "nginx": r"FROM nginx:1\.31\.4-alpine",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def non_comment_requirement_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("--", "-r ", "-c ")):
            continue
        # pip-compile continuation / annotation lines
        if line.startswith("# via") or line == "\\":
            continue
        lines.append(line.rstrip("\\").strip())
    return lines


def check_lock(path: Path, errors: list[str]) -> None:
    if not path.exists():
        fail(errors, f"Missing dependency lock: {path.relative_to(REPO_ROOT)}")
        return
    unpinned = []
    for line in non_comment_requirement_lines(path):
        requirement = line.split(" ; ", 1)[0].strip()
        if "==" not in requirement and " @ " not in requirement:
            unpinned.append(line)
    if unpinned:
        fail(errors, f"Unpinned requirements in {path.name}: {unpinned[:5]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage 13 Docker/reproducibility contract.")
    parser.add_argument(
        "--require-locks",
        action="store_true",
        help="Fail if generated Python/npm lock files are absent.",
    )
    parser.add_argument(
        "--docker-compose-config",
        action="store_true",
        help="Also require `docker compose config` to succeed.",
    )
    args = parser.parse_args()

    errors: list[str] = []
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    backend_dockerfile = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
    frontend_dockerfile = (FRONTEND_DIR / "Dockerfile").read_text(encoding="utf-8")

    corpus = "\n".join([compose, backend_dockerfile, frontend_dockerfile])
    if re.search(r"(?:image:|FROM)\s+[^\n]*:latest(?:\s|$)", corpus):
        fail(errors, "Docker configuration must not use :latest image tags.")

    for label, pattern in PINNED_IMAGE_PATTERNS.items():
        if not re.search(pattern, corpus):
            fail(errors, f"Pinned {label} image contract is missing or changed.")

    required_compose_fragments = [
        "condition: service_healthy",
        "condition: service_completed_successfully",
        "rag_pgdata:/var/lib/postgresql/data",
        "rag_hf_cache:/home/rag/.cache/huggingface",
        "./backend/data:/app/data",
        "GENERATION_MODEL: ${GENERATION_MODEL:-openai/gpt-oss-120b}",
        'profiles: ["verify"]',
        "target: test",
    ]
    for fragment in required_compose_fragments:
        if fragment not in compose:
            fail(errors, f"Compose reproducibility contract missing: {fragment}")

    package = json.loads((FRONTEND_DIR / "package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for name, version in package.get(section, {}).items():
            if version == "latest" or version.startswith(("^", "~", ">", "<", "*")):
                fail(errors, f"Frontend dependency must be exact-pinned: {name}={version}")
    if package.get("engines", {}).get("node") != "24.19.x":
        fail(errors, "frontend package.json must declare Node 24.19.x.")
    if package.get("engines", {}).get("npm") != "11.17.x":
        fail(errors, "frontend package.json must declare npm 11.17.x.")
    if package.get("packageManager") != "npm@11.17.0":
        fail(errors, "frontend packageManager must pin npm@11.17.0.")
    if (FRONTEND_DIR / ".nvmrc").read_text(encoding="utf-8").strip() != "24.19.0":
        fail(errors, "frontend/.nvmrc must pin Node 24.19.0.")

    if args.require_locks:
        check_lock(BACKEND_DIR / "requirements.lock.txt", errors)
        check_lock(BACKEND_DIR / "requirements-dev.lock.txt", errors)
        lock = FRONTEND_DIR / "package-lock.json"
        if not lock.exists():
            fail(errors, "Missing dependency lock: frontend/package-lock.json")
        else:
            data = json.loads(lock.read_text(encoding="utf-8"))
            if int(data.get("lockfileVersion", 0)) < 3:
                fail(errors, "frontend/package-lock.json must use lockfileVersion >= 3.")
            root = data.get("packages", {}).get("", {})
            if root.get("dependencies") != package.get("dependencies"):
                fail(errors, "package-lock root dependencies do not match package.json.")
            if root.get("devDependencies") != package.get("devDependencies"):
                fail(errors, "package-lock root devDependencies do not match package.json.")

    if args.docker_compose_config:
        docker = shutil.which("docker")
        if not docker:
            fail(errors, "docker executable is not available.")
        else:
            proc = subprocess.run(
                [docker, "compose", "config", "--quiet"],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                fail(errors, f"docker compose config failed: {(proc.stderr or proc.stdout).strip()}")

    if errors:
        print("FAIL: Stage 13 reproducibility contract")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: Stage 13 reproducibility contract")
    print("Pinned container toolchain: Python 3.12.14 / Node 24.19.0 / pgvector 0.8.6+PG16 / nginx 1.31.4")
    print("Frontend direct dependencies: exact-pinned")
    if args.require_locks:
        print("Python/npm dependency locks: present and structurally valid")
    if args.docker_compose_config:
        print("docker compose config: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
