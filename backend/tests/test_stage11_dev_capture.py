from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CAPTURE = BACKEND_ROOT / "scripts" / "capture_answer_citation_dev.py"


def test_stage11_dev_capture_dry_run_passes_all_guards():
    result = subprocess.run(
        [sys.executable, str(CAPTURE), "--dry-run"],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "20 selected DEV questions" in result.stdout
    assert "DRY RUN PASS" in result.stdout


def test_stage11_dev_capture_can_select_one_question_in_dry_run():
    result = subprocess.run(
        [sys.executable, str(CAPTURE), "--dry-run", "--question-id", "ACIT-017"],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 selected DEV questions" in result.stdout
    assert "ACIT-017" in result.stdout
    assert "ACIT-001" not in result.stdout
