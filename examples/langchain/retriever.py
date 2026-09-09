"""LangChain retriever adapter for the existing RAG Document Studio API.

This module deliberately reuses the production retrieval endpoint instead of
reimplementing embeddings, lexical search, fusion, or reranking in LangChain.
That keeps the project's evaluated retrieval behavior as the source of truth
while exposing it through LangChain's standard ``BaseRetriever`` interface.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field


RetrievalEndpoint = Literal[
    "hybrid",
    "hybrid-rerank",
    "hybrid-rerank-context",
]


class RagDocumentStudioRetriever(BaseRetriever):
    """Wrap RAG Document Studio retrieval as a LangChain retriever.

    The default endpoint is the production retrieval profile used before
    grounded generation: hybrid candidate generation, reranking, and bounded
    structural context expansion.
    """

    api_base_url: str = "http://localhost:8000"
    document_id: str
    endpoint: RetrievalEndpoint = "hybrid-rerank-context"
    top_k: int = Field(default=5, ge=1, le=50)
    candidate_k: int = Field(default=20, ge=1, le=100)
    timeout_seconds: float = Field(default=180.0, gt=0.0)

    # These are only sent to the context endpoint. They mirror the project's
    # bounded structural-context defaults rather than introducing new behavior.
    context_max_forward_neighbors_per_seed: int = Field(default=1, ge=0, le=5)
    context_max_backward_neighbors_per_seed: int = Field(default=1, ge=0, le=5)
    context_max_page_gap: int = Field(default=1, ge=0, le=10)
    context_max_chunks: int = Field(default=30, ge=1, le=100)

    def _request_payload(self, query: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "document_id": self.document_id,
            "query": query,
            "top_k": self.top_k,
            "candidate_k": max(self.candidate_k, self.top_k),
        }
        if self.endpoint == "hybrid-rerank-context":
            payload.update(
                {
                    "context_max_forward_neighbors_per_seed": self.context_max_forward_neighbors_per_seed,
                    "context_max_backward_neighbors_per_seed": self.context_max_backward_neighbors_per_seed,
                    "context_max_page_gap": self.context_max_page_gap,
                    "context_max_chunks": self.context_max_chunks,
                }
            )
        return payload

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            body = response.text.strip()
        if isinstance(body, dict) and "detail" in body:
            body = body["detail"]
        return f"RAG Document Studio retrieval failed ({response.status_code}): {body}"

    @staticmethod
    def _document_from_row(row: dict[str, Any], *, fallback_rank: int) -> Document:
        text = str(row.get("content_text") or row.get("text") or "").strip()
        if not text:
            raise ValueError("Retrieval returned a row without content text.")

        metadata = {
            "chunk_id": row.get("chunk_id"),
            "chunk_index": row.get("chunk_index"),
            "semantic_type": row.get("semantic_type"),
            "rank": row.get("rank", row.get("source_rank", fallback_rank)),
            "pages": list(row.get("pages") or []),
            "section_path": list(row.get("section_path") or []),
            "source_element_ids": list(row.get("source_element_ids") or []),
            "visual_refs": list(row.get("visual_refs") or []),
            "reranker_score": row.get("reranker_score"),
            "fusion_score": row.get("fusion_score"),
            "context_role": row.get("context_role"),
            "context_reasons": list(row.get("reasons") or row.get("context_reasons") or []),
        }
        # Remove only null scalar fields; keep empty lists because their absence
        # is meaningful provenance information to callers.
        metadata = {key: value for key, value in metadata.items() if value is not None}
        return Document(page_content=text, metadata=metadata)

    def _get_relevant_documents(self, query: str) -> list[Document]:
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        url = f"{self.api_base_url.rstrip('/')}/api/retrieval/{self.endpoint}"
        try:
            response = httpx.post(
                url,
                json=self._request_payload(cleaned_query),
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not reach RAG Document Studio at {url}: {exc}") from exc

        if response.is_error:
            raise RuntimeError(self._error_message(response))

        payload = response.json()
        rows = (
            payload.get("context_chunks", [])
            if self.endpoint == "hybrid-rerank-context"
            else payload.get("hits", [])
        )
        if not isinstance(rows, list):
            raise RuntimeError("Retrieval API returned an unexpected response shape.")

        documents: list[Document] = []
        seen_chunk_ids: set[str] = set()
        for index, raw_row in enumerate(rows, start=1):
            if not isinstance(raw_row, dict):
                continue
            chunk_id = str(raw_row.get("chunk_id") or "")
            if chunk_id and chunk_id in seen_chunk_ids:
                continue
            if chunk_id:
                seen_chunk_ids.add(chunk_id)
            documents.append(self._document_from_row(raw_row, fallback_rank=index))
        return documents
