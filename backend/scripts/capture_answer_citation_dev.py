#!/usr/bin/env python3
"""Capture fresh Stage 11.2 DEV responses from the frozen production endpoint.

Safety properties:
- DEV only; no held-out execution path.
- Validates dataset contract, canonical gold locators, and frozen baseline first.
- Resumable by default; valid existing responses are not regenerated.
- Rate-limit aware using the same Groq/provider behavior as Stage 10 smoke.
- Saves raw API JSON per question for deterministic offline scoring.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.baseline_guard import load_manifest, validate_frozen_baseline  # noqa: E402
from app.services.evaluation.generation_metrics import validate_response_invariants  # noqa: E402
from scripts.validate_answer_citation_eval_dataset import validate_dataset  # noqa: E402
from scripts.validate_answer_citation_eval_source import DEFAULT_CANONICAL, validate_source  # noqa: E402

DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_v1.json"
DEFAULT_MANIFEST = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_frozen_pipeline_manifest_v1.json"
DEFAULT_OUTPUT = BACKEND_ROOT / "evaluation" / "reports" / "stage11_2_dev_capture_v1" / "responses"
RATE_LIMIT_RE = re.compile(r"Please try again in\s+([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def _provider_status_code(response: requests.Response) -> int | None:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return response.status_code if response.status_code == 429 else None
    if response.status_code == 429:
        return 429
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get("provider_status_code"), int):
        return int(detail["provider_status_code"])
    return None


def _provider_retry_after_seconds(response: requests.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            provider_detail = detail.get("provider_detail")
            if isinstance(provider_detail, dict):
                error = provider_detail.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    match = RATE_LIMIT_RE.search(error["message"])
                    if match:
                        return float(match.group(1))
    match = RATE_LIMIT_RE.search(response.text or "")
    return float(match.group(1)) if match else None


def _post_with_rate_limit_retry(
    *, url: str, payload: dict[str, str], timeout: float, max_retries: int,
    retry_buffer_seconds: float, fallback_retry_seconds: float,
) -> tuple[requests.Response, int]:
    retries = 0
    while True:
        response = requests.post(url, json=payload, timeout=timeout)
        if response.ok or _provider_status_code(response) != 429 or retries >= max_retries:
            return response, retries
        suggested = _provider_retry_after_seconds(response)
        wait_seconds = (suggested if suggested is not None else fallback_retry_seconds) + retry_buffer_seconds
        retries += 1
        print(f"  provider rate limit; waiting {wait_seconds:.1f}s ({retries}/{max_retries})", flush=True)
        time.sleep(wait_seconds)


def _validate_setup(dataset: dict[str, Any], canonical: dict[str, Any], manifest_path: Path) -> list[str]:
    errors = list(validate_dataset(dataset))
    errors.extend(validate_source(dataset, canonical))
    if any(q.get("split") != "dev" for q in dataset.get("questions") or []):
        errors.append("Stage 11.2 capture dataset must contain DEV records only")
    if int((dataset.get("counts") or {}).get("heldout", 0)) != 0:
        errors.append("Stage 11.2 capture refuses datasets with heldout questions")
    baseline = validate_frozen_baseline(backend_root=BACKEND_ROOT, manifest=load_manifest(manifest_path))
    if not baseline.get("valid"):
        errors.extend(f"frozen baseline: {item}" for item in baseline.get("errors") or [])
    return errors


def _existing_response_usable(path: Path, *, document_id: str, question: str, citation_version: str) -> bool:
    if not path.exists():
        return False
    try:
        response = _load_json(path)
    except Exception:
        return False
    if response.get("document_id") != document_id or response.get("question") != question:
        return False
    return not validate_response_invariants(response, expected_citation_version=citation_version)


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture fresh Stage 11.2 DEV answer/citation responses")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--delay-seconds", type=float, default=30.0)
    ap.add_argument("--max-rate-limit-retries", type=int, default=2)
    ap.add_argument("--rate-limit-buffer-seconds", type=float, default=2.0)
    ap.add_argument("--timeout-seconds", type=float, default=180.0)
    ap.add_argument("--question-id", action="append", default=[], help="Capture only selected ACIT-### IDs; repeatable")
    ap.add_argument("--overwrite", action="store_true", help="Regenerate even when a valid response already exists")
    ap.add_argument("--dry-run", action="store_true", help="Validate all guards and list questions without API calls")
    args = ap.parse_args()

    if args.delay_seconds < 0 or args.max_rate_limit_retries < 0 or args.rate_limit_buffer_seconds < 0 or args.timeout_seconds <= 0:
        ap.error("delay/retry values must be non-negative and timeout must be > 0")

    dataset = _load_json(args.dataset)
    canonical = _load_json(args.canonical)
    setup_errors = _validate_setup(dataset, canonical, args.manifest)
    if setup_errors:
        print(f"REFUSED: {len(setup_errors)} Stage 11.2 setup error(s)")
        for error in setup_errors:
            print(f"- {error}")
        return 2

    questions = list(dataset.get("questions") or [])
    by_id = {str(q["question_id"]): q for q in questions}
    if args.question_id:
        unknown = [qid for qid in args.question_id if qid not in by_id]
        if unknown:
            print(f"Unknown question IDs: {unknown}")
            return 2
        questions = [by_id[qid] for qid in args.question_id]

    print(f"Dataset: {dataset.get('dataset_id')} ({len(questions)} selected DEV questions)")
    print(f"Frozen retrieval profile: {dataset['policy']['retrieval_profile']}")
    print(f"Citation version: {dataset['policy']['citation_version']}")
    for q in questions:
        print(f"- {q['question_id']} [{q['category']}/{q['difficulty']}] {q['question']}")
    if args.dry_run:
        print("DRY RUN PASS: dataset, source locators, and frozen baseline are valid; no API calls made.")
        return 0

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

    for index, q in enumerate(questions, start=1):
        qid = str(q["question_id"])
        output_path = args.output_dir / f"{qid}.json"
        if not args.overwrite and _existing_response_usable(
            output_path, document_id=document_id, question=str(q["question"]), citation_version=citation_version
        ):
            skipped += 1
            summary_rows.append({"question_id": qid, "capture_status": "skipped_valid_existing"})
            print(f"[{index}/{len(questions)}] {qid}: SKIP valid existing response")
            continue

        if previous_call_made and args.delay_seconds > 0:
            print(f"Waiting {args.delay_seconds:.1f}s before next generation request ...", flush=True)
            time.sleep(args.delay_seconds)
        previous_call_made = True
        print(f"[{index}/{len(questions)}] {qid}: capture ...", flush=True)
        started = time.perf_counter()
        response, retries = _post_with_rate_limit_retry(
            url=f"{args.base_url}/api/generation/answer",
            payload={"document_id": document_id, "question": str(q["question"])},
            timeout=args.timeout_seconds,
            max_retries=args.max_rate_limit_retries,
            retry_buffer_seconds=args.rate_limit_buffer_seconds,
            fallback_retry_seconds=max(args.delay_seconds, 30.0),
        )
        elapsed = time.perf_counter() - started
        if not response.ok:
            failures += 1
            error_record = {
                "question_id": qid,
                "question": q["question"],
                "http_status": response.status_code,
                "provider_status_code": _provider_status_code(response),
                "rate_limit_retries": retries,
                "elapsed_seconds": round(elapsed, 3),
                "body": response.text,
            }
            _atomic_write(args.output_dir / f"{qid}.error.json", error_record)
            summary_rows.append({"question_id": qid, "capture_status": "http_error", **error_record})
            print(f"  FAIL HTTP {response.status_code}")
            continue

        data = response.json()
        if data.get("document_id") != document_id or data.get("question") != q["question"]:
            failures += 1
            summary_rows.append({"question_id": qid, "capture_status": "response_identity_mismatch"})
            print("  FAIL response document/question identity mismatch")
            continue
        invariant_errors = validate_response_invariants(data, expected_citation_version=citation_version)
        if invariant_errors:
            failures += 1
            _atomic_write(args.output_dir / f"{qid}.invalid.json", {"response": data, "invariant_errors": invariant_errors})
            summary_rows.append({
                "question_id": qid, "capture_status": "invalid_stage10_response",
                "elapsed_seconds": round(elapsed, 3), "rate_limit_retries": retries,
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
            "expected_status": q.get("expected_status"),
            "elapsed_seconds": round(elapsed, 3),
            "rate_limit_retries": retries,
            "claim_count": len(data.get("claims") or []),
            "citation_count": len(data.get("citations") or []),
        })
        print(f"  CAPTURED {data.get('status')} · {len(data.get('claims') or [])} claims · {len(data.get('citations') or [])} citations")

    captured_files = sum(1 for q in questions if (args.output_dir / f"{q['question_id']}.json").exists())
    summary = {
        "capture_stage": "11.2",
        "dataset_id": dataset.get("dataset_id"),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_question_count": len(questions),
        "valid_response_file_count": captured_files,
        "newly_captured_count": newly_captured,
        "skipped_valid_existing_count": skipped,
        "failure_count": failures,
        "complete": failures == 0 and captured_files == len(questions),
        "rows": summary_rows,
    }
    _atomic_write(args.output_dir.parent / "capture_summary.json", summary)
    print(f"Capture summary: {args.output_dir.parent / 'capture_summary.json'}")
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
