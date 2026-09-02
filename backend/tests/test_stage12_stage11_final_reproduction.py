from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = BACKEND_ROOT / "scripts" / "validate_stage11_final_evaluation.py"


def test_frozen_stage11_final_evaluation_reproduces_without_api_calls():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: frozen Stage 11 final evaluation reproduced offline" in result.stdout
    assert "Responses: 18 exact hash-bound held-out snapshots" in result.stdout
    assert "External API calls: 0" in result.stdout
