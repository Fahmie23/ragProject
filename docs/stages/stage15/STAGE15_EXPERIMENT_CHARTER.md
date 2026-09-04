# Stage 15.0 — Controlled Experiment Charter

Status: **Authoritative Stage 15 experiment policy**

This charter supersedes any earlier provisional Stage 15 sequence that began
with UI or database implementation. The Stage 15.1B storage tables already
created remain compatible with this policy; this document defines how they may
be used.

## Purpose

Stage 15 exists to produce engineering evidence about the retrieval system
without changing the frozen production RAG behavior through ad-hoc tuning.

The governing question is:

> Which experiments provide meaningful engineering evidence, rather than just
> making the project bigger?

## Frozen production reference

The production retrieval profile remains:

- Profile: `retrieval_v1_stage8_2_top5`
- Dense model: `BAAI/bge-m3`
- Lexical backend: PostgreSQL FTS
- Lexical query formulation: `or_content_terms_v1`
- Lexical ranking: term coverage, then `ts_rank_cd`
- Fusion: reciprocal rank fusion
- `candidate_k = 20`
- `rrf_k = 60`
- `dense_weight = 1.0`
- `lexical_weight = 1.0`
- Reranker: `BAAI/bge-reranker-v2-m3`
- Reranked seed `top_k = 5`
- Context assembly: frozen Stage 8.2 bounded structure-aware policy

Stage 15 experiments must not silently alter the production profile used by
`POST /api/generation/answer`.

There is no Stage 15 "make this production" action.

## Evaluation independence

The original Stage 11 held-out dataset is final independent evaluation data.

It must not be used for:

- iterative parameter tuning;
- choosing candidate K, Top K, RRF K, or fusion weights;
- selecting a retrieval strategy because it scores best on that held-out set;
- repeated configuration search.

Existing frozen metrics may be displayed or cited descriptively, but the
questions must remain outside the Stage 15 optimization loop.

## Allowed Stage 15 data

The existing retrieval benchmark contains a formally separated 25-question DEV
split and 15-question held-out split.

Stage 15 may reuse the **DEV split** for controlled retrospective/development
experiments because the dataset contract explicitly allows DEV questions to be
inspected when diagnosing retrieval failures and tuning retrieval configuration.

This DEV split is historical development data, not independent validation.
Stage 15 findings derived from it must be described accordingly.

The original 15-question retrieval held-out split and the independent Stage 11
held-out answer/citation benchmark remain outside the Stage 15 optimization
loop.

The project scope is intentionally the single SC AML/CFT PDF. A second document
is not required for Stage 15 portfolio completion, and Stage 15 does not claim
cross-document generalization.

## V1 experiment variables

The first controlled retrieval contract exposes only variables already
implemented and understood by the project:

- strategy: `dense`, `hybrid`, or `hybrid_reranker`;
- `top_k`;
- `candidate_k` for hybrid strategies;
- `rrf_k` for hybrid strategies;
- `dense_weight` for hybrid strategies;
- `lexical_weight` for hybrid strategies.

The initial experiment workspace does not support arbitrary model switching.

## Locked components

For retrieval-quality experiments, these remain system-owned:

- embedding model;
- embedding device;
- lexical backend and query formulation;
- fusion implementation;
- reranker model;
- reranker device and batch size;
- generation model and prompt;
- frozen Stage 5 chunks;
- frozen production context-assembly behavior.

Runtime/device variables may be studied later only in an explicitly separate
performance-profiling experiment.

## Persistence semantics

`retrieval_experiments` is an editable experiment definition.

`retrieval_experiment_runs` is an immutable execution snapshot after
completion.

`retrieval_experiment_candidates` preserves per-run ranking evidence.

A completed run must retain the exact normalized configuration used for that
run even if the parent experiment definition is edited later.

Historical candidate `chunk_id` values are identifiers, not live foreign keys,
because Stage 5 synchronization can delete and recreate live chunk rows.

## Initial evidence-producing experiment

The Dense vs Hybrid vs Hybrid + Reranker architecture ablation already exists
in the formal retrieval benchmark, so Stage 15 must not rerun it merely to make
the experiment layer look busier.

The first new evidence-producing Stage 15 experiment therefore asks a narrower
engineering question:

> Does increasing `candidate_k` materially improve Hybrid + Reranker retrieval
> quality enough to justify the additional candidate/reranking cost?

The controlled variants are:

1. `candidate_k = 10`
2. `candidate_k = 20` — frozen production reference
3. `candidate_k = 40`

All other retrieval-quality variables remain locked. The experiment uses only
the existing 25-question DEV split and does not promote a DEV winner into
production.

## Stage 15 sequence

- **15.0** Experiment charter, freeze rules, dataset independence
- **15.1** Persistence and typed experiment contracts
- **15.2** Existing benchmark/dataset audit and DEV-only experiment scope
- **15.3** One hypothesis-driven `candidate_k` retrieval ablation
- **15.4** Findings and reproducibility report
- **15.5** Portfolio finalization

## Promotion policy

Stage 15 is diagnostic and experimental.

No experiment replaces Retrieval v1 during Stage 15. A future production
promotion, if ever justified, requires a separate explicit decision with
independent evaluation rather than an automatic winner-selection rule.
