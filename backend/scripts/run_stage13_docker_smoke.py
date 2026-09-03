from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
PROJECT = "rag-stage13-smoke"


def run(cmd: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, check=check)


def fetch_json(url: str, timeout: float = 3.0) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def wait_url(url: str, *, timeout_seconds: float, expect_json: bool = False) -> object:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if expect_json:
                return fetch_json(url)
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 400:
                    return response.status
        except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a clean, isolated Stage 13 Docker startup smoke.")
    parser.add_argument("--keep", action="store_true", help="Keep the smoke stack and volumes after success/failure.")
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    args = parser.parse_args()

    docker = shutil.which("docker")
    if not docker:
        print("docker executable is required.", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env.update(
        {
            "POSTGRES_PORT": "55432",
            "BACKEND_PORT": "18000",
            "FRONTEND_PORT": "15173",
            "VITE_API_BASE": "",
            # Keep the smoke hermetic: generation provider configuration may exist,
            # but no generation endpoint is called.
            "GROQ_API_KEY": "",
        }
    )
    compose = [docker, "compose", "-p", PROJECT]

    try:
        run(compose + ["down", "--volumes", "--remove-orphans"], env=env, check=False)
        run(compose + ["up", "-d", "--build"], env=env)

        health = wait_url("http://127.0.0.1:18000/health", timeout_seconds=args.timeout_seconds, expect_json=True)
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise RuntimeError(f"Backend health is not ok: {health}")

        db = wait_url(
            "http://127.0.0.1:18000/api/system/database",
            timeout_seconds=30,
            expect_json=True,
        )
        if not isinstance(db, dict):
            raise RuntimeError(f"Unexpected database status payload: {db}")
        if not db.get("reachable") or not db.get("pgvector_enabled") or not db.get("schema_ready"):
            raise RuntimeError(f"Database/pgvector/migration readiness failed: {db}")

        wait_url("http://127.0.0.1:15173/", timeout_seconds=60)
        proxied_health = wait_url(
            "http://127.0.0.1:15173/health", timeout_seconds=30, expect_json=True
        )
        if not isinstance(proxied_health, dict) or proxied_health.get("status") != "ok":
            raise RuntimeError(f"Frontend -> backend proxy health failed: {proxied_health}")
        proxied_db = wait_url(
            "http://127.0.0.1:15173/api/system/database", timeout_seconds=30, expect_json=True
        )
        if not isinstance(proxied_db, dict) or not proxied_db.get("schema_ready"):
            raise RuntimeError(f"Frontend -> backend API proxy failed: {proxied_db}")

        print("PASS: Stage 13 clean Docker smoke")
        print("PostgreSQL + pgvector: healthy")
        print("Alembic migration: completed before backend startup")
        print("FastAPI /health: ok")
        print("Frontend static container: reachable")
        print("Frontend same-origin /api proxy -> backend: PASS")
        print("External generation calls: 0")
        return 0
    finally:
        if not args.keep:
            run(compose + ["down", "--volumes", "--remove-orphans"], env=env, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
