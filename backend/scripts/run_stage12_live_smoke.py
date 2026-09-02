#!/usr/bin/env python3
"""Stage 12 live local-system smoke test.

Checks the running FastAPI service, PostgreSQL/pgvector/schema readiness, frozen
source-document artifacts, and one real hybrid+reranker+context retrieval request.
Generation is optional because Stage 11 already consumed the live held-out run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_heldout_v1.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _get(session: requests.Session, url: str, timeout: float) -> dict[str, Any]:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Stage 12 live local-system smoke checks")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--include-generation", action="store_true", help="Make one live generation-provider call")
    args = ap.parse_args()

    dataset = _load(args.dataset)
    document_id = str((dataset.get("document") or {}).get("document_id") or "")
    if not document_id:
        print("FAIL: benchmark document_id is missing")
        return 2

    base = args.base_url.rstrip("/")
    session = requests.Session()
    errors: list[str] = []

    try:
        health = _get(session, f"{base}/health", args.timeout)
        if health.get("status") != "ok":
            errors.append(f"/health status is {health.get('status')!r}, expected 'ok'")

        db = _get(session, f"{base}/api/system/database", args.timeout)
        if db.get("reachable") is not True:
            errors.append("PostgreSQL is not reachable")
        if db.get("pgvector_enabled") is not True:
            errors.append("pgvector extension is not enabled")
        if db.get("schema_ready") is not True:
            errors.append("database schema is not ready")

        generation_status = _get(session, f"{base}/api/system/generation", args.timeout)
        if generation_status.get("retrieval_profile") != "retrieval_v1_stage8_2_top5":
            errors.append("generation endpoint does not report frozen Retrieval-v1 profile")
        if generation_status.get("citation_version") != "deterministic_citations_v1_2":
            errors.append("generation endpoint does not report frozen citation version")

        document = _get(session, f"{base}/api/documents/{document_id}", args.timeout)
        if document.get("document_id") != document_id:
            errors.append("benchmark source document metadata mismatch")
        if document.get("sha256") != (dataset.get("document") or {}).get("source_sha256"):
            errors.append("benchmark source document SHA-256 mismatch")

        chunks = _get(session, f"{base}/api/documents/{document_id}/chunks", args.timeout)
        if not chunks.get("chunks"):
            errors.append("frozen Stage 5 chunk artifact is empty")

        retrieval_response = session.post(
            f"{base}/api/retrieval/hybrid-rerank-context",
            json={
                "document_id": document_id,
                "query": "What AML/CFT/CPF obligations apply to reporting institutions?",
                "top_k": 5,
                "candidate_k": 20,
                "rrf_k": 60,
                "dense_weight": 1.0,
                "lexical_weight": 1.0,
                "context_max_forward_neighbors_per_seed": 2,
                "context_max_backward_neighbors_per_seed": 1,
                "context_max_page_gap": 1,
                "context_max_chunks": 30,
            },
            timeout=args.timeout,
        )
        retrieval_response.raise_for_status()
        retrieval = retrieval_response.json()
        if retrieval.get("top_k") != 5 or retrieval.get("candidate_k") != 20:
            errors.append("live retrieval did not use requested frozen candidate/top-k values")
        if retrieval.get("context_strategy") != "structural_one_hop_v1":
            errors.append("live retrieval context strategy mismatch")
        if not retrieval.get("hits"):
            errors.append("live retrieval returned no reranked hits")
        if not retrieval.get("context_chunks"):
            errors.append("live retrieval returned no context chunks")

        if args.include_generation:
            generation_response = session.post(
                f"{base}/api/generation/answer",
                json={"document_id": document_id, "question": "Who must comply with these Guidelines?"},
                timeout=args.timeout,
            )
            generation_response.raise_for_status()
            generated = generation_response.json()
            if generated.get("retrieval_profile") != "retrieval_v1_stage8_2_top5":
                errors.append("live generation retrieval profile mismatch")
            if generated.get("citation_version") != "deterministic_citations_v1_2":
                errors.append("live generation citation version mismatch")
            if generated.get("status") == "answered" and (generated.get("citation_validation") or {}).get("status") != "valid":
                errors.append("live answered generation did not return valid deterministic citations")

    except requests.RequestException as exc:
        errors.append(f"HTTP/system smoke request failed: {exc}")

    if errors:
        print(f"FAIL: {len(errors)} Stage 12 live-system smoke error(s)")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: Stage 12 live local-system smoke")
    print(f"Document: {document_id}")
    print("PostgreSQL/pgvector/schema: ready")
    print("Frozen Stage 5 document artifact: present")
    print("Hybrid + reranker + structural context: PASS")
    print(f"Live generation call: {'PASS' if args.include_generation else 'SKIPPED (Stage 11 already verified provider path)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
