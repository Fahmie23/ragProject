#!/usr/bin/env python3
"""Stage 8 Hybrid + Reranker smoke-test runner.

Uses the exact same five questions as the Dense and Hybrid baselines.

Outputs:
    reranked_retrieval_results_stage8/
        01_definition_pep.txt
        02_delayed_verification.txt
        03_non_face_to_face.txt
        04_verification_timeout.txt
        05_positive_designated_person_match.txt
        all_reranked_retrieval_results_stage8.txt
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


BASE_URL = "http://localhost:8000"
DOCUMENT_ID = "485c4989-c300-45c8-ac06-79a59492bb5c"
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DEVICE = "auto"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RERANKER_DEVICE = "auto"
TOP_K = 5
CANDIDATE_K = 20
RRF_K = 60
DENSE_WEIGHT = 1.0
LEXICAL_WEIGHT = 1.0
OUTPUT_DIR = Path("reranked_retrieval_results_stage8")


TESTS = [
    {
        "id": "01_definition_pep",
        "behavior": "Definition retrieval",
        "query": "What is a politically exposed person?",
        "purpose": "Tests whether reranking preserves the exact PEP definition at rank 1.",
    },
    {
        "id": "02_delayed_verification",
        "behavior": "Exact regulatory requirement",
        "query": "What are the requirements for delayed verification?",
        "purpose": "Tests whether reranking preserves the strong delayed-verification result.",
    },
    {
        "id": "03_non_face_to_face",
        "behavior": "Long structured clause",
        "query": "What measures are required when establishing a non-face-to-face business relationship?",
        "purpose": "Tests whether reranking preserves intact clause 8.1.23 as the best evidence.",
    },
    {
        "id": "04_verification_timeout",
        "behavior": "Conceptual / paraphrased query",
        "query": "What should an institution do when a customer cannot complete identity verification in time?",
        "purpose": "Tests whether reranking preserves Stage 7.1's improvement for the paraphrased timeout query.",
    },
    {
        "id": "05_positive_designated_person_match",
        "behavior": "Appendix / form retrieval",
        "query": "What information must be reported when there is a positive match with a designated person?",
        "purpose": "Tests whether reranking recovers the Appendix I answer-bearing reporting table from the candidate union.",
    },
]


def reranked_retrieve(query: str) -> dict[str, Any]:
    response = requests.post(
        f"{BASE_URL}/api/retrieval/hybrid-rerank",
        headers={"Content-Type": "application/json"},
        json={
            "document_id": DOCUMENT_ID,
            "query": query,
            "top_k": TOP_K,
            "candidate_k": CANDIDATE_K,
            "rrf_k": RRF_K,
            "dense_weight": DENSE_WEIGHT,
            "lexical_weight": LEXICAL_WEIGHT,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_device": EMBEDDING_DEVICE,
            "reranker_model": RERANKER_MODEL,
            "reranker_device": RERANKER_DEVICE,
        },
        timeout=900,
    )
    response.raise_for_status()
    return response.json()


def _number(value: Any, digits: int = 6) -> str:
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "—"


def format_hit(hit: dict[str, Any]) -> str:
    return f"""\
------------------------------------------------------------
RANK {hit.get('rank')}
------------------------------------------------------------
Chunk index          : {hit.get('chunk_index')}
Chunk ID             : {hit.get('chunk_id')}
Semantic type        : {hit.get('semantic_type')}
Reranker score       : {_number(hit.get('reranker_score'))}
Hybrid candidate rank: {hit.get('hybrid_candidate_rank')}
Fusion score         : {_number(hit.get('fusion_score'))}
Dense rank           : {hit.get('dense_rank') or '—'}
Dense score          : {_number(hit.get('dense_score'))}
Dense distance       : {_number(hit.get('dense_distance'))}
Dense RRF            : {_number(hit.get('dense_rrf_score'))}
Lexical rank         : {hit.get('lexical_rank') or '—'}
Lexical score        : {_number(hit.get('lexical_score'))}
Lexical terms hit    : {hit.get('lexical_matched_term_count', 0)}
Lexical coverage     : {_number(hit.get('lexical_term_coverage'), 4)}
Lexical RRF          : {_number(hit.get('lexical_rrf_score'))}
Token count          : {hit.get('token_count')}
Pages                : {hit.get('pages', [])}
Section path         : {' > '.join(hit.get('section_path', []))}
Source element IDs   : {hit.get('source_element_ids', [])}

TEXT
------------------------------------------------------------
{hit.get('text', '')}
"""


def format_report(test: dict[str, str], result: dict[str, Any]) -> str:
    hits = result.get("hits", [])
    lines = [
        "=" * 78,
        f"RETRIEVAL BEHAVIOUR: {test['behavior']}",
        "=" * 78,
        f"Test ID                    : {test['id']}",
        f"Query                      : {test['query']}",
        f"Purpose                    : {test['purpose']}",
        f"Document ID                : {result.get('document_id', DOCUMENT_ID)}",
        f"Embedding model            : {result.get('embedding_model', EMBEDDING_MODEL)}",
        f"Embedding requested device : {result.get('embedding_requested_device')}",
        f"Embedding resolved device  : {result.get('embedding_resolved_device')}",
        f"Reranker model             : {result.get('reranker_model', RERANKER_MODEL)}",
        f"Reranker requested device  : {result.get('reranker_requested_device')}",
        f"Reranker resolved device   : {result.get('reranker_resolved_device')}",
        f"Reranker batch size        : {result.get('reranker_batch_size')}",
        f"Reranker max length        : {result.get('reranker_max_length')}",
        f"Top K                      : {result.get('top_k', TOP_K)}",
        f"Candidate K per retriever  : {result.get('candidate_k', CANDIDATE_K)}",
        f"Candidate union count      : {result.get('candidate_union_count')}",
        f"Candidate strategy         : {result.get('candidate_strategy')}",
        f"Ranking method             : {result.get('ranking_method')}",
        f"RRF K                      : {result.get('rrf_k')}",
        f"Dense weight               : {result.get('dense_weight')}",
        f"Lexical weight             : {result.get('lexical_weight')}",
        f"Lexical ranking            : {result.get('lexical_ranking_method')}",
        f"Lexical query mode         : {result.get('lexical_query_mode')}",
        f"Lexical terms              : {result.get('lexical_terms')}",
        f"Lexical tsquery            : {result.get('lexical_tsquery')}",
        f"Embedded chunks            : {result.get('embedded_chunk_count')}",
        f"Total chunks               : {result.get('total_chunk_count')}",
        f"Retrieved hits             : {len(hits)}",
        "",
    ]
    for hit in hits:
        lines.append(format_hit(hit))
    lines.extend([
        "",
        "=" * 78,
        "RAW JSON RESPONSE",
        "=" * 78,
        json.dumps(result, indent=2, ensure_ascii=False),
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().astimezone()
    combined_reports: list[str] = []

    print("Stage 8 Hybrid + Reranker smoke test")
    print(f"Backend       : {BASE_URL}")
    print(f"Document      : {DOCUMENT_ID}")
    print(f"Embedding     : {EMBEDDING_MODEL} ({EMBEDDING_DEVICE})")
    print(f"Reranker      : {RERANKER_MODEL} ({RERANKER_DEVICE})")
    print(f"Top K         : {TOP_K}")
    print(f"Candidate K   : {CANDIDATE_K} per retriever")
    print()

    for index, test in enumerate(TESTS, start=1):
        print(f"[{index}/{len(TESTS)}] {test['behavior']}")
        print(f"Query: {test['query']}")
        try:
            result = reranked_retrieve(test["query"])
            report = format_report(test, result)
            output_path = OUTPUT_DIR / f"{test['id']}.txt"
            output_path.write_text(report, encoding="utf-8")
            combined_reports.append(report)
            hits = result.get("hits", [])
            if hits:
                top = hits[0]
                print(
                    f"  OK - rank 1: chunk={top.get('chunk_index')} "
                    f"reranker={_number(top.get('reranker_score'))} "
                    f"dense_rank={top.get('dense_rank') or '—'} "
                    f"lexical_rank={top.get('lexical_rank') or '—'} "
                    f"hybrid_candidate_rank={top.get('hybrid_candidate_rank')}"
                )
            else:
                print("  WARNING - no hits returned")
            print(f"  Saved: {output_path}")
        except requests.RequestException as exc:
            response_text = ""
            if getattr(exc, "response", None) is not None:
                response_text = f"\n\nRESPONSE\n--------\n{exc.response.text}"
            error_report = f"""\
==============================================================================
RETRIEVAL BEHAVIOUR: {test['behavior']}
==============================================================================
Query: {test['query']}

ERROR
-----
{type(exc).__name__}: {exc}{response_text}
"""
            output_path = OUTPUT_DIR / f"{test['id']}.txt"
            output_path.write_text(error_report, encoding="utf-8")
            combined_reports.append(error_report)
            print(f"  ERROR: {exc}")
            print(f"  Saved error report: {output_path}")
        print()

    finished_at = datetime.now().astimezone()
    header = f"""\
STAGE 8 HYBRID + RERANKER SMOKE-TEST REPORT
============================================

Started  : {started_at.isoformat()}
Finished : {finished_at.isoformat()}

Backend           : {BASE_URL}
Document ID       : {DOCUMENT_ID}
Embedding model   : {EMBEDDING_MODEL}
Embedding device  : {EMBEDDING_DEVICE}
Reranker model    : {RERANKER_MODEL}
Reranker device   : {RERANKER_DEVICE}
Top K             : {TOP_K}
Candidate K       : {CANDIDATE_K} per retriever
RRF K             : {RRF_K}
Dense weight      : {DENSE_WEIGHT}
Lexical weight    : {LEXICAL_WEIGHT}
Number of tests   : {len(TESTS)}

"""
    combined_path = OUTPUT_DIR / "all_reranked_retrieval_results_stage8.txt"
    combined_path.write_text(header + "\n\n".join(combined_reports), encoding="utf-8")

    print("=" * 78)
    print("DONE")
    print("=" * 78)
    print(f"Combined report: {combined_path}")
    print("Send me this file:")
    print(combined_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
