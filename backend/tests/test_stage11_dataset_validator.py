from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "validate_answer_citation_eval_dataset.py"
TEMPLATE = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_template_v1.json"


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_stage11_dev_template_satisfies_contract():
    result = _run(TEMPLATE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS:" in result.stdout


def test_validator_rejects_answerable_record_without_source_groups(tmp_path: Path):
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    data["questions"][0]["gold"]["required_source_groups"] = []
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = _run(path)
    assert result.returncode == 1
    assert "has no required_source_groups" in result.stdout


def test_validator_rejects_incorrect_count_metadata(tmp_path: Path):
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    data["counts"]["questions"] = 99
    path = tmp_path / "bad_counts.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = _run(path)
    assert result.returncode == 1
    assert "counts.questions=99, expected 1" in result.stdout
