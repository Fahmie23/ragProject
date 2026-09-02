#!/usr/bin/env python3
"""Offline Stage 11 answer/citation scorer.

The deterministic path always runs. Semantic metrics are optional and are computed
only from a frozen, human-confirmed calibration artifact under the frozen Stage 11
semantic rubric. This runner never calls an LLM.
"""

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
from app.services.evaluation.generation_metrics import (  # noqa: E402
    ANSWER_CITATION_HELDOUT_CONFIRMATION,
    aggregate_deterministic_results,
    enforce_answer_citation_split_policy,
    grouped_deterministic_aggregates,
    score_deterministic_response,
)
from scripts.validate_stage11_heldout_benchmark import (  # noqa: E402
    DEFAULT_CANONICAL as DEFAULT_HELDOUT_CANONICAL,
    DEFAULT_DEV as DEFAULT_HELDOUT_DEV,
    DEFAULT_HELDOUT_MANIFEST,
    DEFAULT_RETRIEVAL as DEFAULT_HELDOUT_RETRIEVAL,
    _load_retrieval as _load_heldout_retrieval,
    validate_heldout_benchmark,
)
from scripts.validate_answer_citation_eval_source import _load as _load_source_json  # noqa: E402

from app.services.evaluation.semantic_metrics import (  # noqa: E402
    aggregate_semantic_results,
    canonical_json_sha256,
    score_semantic_question,
    validate_semantic_calibration,
)

DEFAULT_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_frozen_pipeline_manifest_v1.json"
DEFAULT_SEMANTIC_RUBRIC = BACKEND_ROOT / "evaluation" / "generation" / "stage11_semantic_rubric_v1.json"
DEFAULT_SEMANTIC_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_semantic_evaluation_manifest_v1.json"


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score captured Stage 11 answer/citation JSON responses")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--responses-dir", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "heldout"], default="dev")
    parser.add_argument("--output-dir", type=Path, default=Path("answer_citation_evaluation_results"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--semantic-calibration", type=Path, help="Frozen human-labelled semantic calibration JSON")
    parser.add_argument("--semantic-rubric", type=Path, default=DEFAULT_SEMANTIC_RUBRIC)
    parser.add_argument("--semantic-manifest", type=Path, default=DEFAULT_SEMANTIC_MANIFEST)
    parser.add_argument("--confirm-heldout")
    args = parser.parse_args()

    dataset = _load_json(args.dataset)
    enforce_answer_citation_split_policy(
        split=args.split,
        confirmation=args.confirm_heldout,
        benchmark_status=str(dataset.get("benchmark_status")),
    )

    if args.split == "heldout":
        heldout_errors = validate_heldout_benchmark(
            dataset=dataset,
            canonical=_load_source_json(DEFAULT_HELDOUT_CANONICAL),
            dev=_load_json(DEFAULT_HELDOUT_DEV),
            retrieval_rows=_load_heldout_retrieval(DEFAULT_HELDOUT_RETRIEVAL),
            production_manifest=DEFAULT_MANIFEST,
            semantic_manifest=DEFAULT_SEMANTIC_MANIFEST,
            heldout_manifest=DEFAULT_HELDOUT_MANIFEST,
            dataset_path=args.dataset,
        )
        if heldout_errors:
            print("Frozen Stage 11.3 held-out benchmark validation failed; refusing to score.")
            for error in heldout_errors:
                print(f"- {error}")
            return 5

    baseline = validate_frozen_baseline(
        backend_root=BACKEND_ROOT,
        manifest=load_manifest(args.manifest),
    )
    if not baseline["valid"]:
        print("Frozen Stage 11 baseline validation failed; refusing to score.")
        for error in baseline["errors"]:
            print(f"- {error}")
        return 2

    questions = [q for q in dataset.get("questions", []) if q.get("split") == args.split]
    if not questions:
        raise SystemExit(f"dataset contains no {args.split!r} questions")

    semantic_calibration: dict[str, Any] | None = None
    semantic_by_id: dict[str, dict[str, Any]] = {}
    semantic_rubric: dict[str, Any] | None = None
    semantic_baseline: dict[str, Any] | None = None
    if args.semantic_calibration:
        semantic_baseline = validate_frozen_baseline(
            backend_root=BACKEND_ROOT,
            manifest=load_manifest(args.semantic_manifest),
        )
        if not semantic_baseline["valid"]:
            print("Frozen Stage 11 semantic-evaluation manifest failed; refusing semantic scoring.")
            for error in semantic_baseline["errors"]:
                print(f"- {error}")
            return 4
        semantic_calibration = _load_json(args.semantic_calibration)
        semantic_rubric = _load_json(args.semantic_rubric)
        selected_ids = {str(q["question_id"]) for q in questions}
        semantic_ids = {str(q.get("question_id")) for q in semantic_calibration.get("questions") or []}
        outside = sorted(semantic_ids - selected_ids)
        if outside:
            raise SystemExit(f"semantic calibration contains question(s) outside split {args.split!r}: {outside}")
        semantic_by_id = {str(q["question_id"]): q for q in semantic_calibration.get("questions") or []}

    rows: list[dict[str, Any]] = []
    loaded_responses: dict[str, dict[str, Any]] = {}
    missing = 0
    for question in questions:
        question_id = str(question["question_id"])
        response_path = args.responses_dir / f"{question_id}.json"
        if not response_path.exists():
            missing += 1
            rows.append({
                "question_id": question_id,
                "split": args.split,
                "category": question.get("category"),
                "difficulty": question.get("difficulty"),
                "status": "missing_response",
                "metrics": None,
                "semantic_evaluation": "not_scored",
            })
            continue

        response = _load_json(response_path)
        loaded_responses[question_id] = response
        metrics = score_deterministic_response(
            response=response,
            expected_status=str(question["expected_status"]),
            required_source_groups=question.get("gold", {}).get("required_source_groups", []),
            expected_citation_version=str(dataset.get("policy", {}).get("citation_version", "deterministic_citations_v1_2")),
        )
        semantic_question = semantic_by_id.get(question_id)
        rows.append({
            "question_id": question_id,
            "split": args.split,
            "category": question.get("category"),
            "difficulty": question.get("difficulty"),
            "status": "ok",
            "metrics": metrics,
            "semantic_evaluation": "human_frozen_rubric" if semantic_question else "not_scored",
            "semantic_metrics": score_semantic_question(semantic_question) if semantic_question else None,
        })

    if semantic_calibration is not None and semantic_rubric is not None:
        semantic_errors = validate_semantic_calibration(
            semantic_calibration,
            rubric=semantic_rubric,
            dataset=dataset,
            responses_by_id=loaded_responses,
        )
        if semantic_errors:
            print("Frozen semantic calibration validation failed; refusing semantic scoring.")
            for error in semantic_errors:
                print(f"- {error}")
            return 3

    scored = [row for row in rows if row["status"] == "ok"]
    aggregate = aggregate_deterministic_results(scored)
    aggregate["expected_question_count"] = len(questions)
    aggregate["missing_response_count"] = missing
    aggregate["complete"] = missing == 0

    semantic_questions = list(semantic_by_id.values()) if semantic_calibration is not None else []
    semantic_aggregate = aggregate_semantic_results(semantic_questions) if semantic_questions else None
    if semantic_aggregate is None:
        aggregate["semantic_metrics_status"] = "not_scored"
    else:
        aggregate["semantic_metrics_status"] = "scored_human_frozen_rubric"
        aggregate["semantic_calibration_question_count"] = semantic_aggregate["semantic_question_count"]

    output = {
        "schema_version": "1.0",
        "evaluation_stage": "11.2C",
        "evaluation_mode": "deterministic_plus_human_semantic" if semantic_aggregate else "deterministic_only",
        "dataset_id": dataset.get("dataset_id"),
        "benchmark_status": dataset.get("benchmark_status"),
        "split": args.split,
        "baseline": {
            "baseline_id": baseline.get("baseline_id"),
            "valid": baseline.get("valid"),
            "checked_file_count": baseline.get("checked_file_count"),
        },
        "aggregate_metrics": aggregate,
        "semantic_evaluation": {
            "status": aggregate["semantic_metrics_status"],
            "rubric_version": semantic_calibration.get("rubric_version") if semantic_calibration else None,
            "calibration_id": semantic_calibration.get("calibration_id") if semantic_calibration else None,
            "dataset_canonical_sha256": canonical_json_sha256(dataset) if semantic_calibration else None,
            "scope": "human_labelled_calibration_subset" if semantic_calibration else None,
            "semantic_baseline_id": semantic_baseline.get("baseline_id") if semantic_baseline else None,
            "semantic_baseline_valid": semantic_baseline.get("valid") if semantic_baseline else None,
            "aggregate_metrics": semantic_aggregate,
        },
        "by_category": grouped_deterministic_aggregates(scored, field="category"),
        "by_difficulty": grouped_deterministic_aggregates(scored, field="difficulty"),
        "results": rows,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(args.output_dir / f"{args.split}_deterministic_results.json", output)
    _atomic_write_json(args.output_dir / f"{args.split}_aggregate_metrics.json", aggregate)
    if semantic_aggregate is not None:
        _atomic_write_json(args.output_dir / f"{args.split}_semantic_aggregate_metrics.json", semantic_aggregate)

    print(f"Scored {len(scored)}/{len(questions)} {args.split} responses")
    print(f"Missing responses: {missing}")
    print(f"AnswerStatusAccuracy: {aggregate.get('answer_status_accuracy')}")
    print(f"ClaimCitationCoverage: {aggregate.get('claim_citation_coverage')}")
    print(f"DeterministicCitationValidity: {aggregate.get('deterministic_citation_validity')}")
    print(f"RequiredSourceCoverage: {aggregate.get('required_source_coverage')}")
    if semantic_aggregate is None:
        print("Semantic metrics: NOT SCORED (no frozen human calibration provided)")
    else:
        print(f"Semantic calibration questions: {semantic_aggregate['semantic_question_count']}")
        print(f"ClaimSupportRate: {semantic_aggregate['claim_support_rate']}")
        print(f"CitationEntailmentRate: {semantic_aggregate['citation_entailment_rate']}")
        print(f"GoldClaimCoverage: {semantic_aggregate['gold_claim_coverage']}")
        print(f"AnswerCompleteness: {semantic_aggregate['answer_completeness']}")
        print(f"AnswerRelevanceMean: {semantic_aggregate['answer_relevance_mean']}")
    return 0 if missing == 0 and aggregate.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
