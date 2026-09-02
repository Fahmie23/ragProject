#!/usr/bin/env python3
"""Capture the frozen Stage 11.3 held-out benchmark exactly once, with resume safety.

Safety properties:
- heldout-only and benchmark_status=frozen;
- validates canonical gold locators, independence, production freeze, semantic
  rubric freeze, and held-out dataset hash before any API request;
- actual API calls require the exact held-out confirmation token;
- no overwrite or single-question selection path exists;
- valid responses are immutable and skipped on resume;
- failed/missing responses may be resumed without regenerating valid results;
- rate-limit aware and preserves raw API JSON for offline scoring.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.generation_metrics import (  # noqa: E402
    ANSWER_CITATION_HELDOUT_CONFIRMATION,
    validate_response_invariants,
)
from scripts.capture_answer_citation_dev import (  # noqa: E402
    _atomic_write,
    _existing_response_usable,
    _load_json,
    _post_with_rate_limit_retry,
    _provider_status_code,
)
from scripts.validate_stage11_heldout_benchmark import (  # noqa: E402
    DEFAULT_CANONICAL,
    DEFAULT_DEV,
    DEFAULT_HELDOUT_MANIFEST,
    DEFAULT_PRODUCTION_MANIFEST,
    DEFAULT_RETRIEVAL,
    DEFAULT_SEMANTIC_MANIFEST,
    _load_retrieval,
    validate_heldout_benchmark,
)

DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_heldout_v1.json"
DEFAULT_OUTPUT = BACKEND_ROOT / "evaluation" / "reports" / "stage11_3_heldout_capture_v1" / "responses"


def _validate_setup(args: argparse.Namespace, dataset: dict[str, Any]) -> list[str]:
    return validate_heldout_benchmark(
        dataset=dataset,
        canonical=_load_json(args.canonical),
        dev=_load_json(args.dev_dataset),
        retrieval_rows=_load_retrieval(args.retrieval_dataset),
        production_manifest=args.production_manifest,
        semantic_manifest=args.semantic_manifest,
        heldout_manifest=args.heldout_manifest,
        dataset_path=args.dataset,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture frozen Stage 11.3 held-out answer/citation responses")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    ap.add_argument("--dev-dataset", type=Path, default=DEFAULT_DEV)
    ap.add_argument("--retrieval-dataset", type=Path, default=DEFAULT_RETRIEVAL)
    ap.add_argument("--production-manifest", type=Path, default=DEFAULT_PRODUCTION_MANIFEST)
    ap.add_argument("--semantic-manifest", type=Path, default=DEFAULT_SEMANTIC_MANIFEST)
    ap.add_argument("--heldout-manifest", type=Path, default=DEFAULT_HELDOUT_MANIFEST)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--delay-seconds", type=float, default=30.0)
    ap.add_argument("--max-rate-limit-retries", type=int, default=2)
    ap.add_argument("--rate-limit-buffer-seconds", type=float, default=2.0)
    ap.add_argument("--timeout-seconds", type=float, default=180.0)
    ap.add_argument("--confirm-heldout", help=f"Required for live capture: {ANSWER_CITATION_HELDOUT_CONFIRMATION}")
    ap.add_argument("--dry-run", action="store_true", help="Validate all freeze guards and list questions; no API calls")
    args = ap.parse_args()

    if args.delay_seconds < 0 or args.max_rate_limit_retries < 0 or args.rate_limit_buffer_seconds < 0 or args.timeout_seconds <= 0:
        ap.error("delay/retry values must be non-negative and timeout must be > 0")

    dataset = _load_json(args.dataset)
    errors = _validate_setup(args, dataset)
    if errors:
        print(f"REFUSED: {len(errors)} Stage 11.3 setup error(s)")
        for error in errors:
            print(f"- {error}")
        return 2

    questions = list(dataset.get("questions") or [])
    print(f"Dataset: {dataset.get('dataset_id')} ({len(questions)} frozen HELD-OUT questions)")
    print(f"Frozen retrieval profile: {dataset['policy']['retrieval_profile']}")
    print(f"Citation version: {dataset['policy']['citation_version']}")
    print("Held-out benchmark hash: PASS")
    print("Prior-benchmark independence: PASS")
    for question in questions:
        print(f"- {question['question_id']} [{question['category']}/{question['difficulty']}] {question['question']}")
    if args.dry_run:
        print("DRY RUN PASS: all held-out freeze guards are valid; no API calls made.")
        return 0

    if args.confirm_heldout != ANSWER_CITATION_HELDOUT_CONFIRMATION:
        print("REFUSED: live held-out capture requires exact confirmation token:")
        print(f"  --confirm-heldout {ANSWER_CITATION_HELDOUT_CONFIRMATION}")
        return 2

    status_response = requests.get(f"{args.base_url}/api/system/generation", timeout=15)
    status_response.raise_for_status()
    system = status_response.json()
    if not system.get("api_key_configured"):
        print("Generation API key is not configured. Set GROQ_API_KEY or GENERATION_API_KEY and restart FastAPI.")
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []
    failures = 0
    newly_captured = 0
    skipped = 0
    previous_call_made = False
    document_id = str(dataset["document"]["document_id"])
    citation_version = str(dataset["policy"]["citation_version"])

    for index, question in enumerate(questions, start=1):
        qid = str(question["question_id"])
        output_path = args.output_dir / f"{qid}.json"
        if _existing_response_usable(
            output_path,
            document_id=document_id,
            question=str(question["question"]),
            citation_version=citation_version,
        ):
            skipped += 1
            summary_rows.append({"question_id": qid, "capture_status": "skipped_frozen_existing"})
            print(f"[{index}/{len(questions)}] {qid}: SKIP frozen valid existing response")
            continue

        if previous_call_made and args.delay_seconds > 0:
            print(f"Waiting {args.delay_seconds:.1f}s before next held-out request ...", flush=True)
            time.sleep(args.delay_seconds)
        previous_call_made = True
        print(f"[{index}/{len(questions)}] {qid}: capture ...", flush=True)
        started = time.perf_counter()
        response, retries = _post_with_rate_limit_retry(
            url=f"{args.base_url}/api/generation/answer",
            payload={"document_id": document_id, "question": str(question["question"])},
            timeout=args.timeout_seconds,
            max_retries=args.max_rate_limit_retries,
            retry_buffer_seconds=args.rate_limit_buffer_seconds,
            fallback_retry_seconds=max(args.delay_seconds, 30.0),
        )
        elapsed = time.perf_counter() - started
        if not response.ok:
            failures += 1
            record = {
                "question_id": qid,
                "question": question["question"],
                "http_status": response.status_code,
                "provider_status_code": _provider_status_code(response),
                "rate_limit_retries": retries,
                "elapsed_seconds": round(elapsed, 3),
                "body": response.text,
            }
            _atomic_write(args.output_dir / f"{qid}.error.json", record)
            summary_rows.append({"question_id": qid, "capture_status": "http_error", **record})
            print(f"  FAIL HTTP {response.status_code}")
            continue

        data = response.json()
        if data.get("document_id") != document_id or data.get("question") != question["question"]:
            failures += 1
            summary_rows.append({"question_id": qid, "capture_status": "response_identity_mismatch"})
            print("  FAIL response document/question identity mismatch")
            continue
        invariant_errors = validate_response_invariants(data, expected_citation_version=citation_version)
        if invariant_errors:
            failures += 1
            _atomic_write(args.output_dir / f"{qid}.invalid.json", {"response": data, "invariant_errors": invariant_errors})
            summary_rows.append({
                "question_id": qid,
                "capture_status": "invalid_stage10_response",
                "elapsed_seconds": round(elapsed, 3),
                "rate_limit_retries": retries,
                "invariant_errors": invariant_errors,
            })
            print(f"  FAIL {len(invariant_errors)} Stage 10 invariant error(s)")
            continue

        _atomic_write(output_path, data)
        newly_captured += 1
        summary_rows.append({
            "question_id": qid,
            "capture_status": "captured",
            "actual_status": data.get("status"),
            "expected_status": question.get("expected_status"),
            "elapsed_seconds": round(elapsed, 3),
            "rate_limit_retries": retries,
            "claim_count": len(data.get("claims") or []),
            "citation_count": len(data.get("citations") or []),
        })
        print(f"  CAPTURED {data.get('status')} · {len(data.get('claims') or [])} claims · {len(data.get('citations') or [])} citations")

    captured_files = sum(1 for question in questions if (args.output_dir / f"{question['question_id']}.json").exists())
    summary = {
        "capture_stage": "11.3",
        "dataset_id": dataset.get("dataset_id"),
        "benchmark_status": dataset.get("benchmark_status"),
        "heldout_confirmation_verified": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_question_count": len(questions),
        "valid_response_file_count": captured_files,
        "newly_captured_count": newly_captured,
        "skipped_frozen_existing_count": skipped,
        "failure_count": failures,
        "complete": failures == 0 and captured_files == len(questions),
        "rows": summary_rows,
    }
    _atomic_write(args.output_dir.parent / "capture_summary.json", summary)
    print(f"Capture summary: {args.output_dir.parent / 'capture_summary.json'}")
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
