# Controlled Retrieval Experiments

## Purpose

Stage 15 adds an isolated experimentation layer around the frozen production retrieval system. Its purpose is to produce engineering evidence without silently retuning the system that generated the final held-out benchmark.

There is no Stage 15 “make this production” action.

## Frozen reference

```text
profile            retrieval_v1_stage8_2_top5
embedding          BAAI/bge-m3
lexical            PostgreSQL FTS / OR content terms v1
fusion             RRF k=60, weights 1.0 / 1.0
candidate_k        20
reranker           BAAI/bge-reranker-v2-m3
seed top_k         5
context            frozen Stage 8.2 policy
```

Stage 15 experiments do not modify `POST /api/generation/answer`.

## Data policy

The 25-question retrieval DEV split may be reused for retrospective/development experiments because it was already designated for development. It is explicitly **not independent validation**.

The 15-question retrieval held-out split and the independent Stage 11 answer/citation held-out set remain outside the Stage 15 optimization loop.

The portfolio scope remains the single SC AML/CFT PDF; Stage 15 does not claim cross-document generalization.

## Typed experiment contract

The versioned experiment config can vary only understood retrieval variables such as strategy, `top_k`, `candidate_k`, `rrf_k` and fusion weights while model/backend identities stay locked for retrieval-quality experiments.

Completed runs store immutable configuration snapshots, document SHA/fingerprint, same-execution trace metadata, timing and per-stage candidate ranking evidence.

## `candidate_k` experiment

Experiment ID: `stage15-candidate-k-v1`

Question:

> How does hybrid candidate-pool breadth affect top-5 evidence quality and reranker cost on the existing DEV set?

Controlled variants:

```text
candidate_k = 10
candidate_k = 20   frozen production reference
candidate_k = 40
```

All other retrieval-quality variables remained locked. The executor returned top 10 experimentally so formal `MRR@10` and Top-10 evidence metrics could be measured; production generation remained top-5.

## Results

| candidate_k | Hit@1 | Hit@5 | Recall@5 | MRR@10 | CompleteEvidence@5 | Avg request ms | Avg union |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 844.1 | 14.48 |
| 20 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 1302.3 | 28.64 |
| 40 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 2131.0 | 56.92 |

Top-5 quality was identical across all three variants. `candidate_k=40` improved only deeper Top-10 evidence coverage (`Recall@10` 95.3%, `CompleteEvidence@10` 92.0%) while candidate volume and average end-to-end request duration increased substantially.

The timing values are whole endpoint request durations, not a pure reranker microbenchmark.

## Engineering conclusion

For this DEV workload, a larger candidate pool showed diminishing returns for the production Top-5 evidence objective. `candidate_k=10` is an interesting efficiency result, but Retrieval v1 remains frozen at `20` because a DEV-only ablation is evidence, not an automatic production promotion.

Compact final experiment evidence is committed under:

```text
evaluation/stage15/experiments/stage15-candidate-k-v1/
  aggregate_metrics.json
  comparison_report.txt
```
