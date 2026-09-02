#!/usr/bin/env python3
"""Validate the frozen Stage 11.3 held-out benchmark and all freeze guards."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.baseline_guard import load_manifest, sha256_file, validate_frozen_baseline  # noqa: E402
from scripts.audit_stage11_heldout_independence import (  # noqa: E402
    DEFAULT_DEV,
    DEFAULT_RETRIEVAL,
    _load_retrieval,
    audit_independence,
)
from scripts.validate_answer_citation_eval_dataset import validate_dataset  # noqa: E402
from scripts.validate_answer_citation_eval_source import DEFAULT_CANONICAL, validate_source  # noqa: E402

DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_heldout_v1.json"
DEFAULT_PRODUCTION_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_frozen_pipeline_manifest_v1.json"
DEFAULT_SEMANTIC_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_semantic_evaluation_manifest_v1.json"
DEFAULT_HELDOUT_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_heldout_benchmark_manifest_v1.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def validate_heldout_benchmark(
    *,
    dataset: dict[str, Any],
    canonical: dict[str, Any],
    dev: dict[str, Any],
    retrieval_rows: list[dict[str, str]],
    production_manifest: Path,
    semantic_manifest: Path,
    heldout_manifest: Path,
    dataset_path: Path | None = None,
) -> list[str]:
    errors = list(validate_dataset(dataset))
    errors.extend(validate_source(dataset, canonical))
    if dataset.get("benchmark_status") != "frozen":
        errors.append("Stage 11.3 held-out benchmark must have benchmark_status='frozen'")
    if any(q.get("split") != "heldout" for q in dataset.get("questions") or []):
        errors.append("Stage 11.3 benchmark must contain heldout records only")
    counts = dataset.get("counts") or {}
    if int(counts.get("dev", 0)) != 0 or int(counts.get("heldout", 0)) != len(dataset.get("questions") or []):
        errors.append("Stage 11.3 counts must contain heldout questions only")

    independence = audit_independence(dataset, dev=dev, retrieval_rows=retrieval_rows)
    if not independence.get("valid"):
        errors.append(
            "held-out independence audit failed: "
            f"duplicates={independence['exact_duplicate_count']}, "
            f"similarity_warnings={independence['similarity_warning_count']}, "
            f"id_collisions={independence['question_id_collision_count']}, "
            f"dev_locator_overlaps={independence['exact_dev_gold_locator_overlap_count']}"
        )

    heldout_manifest_data = load_manifest(heldout_manifest)
    expected_dataset_sha = heldout_manifest_data.get("files", {}).get("backend/evaluation/generation/answer_citation_eval_heldout_v1.json")
    if dataset_path is not None:
        actual_dataset_sha = sha256_file(dataset_path)
        if actual_dataset_sha != expected_dataset_sha:
            errors.append(
                f"heldout freeze: executed dataset hash mismatch: {actual_dataset_sha} != {expected_dataset_sha}"
            )

    for label, manifest_path in (
        ("production", production_manifest),
        ("semantic", semantic_manifest),
        ("heldout", heldout_manifest),
    ):
        result = validate_frozen_baseline(backend_root=BACKEND_ROOT, manifest=load_manifest(manifest_path))
        if not result.get("valid"):
            errors.extend(f"{label} freeze: {item}" for item in result.get("errors") or [])
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate frozen Stage 11.3 held-out benchmark")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    ap.add_argument("--dev-dataset", type=Path, default=DEFAULT_DEV)
    ap.add_argument("--retrieval-dataset", type=Path, default=DEFAULT_RETRIEVAL)
    ap.add_argument("--production-manifest", type=Path, default=DEFAULT_PRODUCTION_MANIFEST)
    ap.add_argument("--semantic-manifest", type=Path, default=DEFAULT_SEMANTIC_MANIFEST)
    ap.add_argument("--heldout-manifest", type=Path, default=DEFAULT_HELDOUT_MANIFEST)
    args = ap.parse_args()

    dataset = _load(args.dataset)
    errors = validate_heldout_benchmark(
        dataset=dataset,
        canonical=_load(args.canonical),
        dev=_load(args.dev_dataset),
        retrieval_rows=_load_retrieval(args.retrieval_dataset),
        production_manifest=args.production_manifest,
        semantic_manifest=args.semantic_manifest,
        heldout_manifest=args.heldout_manifest,
        dataset_path=args.dataset,
    )
    if errors:
        print(f"FAIL: {len(errors)} Stage 11.3 held-out benchmark error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS: frozen Stage 11.3 held-out benchmark")
    print(f"Dataset: {dataset['dataset_id']}")
    print(f"Questions: {len(dataset['questions'])}")
    print("Split: heldout only")
    print("Benchmark status: frozen")
    print("Production freeze: PASS")
    print("Semantic rubric freeze: PASS")
    print("Held-out dataset hash freeze: PASS")
    print("Independence audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
