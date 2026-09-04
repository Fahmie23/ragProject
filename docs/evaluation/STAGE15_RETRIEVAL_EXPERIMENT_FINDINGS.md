# Stage 15 Retrieval Experiment Findings

## Scope

Stage 15 evaluates controlled retrieval changes without modifying the frozen
Retrieval v1 production profile.

The experiment uses only the existing 25-question DEV split from
`sc_aml_cft_retrieval_eval_v1`.

The 15-question held-out split is not used for experiment selection.

## Experiment

Experiment ID:

`stage15-candidate-k-v1`

Retrieval strategy:

`hybrid_reranker`

Independent variable:

`candidate_k`

Variants:

- 10
- 20 — frozen production reference
- 40

Locked components:

- embedding model: `BAAI/bge-m3`
- dense retrieval: exact cosine / pgvector
- lexical backend: PostgreSQL FTS
- lexical query formulation: `or_content_terms_v1`
- lexical ranking: term coverage then `ts_rank_cd`
- fusion: Reciprocal Rank Fusion
- `rrf_k = 60`
- dense weight = 1.0
- lexical weight = 1.0
- reranker: `BAAI/bge-reranker-v2-m3`
- Stage 5 corpus: `semantic-v2.1`

Production Retrieval v1 was not changed by this experiment.

## Results

| candidate_k | Hit@1 | Hit@5 | Recall@5 | MRR@10 | CompleteEvidence@5 | Avg latency | Avg candidate union |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 844.1 ms | 14.48 |
| 20 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 1302.3 ms | 28.64 |
| 40 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 2131.0 ms | 56.92 |

At Top 5, all three candidate sizes produced identical retrieval quality.

Increasing candidate_k increased execution cost substantially:

- 10 → 20 roughly doubled the candidate union and increased average latency.
- 20 → 40 roughly doubled the candidate union again and further increased latency.

`candidate_k=40` produced a small improvement only at deeper Top-10 evidence
coverage:

- Recall@10: 93.3% → 95.3%
- CompleteEvidence@10: 88.0% → 92.0%

This deeper-rank improvement did not improve Top-5 retrieval quality.

## Engineering interpretation

For this DEV benchmark, larger candidate pools did not improve the evidence
available to the production Top-5 retrieval path.

`candidate_k=10` therefore appears sufficient for the measured Top-5 DEV
workload and is more efficient than 20 or 40.

However, this experiment is not used to change production Retrieval v1.

The frozen production value remains:

`candidate_k=20`

because:

1. Retrieval v1 was frozen before Stage 15.
2. Stage 15 experiments use DEV data only.
3. The held-out retrieval benchmark is not reused for iterative configuration
   selection.
4. A DEV-only improvement is recorded as engineering evidence rather than
   silently promoted to production.

## Conclusion

The experiment shows that candidate-pool size has diminishing returns for this
document and benchmark.

Increasing candidate_k from 10 to 20 or 40 did not improve Top-5 retrieval
quality, while increasing candidate volume and latency.

The result supports a general engineering principle:

> More retrieval candidates are not automatically better; candidate-pool size
> should be justified by measured retrieval benefit relative to computational
> cost.

The experiment does not establish a universal optimal candidate_k for other
documents or domains.
