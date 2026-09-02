#!/usr/bin/env python3
"""
Dense retrieval smoke-test runner for the RAG Workbench.

Runs five retrieval-behaviour tests against:
    POST /api/retrieval/dense

Outputs:
    retrieval_results/
        01_definition_pep.txt
        02_delayed_verification.txt
        03_non_face_to_face.txt
        04_verification_timeout.txt
        05_positive_designated_person_match.txt
        all_dense_retrieval_results.txt
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


# ============================================================
# Configuration
# ============================================================

BASE_URL = "http://localhost:8000"
DOCUMENT_ID = "485c4989-c300-45c8-ac06-79a59492bb5c"

EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DEVICE = "auto"
TOP_K = 5

OUTPUT_DIR = Path("retrieval_results")


# ============================================================
# Retrieval behaviours to test
# ============================================================

TESTS = [
    {
        "id": "01_definition_pep",
        "behavior": "Definition retrieval",
        "query": "What is a politically exposed person?",
        "purpose": (
            "Tests whether dense retrieval can find an exact regulatory definition "
            "and keep the complete definition context together."
        ),
    },
    {
        "id": "02_delayed_verification",
        "behavior": "Exact regulatory requirement",
        "query": "What are the requirements for delayed verification?",
        "purpose": (
            "Tests retrieval of a specific regulatory requirement and its related clauses."
        ),
    },
    {
        "id": "03_non_face_to_face",
        "behavior": "Long structured clause",
        "query": (
            "What measures are required when establishing "
            "a non-face-to-face business relationship?"
        ),
        "purpose": (
            "Tests retrieval of the long clause 8.1.23 and whether preserving the "
            "complete semantic clause helps retrieval."
        ),
    },
    {
        "id": "04_verification_timeout",
        "behavior": "Conceptual / paraphrased query",
        "query": (
            "What should an institution do when a customer "
            "cannot complete identity verification in time?"
        ),
        "purpose": (
            "Tests semantic retrieval when the query does not exactly copy the "
            "wording used in the document."
        ),
    },
    {
        "id": "05_positive_designated_person_match",
        "behavior": "Appendix / form retrieval",
        "query": (
            "What information must be reported when there "
            "is a positive match with a designated person?"
        ),
        "purpose": (
            "Tests retrieval of Appendix/form content and the group-header context "
            "corrections made in Stage 5."
        ),
    },
]


# ============================================================
# Helpers
# ============================================================

def dense_retrieve(query: str) -> dict[str, Any]:
    url = f"{BASE_URL}/api/retrieval/dense"

    payload = {
        "document_id": DOCUMENT_ID,
        "query": query,
        "top_k": TOP_K,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_device": EMBEDDING_DEVICE,
    }

    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )

    response.raise_for_status()
    return response.json()


def format_hit(hit: dict[str, Any]) -> str:
    rank = hit.get("rank")
    score = hit.get("score")
    distance = hit.get("distance")
    chunk_index = hit.get("chunk_index")
    chunk_id = hit.get("chunk_id")
    semantic_type = hit.get("semantic_type")
    pages = hit.get("pages", [])
    section_path = hit.get("section_path", [])
    source_element_ids = hit.get("source_element_ids", [])
    token_count = hit.get("token_count")
    text = hit.get("text", "")

    score_text = f"{score:.6f}" if isinstance(score, (int, float)) else str(score)
    distance_text = (
        f"{distance:.6f}" if isinstance(distance, (int, float)) else str(distance)
    )

    return f"""\
------------------------------------------------------------
RANK {rank}
------------------------------------------------------------
Chunk index       : {chunk_index}
Chunk ID          : {chunk_id}
Semantic type     : {semantic_type}
Score             : {score_text}
Cosine distance   : {distance_text}
Token count       : {token_count}
Pages             : {pages}
Section path      : {" > ".join(section_path)}
Source element IDs: {source_element_ids}

TEXT
------------------------------------------------------------
{text}
"""


def format_report(test: dict[str, str], result: dict[str, Any]) -> str:
    hits = result.get("hits", [])

    lines = [
        "=" * 78,
        f"RETRIEVAL BEHAVIOUR: {test['behavior']}",
        "=" * 78,
        f"Test ID          : {test['id']}",
        f"Query            : {test['query']}",
        f"Purpose          : {test['purpose']}",
        f"Document ID      : {result.get('document_id', DOCUMENT_ID)}",
        f"Embedding model  : {result.get('embedding_model', EMBEDDING_MODEL)}",
        f"Requested device : {result.get('requested_device', EMBEDDING_DEVICE)}",
        f"Resolved device  : {result.get('resolved_device')}",
        f"Top K            : {result.get('top_k', TOP_K)}",
        f"Embedded chunks  : {result.get('embedded_chunk_count')}",
        f"Total chunks     : {result.get('total_chunk_count')}",
        f"Retrieved hits   : {len(hits)}",
        "",
    ]

    for hit in hits:
        lines.append(format_hit(hit))

    lines.extend(
        [
            "",
            "=" * 78,
            "RAW JSON RESPONSE",
            "=" * 78,
            json.dumps(result, indent=2, ensure_ascii=False),
            "",
        ]
    )

    return "\n".join(lines)


# ============================================================
# Main
# ============================================================

def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now().astimezone()
    combined_reports: list[str] = []

    print("Dense retrieval smoke test")
    print(f"Backend : {BASE_URL}")
    print(f"Document: {DOCUMENT_ID}")
    print(f"Model   : {EMBEDDING_MODEL}")
    print(f"Device  : {EMBEDDING_DEVICE}")
    print(f"Top K   : {TOP_K}")
    print()

    for index, test in enumerate(TESTS, start=1):
        print(f"[{index}/{len(TESTS)}] {test['behavior']}")
        print(f"Query: {test['query']}")

        try:
            result = dense_retrieve(test["query"])
            report = format_report(test, result)

            output_path = OUTPUT_DIR / f"{test['id']}.txt"
            output_path.write_text(report, encoding="utf-8")
            combined_reports.append(report)

            hits = result.get("hits", [])
            if hits:
                top = hits[0]
                print(
                    f"  OK - rank 1: chunk={top.get('chunk_index')} "
                    f"score={top.get('score'):.4f}"
                )
            else:
                print("  WARNING - no hits returned")

            print(f"  Saved: {output_path}")

        except requests.RequestException as exc:
            error_report = f"""\
==============================================================================
RETRIEVAL BEHAVIOUR: {test['behavior']}
==============================================================================
Query: {test['query']}

ERROR
-----
{type(exc).__name__}: {exc}
"""
            output_path = OUTPUT_DIR / f"{test['id']}.txt"
            output_path.write_text(error_report, encoding="utf-8")
            combined_reports.append(error_report)

            print(f"  ERROR: {exc}")
            print(f"  Saved error report: {output_path}")

        print()

    finished_at = datetime.now().astimezone()

    header = f"""\
DENSE RETRIEVAL SMOKE-TEST REPORT
=================================

Started  : {started_at.isoformat()}
Finished : {finished_at.isoformat()}

Backend          : {BASE_URL}
Document ID      : {DOCUMENT_ID}
Embedding model  : {EMBEDDING_MODEL}
Embedding device : {EMBEDDING_DEVICE}
Top K            : {TOP_K}
Number of tests  : {len(TESTS)}

"""
    combined_path = OUTPUT_DIR / "all_dense_retrieval_results.txt"
    combined_path.write_text(
        header + "\n\n".join(combined_reports),
        encoding="utf-8",
    )

    print("=" * 78)
    print("DONE")
    print("=" * 78)
    print(f"Combined report: {combined_path}")
    print()
    print("Send me this file:")
    print(combined_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
