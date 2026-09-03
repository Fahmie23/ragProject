# Stage 14.1 — RAG Playground Contract & Evaluation Read API

Status: candidate; do not freeze until local verification passes.

## Purpose

Stage 14.1 defines the source-of-truth boundary between the frozen RAG backend and the future React playground. It does not redesign retrieval, generation, citations, or the held-out benchmark.

## Rules

1. React displays backend-owned facts; it does not calculate RRF, reranker ordering, citation validity, or evaluation metrics.
2. Live arbitrary questions continue to use `POST /api/generation/answer` and may call the configured generation provider.
3. Evaluation routes are read-only views over frozen Stage 11 artifacts and make zero external API calls.
4. Evaluation metrics are explicitly scoped to `answer_citation_eval_heldout_v1`; they are not universal RAG performance guarantees.
5. Every summary metric exposes a definition/formula, artifact source, scope, and numerator/denominator where mathematically applicable.
6. Frozen held-out answers cannot be regenerated or modified from the Stage 14 evaluation API.
7. Full dense → lexical → RRF → reranker tracing is deferred to Stage 14.3 because the production generation response does not currently expose that trace. Stage 14.1 must not fabricate it or execute retrieval twice.

## Endpoints

- `GET /api/playground/contract`
- `GET /api/evaluation/answer-citation/summary`
- `GET /api/evaluation/answer-citation/questions`
- `GET /api/evaluation/answer-citation/questions/{question_id}`

The question list supports `category`, `difficulty`, and `failure_only` filters.

## Evaluation provenance

The read API combines existing frozen artifacts:

- held-out benchmark dataset and gold requirements;
- deterministic Stage 11 aggregate and per-question results;
- frozen human semantic calibration;
- immutable held-out response snapshots;
- final Stage 11 evaluation manifest.

No scorer or LLM is invoked merely by opening the Evaluation Explorer.

## Stage 14 sequence

- 14.1 Contract + read-only evaluation API
- 14.2 Core question/answer playground
- 14.3 Retrieval + context inspector
- 14.4 Citation/provenance explorer
- 14.5 Evaluation explorer UI + polish
