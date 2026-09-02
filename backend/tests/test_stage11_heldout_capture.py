from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CAPTURE = BACKEND_ROOT / "scripts" / "capture_answer_citation_heldout.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CAPTURE), *args], cwd=BACKEND_ROOT, text=True, capture_output=True, check=False)


def test_stage11_heldout_capture_dry_run_passes_without_api_calls():
    result = _run("--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "18 frozen HELD-OUT questions" in result.stdout
    assert "Held-out benchmark hash: PASS" in result.stdout
    assert "Prior-benchmark independence: PASS" in result.stdout
    assert "DRY RUN PASS" in result.stdout


def test_stage11_heldout_capture_refuses_live_run_without_exact_confirmation():
    result = _run()
    assert result.returncode == 2
    assert "REFUSED: live held-out capture requires exact confirmation token" in result.stdout
    assert "RUN_FROZEN_ANSWER_CITATION_HELDOUT_V1" in result.stdout
