# Grounded Answer Generation

## Position in the pipeline

Generation is downstream of the frozen retrieval/context path:

```text
question
 ↓
Retrieval v1
 ↓
Top-5 reranked seeds
 ↓
Stage 8.2 bounded context
 ↓
request-local evidence IDs (E1, E2, ...)
 ↓
grounded generation
```

Stage 9 does not change dense retrieval, PostgreSQL FTS, RRF, reranking, semantic chunks or context assembly.

## Grounding contract

The model receives bounded evidence identified by request-local IDs. Its structured output associates generated claims with those evidence IDs. Unknown evidence IDs are rejected by backend validation.

The model is instructed to answer from supplied evidence rather than treating outside knowledge as source material.

## Abstention

If the evidence is insufficient to answer the question, the system can return an explicit insufficient-evidence/abstention status rather than forcing an answer.

This is important for out-of-scope questions and for cases where retrieval/context misses required evidence.

## Prompt and evidence safety

The prompt distinguishes system instructions, the user question and retrieved document evidence. Retrieved text is treated as evidence content, not trusted instructions that may override the grounding contract.

## No silent truncation

Generation has a maximum-context guard. If the evidence/prompt exceeds that guard, the endpoint fails rather than silently cutting evidence and producing a misleading partial answer.

The frozen top-5 + bounded-context evidence budget is intended to remain below that guard for the benchmark workload.

## API

```text
POST /api/generation/answer
GET  /api/system/generation
```

The runtime-status endpoint reports provider/model configuration without exposing secret API keys.

## Evaluation boundary

Retrieval held-out questions were not reused as unseen answer-generation evaluation. Stage 11 uses a separately authored answer/citation benchmark so downstream generation quality can be measured independently of the retrieval held-out set.
