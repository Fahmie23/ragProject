from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run(label: str, cmd: list[str]) -> bool:
    print(f"\n=== {label} ===")
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=BACKEND_DIR)
    if proc.returncode:
        print(f"FAIL: {label} (exit {proc.returncode})")
        return False
    print(f"PASS: {label}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 13 reproducibility verification gates.")
    parser.add_argument(
        "--skip-container-tests",
        action="store_true",
        help="Skip the locked Docker backend pytest image (not allowed for Stage 13 freeze).",
    )
    parser.add_argument(
        "--include-docker-smoke",
        action="store_true",
        help="Build and boot an isolated clean Docker stack after static/offline verification.",
    )
    args = parser.parse_args()

    py = sys.executable
    gates = [
        ("Production freeze guard", [py, "scripts/validate_stage11_frozen_baseline.py"]),
        ("Held-out benchmark freeze guard", [py, "scripts/validate_stage11_heldout_benchmark.py"]),
        ("Final Stage 11 evaluation reproduction", [py, "scripts/validate_stage11_final_evaluation.py"]),
        (
            "Stage 13 reproducibility contract",
            [py, "scripts/validate_stage13_reproducibility.py", "--require-locks", "--docker-compose-config"],
        ),
        (
            "Stage 12 regression verification",
            [py, "scripts/run_stage12_verification.py", "--frontend", "required"],
        ),
    ]

    for label, cmd in gates:
        if not run(label, cmd):
            return 1

    if not args.skip_container_tests:
        if not run(
            "Locked backend container regression",
            ["docker", "compose", "--profile", "verify", "run", "--rm", "--build", "backend-test"],
        ):
            return 1

    if args.include_docker_smoke:
        if not run("Clean Docker startup smoke", [py, "scripts/run_stage13_docker_smoke.py"]):
            return 1

    print("\n=== Stage 13 verification summary ===")
    print("Frozen RAG/evaluation guards: PASS")
    print("Dependency/toolchain lock contract: PASS")
    print("Stage 12 regression: PASS")
    print(f"Locked backend container regression: {'PASS' if not args.skip_container_tests else 'not-run'}")
    print(f"Clean Docker smoke: {'PASS' if args.include_docker_smoke else 'not-run'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
