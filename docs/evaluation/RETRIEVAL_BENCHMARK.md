# Retrieval Benchmark

## Purpose

The formal retrieval benchmark evaluates retrieval quality only for the frozen SC AML/CFT/CPF regulatory-document corpus. Generation is evaluated separately.

Dataset ID: `sc_aml_cft_retrieval_eval_v1`

```text
40 questions total
├─ 25 DEV
└─ 15 held-out
```

The source document is SHA-bound to the 109-page portfolio PDF and the frozen Stage 5 `semantic-v2.1` chunk corpus (284 chunks).

## Split discipline

### DEV — 25 questions

May be inspected for development, diagnostics and controlled Stage 15 retrospective experiments. It is historical development data, not independent validation.

### Held-out — 15 questions

Consumed only after Retrieval v1 was frozen. It must not be reused for iterative parameter selection and then reported as unseen performance.

The earlier five smoke/regression questions are excluded from the formal benchmark metrics.

## Relevance contract

Questions define primary answer-bearing chunks, optional supporting chunks and required evidence groups. `CompleteEvidence@K` requires all required groups to be represented.

## Metrics

- `Hit@K` — at least one relevant chunk occurs in Top-K.
- `Recall@K` — fraction of gold primary chunks retrieved in Top-K.
- `MRR@10` — reciprocal rank of the first relevant hit, capped at 10.
- `CompleteEvidence@K` — all required evidence groups are represented in Top-K.

Formal K values include 1, 3, 5 and 10.

## Frozen Retrieval v1 configuration

```text
Dense        BAAI/bge-m3 + pgvector exact cosine
Lexical      PostgreSQL FTS, OR content terms v1
Hybrid       weighted RRF, candidate_k=20, rrf_k=60,
             dense_weight=1.0, lexical_weight=1.0
Reranker     BAAI/bge-reranker-v2-m3
Context      structural_one_hop_v1, bounded/non-recursive
```

## Final held-out results

| Metric | Dense | Hybrid | Hybrid + Reranker |
|---|---:|---:|---:|
| Hit@1 | 66.7% | 60.0% | **86.7%** |
| Hit@3 | 73.3% | 80.0% | **86.7%** |
| Hit@5 | 73.3% | **93.3%** | **93.3%** |
| Recall@1 | 56.7% | 50.0% | **76.7%** |
| Recall@3 | 70.0% | 76.7% | **83.3%** |
| Recall@5 | 70.0% | **90.0%** | 86.7% |
| MRR@10 | 0.7225 | 0.7189 | **0.8800** |
| CompleteEvidence@5 | 66.7% | **86.7%** | 80.0% |

Interpretation matters: Hybrid substantially improves evidence coverage; the reranker strongly improves the ordering of the best evidence. The slight held-out Recall@5/CompleteEvidence@5 decrease from Hybrid to Hybrid+Reranker is preserved rather than hidden.

## Context assembly result

Hybrid + Reranker with Stage 8.2 reached `ContextRecall@5=90.0%` and `ContextCompleteEvidence@5=86.7%` with 5.27 context chunks on average.

## Frozen limitations

Two representative held-out failures were intentionally not patched against the final set:

- `RET-010`: a relevant customer-risk-profile chunk existed in the candidate path but was pushed outside the reranked Top-10.
- `RET-031`: the second required cross-page wire-transfer chunk was not retained and one-hop context did not recover it.

A future retrieval version would require new independent evaluation evidence.

Raw held-out artifacts remain under `backend/evaluation/reports/retrieval_v1_heldout/`.
