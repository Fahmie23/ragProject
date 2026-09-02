from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.services.evaluation.baseline_guard import load_manifest, validate_frozen_baseline

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_heldout_v1.json"
VALIDATOR = BACKEND_ROOT / "scripts" / "validate_answer_citation_eval_dataset.py"
SOURCE_VALIDATOR = BACKEND_ROOT / "scripts" / "validate_answer_citation_eval_source.py"
INDEPENDENCE = BACKEND_ROOT / "scripts" / "audit_stage11_heldout_independence.py"
FREEZE_VALIDATOR = BACKEND_ROOT / "scripts" / "validate_stage11_heldout_benchmark.py"
HELDOUT_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_heldout_benchmark_manifest_v1.json"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=BACKEND_ROOT, text=True, capture_output=True, check=False)


def test_stage11_heldout_dataset_is_frozen_and_has_intended_shape():
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    assert data["dataset_id"] == "answer_citation_eval_heldout_v1"
    assert data["benchmark_status"] == "frozen"
    assert data["counts"] == {"questions": 18, "dev": 0, "heldout": 18, "answered": 15, "insufficient_evidence": 3}
    assert all(q["split"] == "heldout" for q in data["questions"])
    assert len({q["question_id"] for q in data["questions"]}) == 18
    assert {q["question_id"] for q in data["questions"]} == {f"ACIT-{i:03d}" for i in range(101, 119)}
    result = _run(str(VALIDATOR), str(DATASET))
    assert result.returncode == 0, result.stdout + result.stderr


def test_stage11_heldout_gold_sources_resolve_against_frozen_canonical():
    result = _run(str(SOURCE_VALIDATOR), str(DATASET))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Required source groups: 28" in result.stdout
    assert "Gold locators checked: 28" in result.stdout


def test_stage11_heldout_is_independent_from_prior_benchmarks(tmp_path: Path):
    report = tmp_path / "independence.json"
    result = _run(str(INDEPENDENCE), str(DATASET), "--output", str(report))
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["valid"] is True
    assert payload["exact_duplicate_count"] == 0
    assert payload["similarity_warning_count"] == 0
    assert payload["question_id_collision_count"] == 0
    assert payload["exact_dev_gold_locator_overlap_count"] == 0


def test_stage11_heldout_dataset_hash_is_frozen():
    result = validate_frozen_baseline(backend_root=BACKEND_ROOT, manifest=load_manifest(HELDOUT_MANIFEST))
    assert result["valid"] is True
    assert result["checked_file_count"] == 1


def test_stage11_heldout_full_freeze_validator_passes():
    result = _run(str(FREEZE_VALIDATOR))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: frozen Stage 11.3 held-out benchmark" in result.stdout
    assert "Independence audit: PASS" in result.stdout


def test_stage11_heldout_freeze_rejects_alternate_frozen_dataset_path(tmp_path: Path):
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["questions"][0]["question"] += " "
    tampered = tmp_path / "tampered_heldout.json"
    tampered.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = _run(str(FREEZE_VALIDATOR), "--dataset", str(tampered))
    assert result.returncode == 1
    assert "executed dataset hash mismatch" in result.stdout
