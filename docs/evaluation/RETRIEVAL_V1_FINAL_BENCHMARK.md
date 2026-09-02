# Retrieval v1 — Final Held-out Benchmark

This report records the **single frozen held-out retrieval run** used for Retrieval v1. The 15 held-out questions must not be used to retune Retrieval v1 and then re-reported as unseen performance.

## Frozen configuration

- Dense: BAAI/bge-m3 + pgvector cosine
- Lexical: PostgreSQL FTS, OR content-term formulation
- Hybrid: RRF, `candidate_k=20`, `rrf_k=60`, dense weight `1.0`, lexical weight `1.0`
- Reranker: BAAI/bge-reranker-v2-m3
- Context: Stage 8.2 `structural_one_hop_v1`, same-section, non-recursive, page gap <= 1

## Held-out results (15 questions)

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

Stage 8.2 context assembly on Hybrid + Reranker produced:

- ContextRecall@3: 83.3%
- ContextCompleteEvidence@3: 80.0%
- ContextRecall@5: **90.0%**
- ContextCompleteEvidence@5: **86.7%**
- Average context chunks at K=5: **5.27**

## Known held-out limitations

The frozen run exposed genuine limitations that are intentionally **not patched against this held-out set**:

- `RET-010`: the customer-risk-profile gold chunk was available to Dense/Hybrid but was pushed outside the reranked Top-10.
- `RET-031`: the second required cross-page wire-transfer chunk was not retained by Hybrid/Reranker and was not recovered by one-hop context assembly.

A future Retrieval v2 may address these cases, but it must be evaluated on a new unseen set.

## Stage 9 evidence budget

Stage 9 uses Top-5 reranked seeds plus Stage 8.2 expansion as a practical production evidence budget. This choice belongs to the downstream generation configuration. Future answer-generation quality will be measured on a separate answer/citation evaluation rather than treating the retrieval held-out set as an unseen generation test.

Raw benchmark artifacts are stored in `backend/evaluation/reports/retrieval_v1_heldout/`.
