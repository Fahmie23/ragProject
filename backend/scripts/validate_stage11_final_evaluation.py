#!/usr/bin/env python3
"""Reproduce and validate the frozen Stage 11 final held-out evaluation offline.

This verifier never calls the generation provider. It re-scores only the already
captured one-time held-out response snapshots and compares the recomputed metrics
with the frozen Stage 11 final-evaluation manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.semantic_metrics import validate_semantic_calibration  # noqa: E402

DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_heldout_v1.json"
DEFAULT_RUBRIC = BACKEND_ROOT / "evaluation" / "generation" / "stage11_semantic_rubric_v1.json"
DEFAULT_CALIBRATION = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_heldout_calibration_v1_frozen.json"
DEFAULT_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_final_evaluation_manifest_v1.json"
DEFAULT_RESPONSES = BACKEND_ROOT / "evaluation" / "reports" / "stage11_3_heldout_capture_v1" / "responses"
SCORER = BACKEND_ROOT / "scripts" / "score_answer_citation_results.py"
CONFIRMATION = "RUN_FROZEN_ANSWER_CITATION_HELDOUT_V1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _compare_metrics(expected: dict[str, Any], actual: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, float) and isinstance(actual_value, (float, int)):
            if abs(float(expected_value) - float(actual_value)) > 1e-12:
                errors.append(f"{prefix}.{key}: {actual_value!r} != {expected_value!r}")
        elif actual_value != expected_value:
            errors.append(f"{prefix}.{key}: {actual_value!r} != {expected_value!r}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate frozen Stage 11 final held-out evaluation")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    ap.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--responses-dir", type=Path, default=DEFAULT_RESPONSES)
    args = ap.parse_args()

    errors: list[str] = []
    manifest = _load(args.manifest)
    dataset = _load(args.dataset)
    rubric = _load(args.rubric)
    calibration = _load(args.calibration)

    if manifest.get("status") != "frozen":
        errors.append("final evaluation manifest status must be 'frozen'")
    if manifest.get("one_time_heldout_run_consumed") is not True:
        errors.append("final evaluation manifest must record one_time_heldout_run_consumed=true")
    if manifest.get("heldout_tuning_authorized") is not False:
        errors.append("final evaluation manifest must keep heldout_tuning_authorized=false")
    if manifest.get("automated_judge_used") is not False:
        errors.append("final evaluation manifest must keep automated_judge_used=false")

    dataset_hash = _sha256(args.dataset)
    calibration_hash = _sha256(args.calibration)
    if dataset_hash != manifest.get("dataset_file_sha256"):
        errors.append(f"dataset file SHA-256 mismatch: {dataset_hash} != {manifest.get('dataset_file_sha256')}")
    if calibration_hash != manifest.get("calibration_file_sha256"):
        errors.append(f"calibration file SHA-256 mismatch: {calibration_hash} != {manifest.get('calibration_file_sha256')}")

    responses: dict[str, dict[str, Any]] = {}
    question_ids = [str(item.get("question_id")) for item in calibration.get("questions") or []]
    for qid in question_ids:
        path = args.responses_dir / f"{qid}.json"
        if not path.exists():
            errors.append(f"missing frozen held-out response: {path}")
            continue
        responses[qid] = _load(path)
    if len(responses) != int(manifest.get("response_count") or -1):
        errors.append(f"response count mismatch: {len(responses)} != {manifest.get('response_count')}")

    errors.extend(
        f"semantic calibration: {message}"
        for message in validate_semantic_calibration(
            calibration,
            rubric=rubric,
            dataset=dataset,
            responses_by_id=responses,
        )
    )

    if errors:
        print(f"FAIL: {len(errors)} frozen Stage 11 final-evaluation integrity error(s)")
        for error in errors:
            print(f"- {error}")
        return 1

    with tempfile.TemporaryDirectory(prefix="stage11-final-repro-") as temp_dir:
        out = Path(temp_dir)
        result = subprocess.run(
            [
                sys.executable,
                str(SCORER),
                "--dataset", str(args.dataset),
                "--responses-dir", str(args.responses_dir),
                "--split", "heldout",
                "--semantic-calibration", str(args.calibration),
                "--confirm-heldout", CONFIRMATION,
                "--output-dir", str(out),
            ],
            cwd=BACKEND_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print("FAIL: offline held-out re-score did not complete")
            print(result.stdout)
            print(result.stderr)
            return 2
        deterministic = _load(out / "heldout_aggregate_metrics.json")
        semantic = _load(out / "heldout_semantic_aggregate_metrics.json")

    metric_errors = []
    metric_errors.extend(_compare_metrics(manifest.get("deterministic_metrics") or {}, deterministic, "deterministic_metrics"))
    metric_errors.extend(_compare_metrics(manifest.get("semantic_metrics") or {}, semantic, "semantic_metrics"))
    if metric_errors:
        print(f"FAIL: {len(metric_errors)} frozen Stage 11 metric reproduction mismatch(es)")
        for error in metric_errors:
            print(f"- {error}")
        return 3

    print("PASS: frozen Stage 11 final evaluation reproduced offline")
    print(f"Evaluation: {manifest.get('evaluation_id')}")
    print(f"Responses: {len(responses)} exact hash-bound held-out snapshots")
    print(f"AnswerStatusAccuracy: {deterministic.get('answer_status_accuracy')}")
    print(f"DeterministicCitationValidity: {deterministic.get('deterministic_citation_validity')}")
    print(f"RequiredSourceCoverage: {deterministic.get('required_source_coverage')}")
    print(f"ClaimSupportRate: {semantic.get('claim_support_rate')}")
    print(f"AnswerCompleteness: {semantic.get('answer_completeness')}")
    print("External API calls: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
