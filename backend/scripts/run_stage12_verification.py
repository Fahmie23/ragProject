#!/usr/bin/env python3
"""Run the Stage 12 automated/system verification gates."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def _run(label: str, command: list[str], cwd: Path) -> bool:
    print(f"\n=== {label} ===")
    print("$", " ".join(command))
    result = subprocess.run(command, cwd=cwd, text=True, check=False)
    if result.returncode != 0:
        print(f"FAIL: {label} (exit {result.returncode})")
        return False
    print(f"PASS: {label}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Stage 12 verification gates")
    ap.add_argument("--frontend", choices=["auto", "required", "skip"], default="auto")
    ap.add_argument("--skip-full-pytest", action="store_true")
    args = ap.parse_args()

    checks: list[tuple[str, list[str], Path]] = [
        ("Production freeze guard", [sys.executable, "scripts/validate_stage11_frozen_baseline.py"], BACKEND_ROOT),
        ("Held-out benchmark freeze guard", [sys.executable, "scripts/validate_stage11_heldout_benchmark.py"], BACKEND_ROOT),
        ("Final Stage 11 evaluation reproduction", [sys.executable, "scripts/validate_stage11_final_evaluation.py"], BACKEND_ROOT),
        (
            "Stage 12 system/API tests",
            [sys.executable, "-m", "pytest", "-q", "tests/test_stage12_system_contracts.py", "tests/test_stage12_pipeline_system.py", "tests/test_stage12_stage11_final_reproduction.py"],
            BACKEND_ROOT,
        ),
        ("Python compile", [sys.executable, "-m", "compileall", "-q", "app", "scripts", "tests"], BACKEND_ROOT),
    ]
    if not args.skip_full_pytest:
        checks.append(("Full backend regression", [sys.executable, "-m", "pytest", "-q"], BACKEND_ROOT))

    passed = True
    for label, command, cwd in checks:
        passed = _run(label, command, cwd) and passed
        if not passed:
            break

    frontend_status = "not-run"
    if passed and args.frontend != "skip":
        npm = shutil.which("npm")
        node_modules = FRONTEND_ROOT / "node_modules"
        if npm and node_modules.exists():
            frontend_status = "passed" if _run("Frontend TypeScript/Vite build", [npm, "run", "build"], FRONTEND_ROOT) else "failed"
            passed = frontend_status == "passed"
        elif args.frontend == "required":
            frontend_status = "failed"
            print("\nFAIL: frontend build required but frontend/node_modules is missing or npm is unavailable")
            passed = False
        else:
            frontend_status = "skipped-dependencies-missing"
            print("\nSKIP: frontend build (node_modules/npm unavailable). Run locally with --frontend required after npm dependencies are installed.")

    print("\n=== Stage 12 verification summary ===")
    print(f"Backend/system gates: {'PASS' if passed else 'FAIL'}")
    print(f"Frontend build: {frontend_status}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
