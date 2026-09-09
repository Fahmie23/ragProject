"""Command-line demonstration of the LangChain adapter.

Example:
    python demo.py \
      --document-id 485c4989-c300-45c8-ac06-79a59492bb5c \
      --question "Explain the BbRA and RbRA process."
"""

from __future__ import annotations

import argparse
import os

from langchain_groq import ChatGroq

from chain import build_rag_chain
from retriever import RagDocumentStudioRetriever


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAG Document Studio through LangChain LCEL.")
    parser.add_argument("--document-id", required=True, help="Existing RAG Document Studio document UUID.")
    parser.add_argument("--question", required=True, help="Question to ask the document.")
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("RAG_STUDIO_API_URL", "http://localhost:8000"),
        help="RAG Document Studio backend URL (default: http://localhost:8000).",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Final reranked seed count.")
    parser.add_argument("--candidate-k", type=int, default=20, help="Dense/lexical candidate depth.")
    parser.add_argument(
        "--model",
        default=os.getenv(
            "LANGCHAIN_GROQ_MODEL",
            os.getenv("GENERATION_MODEL", "openai/gpt-oss-120b"),
        ),
        help="Groq-hosted chat model used by the LangChain example.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY is not exported in this shell.")

    retriever = RagDocumentStudioRetriever(
        api_base_url=args.api_base_url,
        document_id=args.document_id,
        top_k=args.top_k,
        candidate_k=max(args.candidate_k, args.top_k),
    )
    llm = ChatGroq(
        model=args.model,
        temperature=0,
        max_retries=2,
    )
    chain = build_rag_chain(retriever=retriever, llm=llm)
    result = chain.invoke(args.question)

    print("\n=== LangChain answer ===\n")
    print(result["answer"])
    print("\n=== Retrieved sources ===\n")
    for index, document in enumerate(result["documents"], start=1):
        pages = document.metadata.get("pages") or []
        section_path = document.metadata.get("section_path") or []
        print(
            f"[LC{index}] chunk={document.metadata.get('chunk_id')} "
            f"pages={pages} section={' > '.join(str(item) for item in section_path)}"
        )
        if document.metadata.get("visual_refs"):
            print(f"      visual_refs={len(document.metadata['visual_refs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
