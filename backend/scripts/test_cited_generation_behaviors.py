#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

import requests

RATE_LIMIT_RE = re.compile(r"Please try again in\s+([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)
EXPECTED_CITATION_VERSION = "deterministic_citations_v1_2"

QUESTIONS = [
    ("01_definition_pep", "What is a politically exposed person?", "answerable"),
    ("02_delayed_verification", "What are the requirements for delayed verification?", "answerable"),
    ("03_non_face_to_face", "What measures are required when establishing a non-face-to-face business relationship?", "answerable"),
    ("04_verification_timeout", "What should an institution do when a customer cannot complete identity verification in time?", "answerable"),
    ("05_positive_designated_person_match", "What information must be reported when there is a positive match with a designated person?", "answerable"),
    ("06_out_of_scope_abstention", "What is the current price of Bitcoin?", "should_abstain"),
]


def _provider_status_code(response: requests.Response) -> int | None:
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


def _validate_stage10_payload(data: dict, expectation: str) -> list[str]:
    errors: list[str] = []
    evidence = {item.get("evidence_id"): item for item in data.get("evidence", []) if item.get("evidence_id")}
    citations = {item.get("citation_id"): item for item in data.get("citations", []) if item.get("citation_id")}

    if data.get("citation_version") != EXPECTED_CITATION_VERSION:
        errors.append(f"citation_version={data.get('citation_version')!r}")
    validation = data.get("citation_validation") or {}
    if validation.get("status") != "valid":
        errors.append(f"citation_validation.status={validation.get('status')!r}")
    if validation.get("errors"):
        errors.append(f"citation_validation.errors={validation.get('errors')!r}")
    if validation.get("citation_count") != len(citations):
        errors.append("citation_validation.citation_count does not match citations")
    if validation.get("valid_citation_count") != len(citations):
        errors.append("citation_validation.valid_citation_count does not match citations")

    if expectation == "should_abstain":
        if data.get("status") != "insufficient_evidence":
            errors.append(f"expected insufficient_evidence, got {data.get('status')!r}")
        if data.get("claims"):
            errors.append("abstention returned claims")
        if citations:
            errors.append("abstention returned citations")
        if data.get("used_evidence_ids"):
            errors.append("abstention returned used_evidence_ids")
        if data.get("cited_answer") != data.get("answer"):
            errors.append("abstention cited_answer must equal the abstention answer")
        return errors

    if data.get("status") != "answered":
        errors.append(f"expected answered, got {data.get('status')!r}")
        return errors
    claims = data.get("claims") or []
    if not claims:
        errors.append("answered response has no claims")
    if not citations:
        errors.append("answered response has no citations")

    used_ids: list[str] = []
    for claim in claims:
        claim_id = claim.get("claim_id")
        evidence_ids = claim.get("evidence_ids") or []
        citation_ids = claim.get("citation_ids") or []
        if not evidence_ids:
            errors.append(f"{claim_id} has no evidence_ids")
        if not citation_ids:
            errors.append(f"{claim_id} has no citation_ids")
        mapped_evidence_ids: list[str] = []
        for citation_id in citation_ids:
            citation = citations.get(citation_id)
            if citation is None:
                errors.append(f"{claim_id} references missing citation {citation_id}")
                continue
            mapped_evidence_ids.append(citation.get("evidence_id"))
        if mapped_evidence_ids != list(dict.fromkeys(evidence_ids)):
            errors.append(f"{claim_id} citation/evidence mapping is not deterministic: {mapped_evidence_ids} != {evidence_ids}")
        for evidence_id in evidence_ids:
            if evidence_id not in used_ids:
                used_ids.append(evidence_id)

    if used_ids != data.get("used_evidence_ids", []):
        errors.append(f"used_evidence_ids disagree with claims: {used_ids} != {data.get('used_evidence_ids')}")

    cited_answer = data.get("cited_answer") or ""
    for citation in citations.values():
        evidence_id = citation.get("evidence_id")
        ev = evidence.get(evidence_id)
        if ev is None:
            errors.append(f"{citation.get('citation_id')} maps to unknown evidence {evidence_id}")
            continue
        if citation.get("validation_status") != "valid":
            errors.append(f"{citation.get('citation_id')} is not valid")
        if citation.get("chunk_id") != ev.get("chunk_id") or citation.get("chunk_index") != ev.get("chunk_index"):
            errors.append(f"{citation.get('citation_id')} chunk provenance differs from {evidence_id}")
        if citation.get("pages") != ev.get("pages"):
            errors.append(f"{citation.get('citation_id')} pages differ from {evidence_id}")
        if citation.get("source_element_ids") != ev.get("source_element_ids"):
            errors.append(f"{citation.get('citation_id')} source elements differ from {evidence_id}")
        if not citation.get("display") or "PDF p" not in citation.get("display", ""):
            errors.append(f"{citation.get('citation_id')} has no human PDF locator")
        if not citation.get("source_filename"):
            errors.append(f"{citation.get('citation_id')} has no source filename")
        if citation.get("marker") not in cited_answer:
            errors.append(f"{citation.get('citation_id')} marker is missing from cited_answer")
        locators = citation.get("locators") or []
        if not locators:
            errors.append(f"{citation.get('citation_id')} has no locators")
        for locator in locators:
            if not set(locator.get("pages") or []).issubset(set(citation.get("pages") or [])):
                errors.append(f"{citation.get('citation_id')} locator escapes citation pages")
            if not set(locator.get("source_element_ids") or []).issubset(set(citation.get("source_element_ids") or [])):
                errors.append(f"{citation.get('citation_id')} locator escapes citation source elements")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 10 cited-generation smoke test")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--document-id", default="485c4989-c300-45c8-ac06-79a59492bb5c")
    ap.add_argument("--output-dir", type=Path, default=Path("cited_generation_results_stage10"))
    ap.add_argument("--delay-seconds", type=float, default=30.0)
    ap.add_argument("--max-rate-limit-retries", type=int, default=2)
    ap.add_argument("--rate-limit-buffer-seconds", type=float, default=2.0)
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

    reports: list[str] = []
    total_failures = 0
    for index, (name, question, expectation) in enumerate(QUESTIONS, start=1):
        if index > 1 and args.delay_seconds > 0:
            print(f"Waiting {args.delay_seconds:.1f}s before the next generation test ...", flush=True)
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
            total_failures += 1
            report = (
                f"QUESTION: {question}\nEXPECTATION: {expectation}\nRATE_LIMIT_RETRIES: {rate_limit_retries}\n"
                f"HTTP: {response.status_code}\nERROR:\n{response.text}\n"
            )
            (args.output_dir / f"{name}.txt").write_text(report, encoding="utf-8")
            reports.append("=" * 100 + "\n" + report)
            print(f"  FAIL HTTP {response.status_code}")
            continue

        data = response.json()
        validation_errors = _validate_stage10_payload(data, expectation)
        if validation_errors:
            total_failures += 1

        lines = [
            f"QUESTION: {question}",
            f"EXPECTATION: {expectation}",
            f"STATUS: {data.get('status')}",
            f"SMOKE_STATUS: {'FAIL' if validation_errors else 'PASS'}",
            f"ELAPSED_SECONDS: {elapsed:.2f}",
            f"RATE_LIMIT_RETRIES: {rate_limit_retries}",
            f"PROVIDER: {data.get('generation_provider')}",
            f"MODEL: {data.get('generation_model')}",
            f"PROMPT_VERSION: {data.get('prompt_version')}",
            f"CITATION_VERSION: {data.get('citation_version')}",
            f"RETRIEVAL_PROFILE: {data.get('retrieval_profile')}",
            f"CONTEXT_CHUNKS: {data.get('context_chunk_count')}",
            f"EXPANDED_CHUNKS: {data.get('expanded_chunk_count')}",
            f"USED_EVIDENCE_IDS: {data.get('used_evidence_ids')}",
            f"CITATION_VALIDATION: {data.get('citation_validation')}",
            "",
            "ANSWER:",
            data.get("answer", ""),
            "",
            "CITED_ANSWER:",
            data.get("cited_answer", ""),
            "",
            "CLAIMS:",
        ]
        for claim in data.get("claims", []):
            lines.append(
                f"- {claim.get('claim_id')}: {claim.get('text')} | evidence={claim.get('evidence_ids')} "
                f"| citations={claim.get('citation_ids')}"
            )
        lines += ["", "CITATIONS:"]
        for citation in data.get("citations", []):
            lines.append(
                f"- {citation.get('citation_id')} {citation.get('marker')} evidence={citation.get('evidence_id')} "
                f"chunk={citation.get('chunk_index')} pages={citation.get('pages')} :: {citation.get('display')}"
            )
        if data.get("missing_information"):
            lines += ["", "MISSING_INFORMATION:"] + [f"- {item}" for item in data["missing_information"]]
        if validation_errors:
            lines += ["", "SMOKE_ERRORS:"] + [f"- {item}" for item in validation_errors]
        lines += ["", "EVIDENCE:"]
        for ev in data.get("evidence", []):
            lines.append(
                f"[{ev.get('evidence_id')}] chunk_index={ev.get('chunk_index')} source_rank={ev.get('source_rank')} "
                f"pages={ev.get('pages')} type={ev.get('semantic_type')} reasons={ev.get('reasons')}\n{ev.get('content_text')}"
            )
        report = "\n".join(lines) + "\n"
        (args.output_dir / f"{name}.txt").write_text(report, encoding="utf-8")
        reports.append("=" * 100 + "\n" + report)
        print(f"  {'FAIL' if validation_errors else 'PASS'} · {data.get('status')} · {len(data.get('citations', []))} citations · {elapsed:.2f}s")

    combined = args.output_dir / "all_cited_generation_results_stage10.txt"
    combined.write_text("\n\n".join(reports), encoding="utf-8")
    print(f"\nWrote {combined}")
    if total_failures:
        print(f"Stage 10 smoke failed: {total_failures}/{len(QUESTIONS)} cases failed.")
        return 1
    print(f"Stage 10 smoke passed: {len(QUESTIONS)}/{len(QUESTIONS)} cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
