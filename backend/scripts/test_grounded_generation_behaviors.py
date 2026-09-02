#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

import requests

RATE_LIMIT_RE = re.compile(r"Please try again in\s+([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)


QUESTIONS = [
    ("01_definition_pep", "What is a politically exposed person?", "answerable"),
    ("02_delayed_verification", "What are the requirements for delayed verification?", "answerable"),
    ("03_non_face_to_face", "What measures are required when establishing a non-face-to-face business relationship?", "answerable"),
    ("04_verification_timeout", "What should an institution do when a customer cannot complete identity verification in time?", "answerable"),
    ("05_positive_designated_person_match", "What information must be reported when there is a positive match with a designated person?", "answerable"),
    ("06_out_of_scope_abstention", "What is the current price of Bitcoin?", "should_abstain"),
]


def _provider_status_code(response: requests.Response) -> int | None:
    """Return the upstream provider status when FastAPI wraps it in HTTP 502."""
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return response.status_code if response.status_code == 429 else None

    if response.status_code == 429:
        return 429
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        value = detail.get("provider_status_code")
        if isinstance(value, int):
            return value
    return None


def _provider_retry_after_seconds(response: requests.Response) -> float | None:
    """Extract Groq's suggested retry delay from either Retry-After or the wrapped error message."""
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
                if isinstance(error, dict):
                    message = error.get("message")
                    if isinstance(message, str):
                        match = RATE_LIMIT_RE.search(message)
                        if match:
                            return float(match.group(1))

    match = RATE_LIMIT_RE.search(response.text or "")
    return float(match.group(1)) if match else None


def _post_with_rate_limit_retry(
    *,
    url: str,
    payload: dict[str, str],
    timeout: float,
    max_retries: int,
    retry_buffer_seconds: float,
    fallback_retry_seconds: float,
) -> tuple[requests.Response, int]:
    retries = 0
    while True:
        response = requests.post(url, json=payload, timeout=timeout)
        if response.ok or _provider_status_code(response) != 429 or retries >= max_retries:
            return response, retries

        suggested = _provider_retry_after_seconds(response)
        wait_seconds = (suggested if suggested is not None else fallback_retry_seconds) + retry_buffer_seconds
        retries += 1
        print(
            f"  rate limited by provider; waiting {wait_seconds:.1f}s before retry "
            f"({retries}/{max_retries}) ...",
            flush=True,
        )
        time.sleep(wait_seconds)


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 9 grounded-generation smoke test")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--document-id", default="485c4989-c300-45c8-ac06-79a59492bb5c")
    ap.add_argument("--output-dir", type=Path, default=Path("grounded_generation_results_stage9"))
    ap.add_argument(
        "--delay-seconds",
        type=float,
        default=30.0,
        help="Delay between test cases to stay below provider TPM limits (default: 30s).",
    )
    ap.add_argument(
        "--max-rate-limit-retries",
        type=int,
        default=2,
        help="Retries for wrapped provider HTTP 429 responses (default: 2).",
    )
    ap.add_argument(
        "--rate-limit-buffer-seconds",
        type=float,
        default=2.0,
        help="Extra wait added to the provider's suggested retry delay (default: 2s).",
    )
    args = ap.parse_args()
    if args.delay_seconds < 0:
        ap.error("--delay-seconds must be >= 0")
    if args.max_rate_limit_retries < 0:
        ap.error("--max-rate-limit-retries must be >= 0")
    if args.rate_limit_buffer_seconds < 0:
        ap.error("--rate-limit-buffer-seconds must be >= 0")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    generation_status = requests.get(f"{args.base_url}/api/system/generation", timeout=15)
    generation_status.raise_for_status()
    status_payload = generation_status.json()
    if not status_payload.get("api_key_configured"):
        raise SystemExit("Generation API key is not configured. Set GROQ_API_KEY or GENERATION_API_KEY and restart FastAPI.")

    reports = []
    for index, (name, question, expectation) in enumerate(QUESTIONS, start=1):
        if index > 1 and args.delay_seconds > 0:
            print(
                f"Waiting {args.delay_seconds:.1f}s before the next generation test to respect provider TPM limits ...",
                flush=True,
            )
            time.sleep(args.delay_seconds)

        print(f"[{index}/{len(QUESTIONS)}] {name} ...", flush=True)
        started = time.perf_counter()
        response, rate_limit_retries = _post_with_rate_limit_retry(
            url=f"{args.base_url}/api/generation/answer",
            payload={"document_id": args.document_id, "question": question},
            timeout=180,
            max_retries=args.max_rate_limit_retries,
            retry_buffer_seconds=args.rate_limit_buffer_seconds,
            fallback_retry_seconds=max(args.delay_seconds, 30.0),
        )
        elapsed = time.perf_counter() - started
        if not response.ok:
            body = response.text
            report = f"QUESTION: {question}\nEXPECTATION: {expectation}\nRATE_LIMIT_RETRIES: {rate_limit_retries}\nHTTP: {response.status_code}\nERROR:\n{body}\n"
            (args.output_dir/f"{name}.txt").write_text(report, encoding="utf-8")
            reports.append(report)
            print(f"  ERROR HTTP {response.status_code}")
            continue

        data = response.json()
        lines = [
            f"QUESTION: {question}",
            f"EXPECTATION: {expectation}",
            f"STATUS: {data['status']}",
            f"ELAPSED_SECONDS: {elapsed:.2f}",
            f"RATE_LIMIT_RETRIES: {rate_limit_retries}",
            f"PROVIDER: {data['generation_provider']}",
            f"MODEL: {data['generation_model']}",
            f"PROMPT_VERSION: {data['prompt_version']}",
            f"RETRIEVAL_PROFILE: {data['retrieval_profile']}",
            f"CONTEXT_CHUNKS: {data['context_chunk_count']}",
            f"EXPANDED_CHUNKS: {data['expanded_chunk_count']}",
            f"USED_EVIDENCE_IDS: {data['used_evidence_ids']}",
            "",
            "ANSWER:",
            data['answer'],
            "",
            "CLAIMS:",
        ]
        for claim in data.get("claims", []):
            lines.append(f"- {claim['claim_id']}: {claim['text']} | evidence={claim['evidence_ids']}")
        if data.get("missing_information"):
            lines += ["", "MISSING_INFORMATION:"] + [f"- {x}" for x in data['missing_information']]
        lines += ["", "EVIDENCE:"]
        for ev in data.get("evidence", []):
            lines.append(
                f"[{ev['evidence_id']}] chunk_index={ev['chunk_index']} source_rank={ev['source_rank']} "
                f"pages={ev['pages']} type={ev['semantic_type']} reasons={ev['reasons']}\n{ev['content_text']}"
            )
        report = "\n".join(lines) + "\n"
        (args.output_dir/f"{name}.txt").write_text(report, encoding="utf-8")
        reports.append("="*100 + "\n" + report)
        print(f"  {data['status']} · {len(data.get('claims', []))} claims · {elapsed:.2f}s")

    combined = args.output_dir/"all_grounded_generation_results_stage9.txt"
    combined.write_text("\n\n".join(reports), encoding="utf-8")
    print(f"\nWrote {combined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
