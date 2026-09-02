#!/usr/bin/env python3
"""Validate the frozen Stage 11 semantic rubric/calibration and response binding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.baseline_guard import load_manifest, validate_frozen_baseline  # noqa: E402
from app.services.evaluation.semantic_metrics import validate_semantic_calibration  # noqa: E402

DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_v1.json"
DEFAULT_RUBRIC = BACKEND_ROOT / "evaluation" / "generation" / "stage11_semantic_rubric_v1.json"
DEFAULT_CALIBRATION = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_calibration_v1_frozen.json"
DEFAULT_SEMANTIC_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_semantic_evaluation_manifest_v1.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate frozen Stage 11 semantic calibration")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    ap.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    ap.add_argument("--semantic-manifest", type=Path, default=DEFAULT_SEMANTIC_MANIFEST)
    ap.add_argument("--responses-dir", type=Path)
    args = ap.parse_args()

    semantic_baseline = validate_frozen_baseline(
        backend_root=BACKEND_ROOT,
        manifest=load_manifest(args.semantic_manifest),
    )
    if not semantic_baseline["valid"]:
        print("FAIL: frozen semantic-evaluation manifest mismatch")
        for error in semantic_baseline["errors"]:
            print(f"- {error}")
        return 2

    calibration = _load(args.calibration)
    responses: dict[str, dict[str, Any]] | None = None
    if args.responses_dir is not None:
        responses = {}
        for question in calibration.get("questions") or []:
            qid = str(question.get("question_id"))
            path = args.responses_dir / f"{qid}.json"
            if path.exists():
                responses[qid] = _load(path)

    errors = validate_semantic_calibration(
        calibration,
        rubric=_load(args.rubric),
        dataset=_load(args.dataset),
        responses_by_id=responses,
    )
    if errors:
        print(f"FAIL: {len(errors)} semantic calibration validation error(s)")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: frozen Stage 11 semantic calibration")
    print(f"Rubric: {calibration.get('rubric_version')}")
    print(f"Calibration: {calibration.get('calibration_id')}")
    print(f"Questions: {len(calibration.get('questions') or [])}")
    print(f"Semantic manifest: {semantic_baseline.get('baseline_id')} ({semantic_baseline.get('checked_file_count')} files)")
    print(f"Response binding checked: {args.responses_dir is not None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
