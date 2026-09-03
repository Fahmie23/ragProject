from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"


def run(cmd: list[str], *, cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Stage 13 Python/npm dependency lock files.")
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Only generate Python lock files.",
    )
    args = parser.parse_args()

    try:
        import piptools  # noqa: F401
    except Exception:
        print(
            "pip-tools is required. Install the Stage 13 development requirements first:\n"
            "  python -m pip install -r requirements-dev.txt",
            file=sys.stderr,
        )
        return 2

    compile_base = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--resolver=backtracking",
        "--strip-extras",
        "--no-emit-index-url",
        "--no-emit-trusted-host",
    ]

    run(
        compile_base
        + [
            "--output-file=requirements.lock.txt",
            "requirements.txt",
        ],
        cwd=BACKEND_DIR,
    )
    run(
        compile_base
        + [
            "--output-file=requirements-dev.lock.txt",
            "requirements-dev.txt",
        ],
        cwd=BACKEND_DIR,
    )

    if not args.skip_frontend:
        npm = shutil.which("npm")
        if not npm:
            print("npm is required to generate frontend/package-lock.json.", file=sys.stderr)
            return 2
        package = json.loads((FRONTEND_DIR / "package.json").read_text(encoding="utf-8"))
        node = shutil.which("node")
        if not node:
            print("node is required to generate frontend/package-lock.json.", file=sys.stderr)
            return 2
        node_version = subprocess.check_output([node, "--version"], text=True).strip().removeprefix("v")
        npm_version = subprocess.check_output([npm, "--version"], text=True).strip()
        if node_version != "24.19.0" or npm_version != "11.17.0":
            print(
                "Frontend lock generation requires the Stage 12 verified toolchain: "
                f"Node 24.19.0 + npm 11.17.0; found Node {node_version} + npm {npm_version}.\n"
                "Use `nvm install 24.19.0 && nvm use 24.19.0` and retry.",
                file=sys.stderr,
            )
            return 2
        print("Frontend toolchain: Node 24.19.0 / npm 11.17.0")
        run([npm, "install", "--package-lock-only", "--ignore-scripts"], cwd=FRONTEND_DIR)

    print("PASS: Stage 13 dependency lock files generated")
    print(f"- {BACKEND_DIR / 'requirements.lock.txt'}")
    print(f"- {BACKEND_DIR / 'requirements-dev.lock.txt'}")
    if not args.skip_frontend:
        print(f"- {FRONTEND_DIR / 'package-lock.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
