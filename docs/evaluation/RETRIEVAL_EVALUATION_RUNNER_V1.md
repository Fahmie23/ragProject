# Retrieval Evaluation Runner v1

## Purpose

This runner evaluates the frozen retrieval stack against the formal 40-question dataset without mixing retrieval quality with LLM answer generation.

Strategies:

1. `dense` — BGE-M3 + pgvector cosine retrieval.
2. `hybrid` — Dense + PostgreSQL FTS + reciprocal-rank fusion.
3. `hybrid_rerank` — Dense Top-20 + Lexical Top-20 union reranked with BGE reranker v2-m3.

## Split discipline

The runner defaults to the **25-question development split**.

```bash
python scripts/run_retrieval_evaluation.py --split dev
```

The 15-question held-out split is protected. It can only run with a frozen retrieval configuration and an explicit acknowledgement:

```bash
python scripts/run_retrieval_evaluation.py \
  --split heldout \
  --confirm-heldout I_HAVE_FROZEN_RETRIEVAL
```

Do not inspect held-out results, retune retrieval, then report the same held-out run as unbiased performance.

## Frozen configuration

`backend/evaluation/retrieval/retrieval_config_v1.json` records the reproducible Stage 8.1 configuration:

- embedding: `BAAI/bge-m3`, device `auto`;
- hybrid candidate K: 20;
- RRF K: 60;
- dense weight: 1.0;
- lexical weight: 1.0;
- reranker: `BAAI/bge-reranker-v2-m3`, device `auto`, batch size 2;
- evaluation return window: Top 10.

Top 10 is used only so Hit/Recall/CompleteEvidence can be measured at 1, 3, 5 and 10. Candidate generation and ranking parameters remain frozen.

## Metrics

Per question, the runner calculates:

- Hit@1 / @3 / @5 / @10;
- Recall@1 / @3 / @5 / @10;
- MRR@10 (reciprocal rank of the first primary gold chunk within the returned Top-10 window);
- CompleteEvidence@1 / @3 / @5 / @10.

`primary_chunk_ids` are used for core scoring. `supporting_chunk_ids` are kept for audit/context and do not inflate the formal metrics.

## Failure behavior

A failed HTTP request is never silently treated as a retrieval miss. The runner:

- saves the error;
- marks the aggregate strategy result `valid=false`;
- exits with status 1 after preserving partial diagnostics.

This avoids publishing artificially low or partial metrics when the backend/model/database failed.

## Resume behavior

Every successful raw endpoint response is written immediately under `responses/<strategy>/<question_id>.json`.

If a long GPU run is interrupted:

```bash
python scripts/run_retrieval_evaluation.py --split dev --resume
```

The runner reuses saved responses and continues missing calls. Existing result directories are never silently overwritten. Use `--overwrite` only when intentionally starting a fresh run.

## Development output

Default location:

```text
backend/retrieval_evaluation_results/dev/
├── run_manifest.json
├── all_results.json
├── per_question_results.csv
├── aggregate_metrics.json
├── comparison_report.txt
├── all_retrieval_evaluation_results.txt
└── responses/
    ├── dense/
    ├── hybrid/
    └── hybrid_rerank/
```

The easiest files to share for review are:

```text
all_retrieval_evaluation_results.txt
aggregate_metrics.json
```

## Recommended sequence

1. Run the 25 development questions.
2. Diagnose only systematic defects; do not chase individual hard questions.
3. If no retrieval changes are justified, keep `retrieval_config_v1.json` frozen.
4. Run the 15 held-out questions once with the explicit held-out confirmation.
5. Record Dense vs Hybrid vs Hybrid+Reranker metrics.
6. Only then integrate benchmark results into the Evaluation frontend and proceed to answer generation/citations.

## Stage 8.2 context metrics

For `hybrid_rerank`, the runner now calls `/api/retrieval/hybrid-rerank-context`. Raw `hits` are scored exactly as before. The separate `context_chunks` array is additionally scored with `ContextRecall@K` and `ContextCompleteEvidence@K`. Expanded chunks never alter MRR or raw Recall@K.

The Stage 8.2 configuration is `draft`, so held-out evaluation remains protected while development context assembly is being validated.
