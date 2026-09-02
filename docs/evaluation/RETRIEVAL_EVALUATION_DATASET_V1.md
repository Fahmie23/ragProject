# Retrieval Evaluation Dataset Specification v1

## Purpose

This dataset evaluates **retrieval quality only** for the SC AML/CFT/CPF regulatory-document RAG benchmark. It is designed to compare:

1. Dense retrieval — BGE-M3 + pgvector cosine similarity
2. Hybrid retrieval — BGE-M3 dense + PostgreSQL FTS + RRF
3. Hybrid + reranker — Dense/lexical candidate union + BGE reranker

Answer-generation quality is deliberately excluded from this dataset.

## Source lock

- Document ID: `485c4989-c300-45c8-ac06-79a59492bb5c`
- PDF SHA-256: `e1d138edd3c55b3fa3dd36b3236876a1a8dd634c4d972cec74157e6bf816bc15`
- PDF pages: 109
- Stage 5 strategy: `semantic-v2.1`
- Stage 5 chunks: 284
- Formal questions: 40
- Development split: 25
- Held-out split: 15

The source hash is intentionally locked. If the PDF or Stage 5 chunk corpus changes, the gold chunk labels must be revalidated before metrics are reported.

## Why the old five smoke questions are separate

The five questions previously used to diagnose Dense, Hybrid and reranker behavior influenced system development. They are retained in `retrieval_regression_smoke_v1.json` for regression testing, but are **not part of the formal 40-question evaluation set**.

Do not use the smoke set as the sole basis for final performance claims.

## Formal split policy

### Development — 25 questions

May be used to:
- inspect retrieval errors;
- debug candidate generation;
- tune retrieval configuration;
- understand category-specific failures.

### Held-out — 15 questions

Use only for final comparison after retrieval settings are frozen.

Do not modify:
- query formulation;
- candidate K;
- RRF parameters;
- retrieval weights;
- reranker configuration;
- chunking;

based on held-out results and then report the same held-out run as unbiased evaluation.

## Categories

| Category | Count |
|---|---:|
| Definition | 5 |
| Direct requirement | 6 |
| Paraphrase | 6 |
| Multi-clause | 5 |
| Table / form | 4 |
| Appendix | 4 |
| Cross-page | 3 |
| Exception / condition | 4 |
| Cross-reference | 3 |
| **Total** | **40** |

The mix deliberately exercises definitions, long clauses, tables, appendices, cross-page reconstruction, regulatory exceptions, and cross-references rather than sampling only easy keyword questions.

## Gold-evidence policy

Each question contains:

- `primary_chunk_ids`: directly answer-bearing evidence. Core metrics use these.
- `supporting_chunk_ids`: related context that can help generation but does not count as a primary hit.
- `required_evidence_groups`: evidence needs that must be represented for complete-evidence evaluation.
- source paragraph/appendix references, pages, and source element IDs for auditability.

For v1, required evidence groups are singleton groups. The schema allows future alternative-equivalent chunks without changing the metric contract.

## Recommended metrics

### Hit@K

A question scores 1 when at least one primary gold chunk appears in the top K.

Report at K = 1, 3, 5 and optionally 10.

### Recall@K

For each question:

`retrieved primary gold chunks / total primary gold chunks`

Macro-average across questions.

This is important for multi-evidence questions where one correct chunk is not enough to cover the whole requirement.

### MRR

Reciprocal rank of the first primary gold chunk. The v1 evaluation runner returns Top 10 and therefore reports this explicitly as **MRR@10**; a primary chunk absent from Top 10 receives reciprocal rank 0 for that run.

### CompleteEvidence@K

A question scores 1 only when every required evidence group is represented in the top K.

This complements MRR by penalising partial retrieval on multi-clause questions.

## Reporting rules

Always report:
- strategy name and exact configuration;
- corpus version / source SHA;
- split (`dev` or `heldout`);
- number of questions;
- Hit@1, Hit@3, Hit@5;
- Recall@1, Recall@3, Recall@5;
- MRR;
- CompleteEvidence@5.

Do not mix development and held-out scores into a single headline metric without also reporting the splits separately.

## Files

- `retrieval_eval_v1.json` — authoritative machine-readable formal dataset.
- `retrieval_eval_v1.csv` — human-review view.
- `retrieval_eval_schema_v1.json` — machine schema.
- `retrieval_regression_smoke_v1.json` — the five previously used smoke/regression questions.
- `validate_retrieval_eval_dataset.py` — deterministic validation against a Stage 5 JSON file.
- `retrieval_config_v1.json` — frozen retrieval/evaluation configuration.
- `run_retrieval_evaluation.py` — live Dense vs Hybrid vs Hybrid+Reranker evaluation runner.

## Next step

After this dataset is frozen, implement the retrieval evaluation runner to execute the **same 40 questions** against Dense, Hybrid and Hybrid + Reranker, then persist per-question rankings and aggregate metrics. Only after the retrieval benchmark is recorded should answer-generation and citation evaluation be layered on top.
