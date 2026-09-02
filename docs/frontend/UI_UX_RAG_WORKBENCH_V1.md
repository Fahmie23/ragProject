# RAG Workbench UI/UX V1 — UI-first shell

## Goal
Reframe the existing frontend from a document-parser-centric experience into an end-to-end RAG portfolio workbench without removing the advanced extraction/correction tools.

## New top-level information architecture

1. **Overview** — project narrative, benchmark document, and end-to-end pipeline status.
2. **Documents** — existing extraction / canonical structure / correction / chunking workbench.
3. **RAG Playground** — UI prototype for query, retrieval strategy, generated answer, sources, and retrieval trace.
4. **Evaluation** — UI prototype for benchmark dataset, retrieval metrics, answer metrics, and strategy comparison.

## Current implementation status

This phase is intentionally UI-first.

- Existing Documents functionality is preserved.
- Overview uses benchmark summary content.
- RAG Playground uses local mock data and local interactions only.
- Evaluation uses local mock metrics / benchmark rows only.
- Retrieval, embedding, indexing, reranking, answer generation, and evaluation backend calls will be wired in later phases.

## UX principle

The parser is now an expert **Document Intelligence** module. The main product identity is **RAG Workbench**, so a reviewer sees the complete RAG architecture before diving into extraction internals.
