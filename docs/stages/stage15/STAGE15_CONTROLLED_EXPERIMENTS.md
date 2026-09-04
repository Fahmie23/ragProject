# Stage 15 — Controlled Retrieval Experiments & Portfolio Finalization

## Status

Stages 15.0–15.4 are complete. Stage 15.5 portfolio finalization is in progress. The frozen Stage 14 application remains the production baseline.

## Purpose

Stage 15 adds an isolated and reproducible experimentation layer around the frozen production retrieval pipeline, then prepares the project for portfolio and interview presentation.

The production path remains:

`Ask with Cited RAG -> frozen Retrieval v1 -> context assembly -> grounded generation -> deterministic citations`

The experiment path is separate:

`DEV question -> explicit experiment config -> existing retrieval endpoint -> same-execution trace -> persisted run/candidates -> offline scoring`

An experiment must never silently change the production profile.

## Product-scope decision

The document-specific Benchmark page is hidden from primary product navigation and from the Overview page.

This is a UI/product-scope decision only. The following remain preserved internally:

- Stage 11 frozen benchmark datasets and reports;
- Stage 11 validation scripts and freeze guards;
- read-only evaluation backend APIs;
- the existing Evaluation React implementation;
- historical evaluation tests.

This keeps the evidence available without making the document-specific benchmark a primary product surface.

## Roadmap

### Stage 15.1 — Experiment persistence and contracts

Complete. Dedicated PostgreSQL experiment/run/candidate tables and a strict versioned `RetrievalExperimentConfigV1` isolate experiments from production Retrieval v1.

### Stage 15.2 — Existing evidence and dataset audit

Complete. The existing 40-question retrieval benchmark was audited before authoring any new questions. Its 25-question DEV split is valid for controlled development analysis; its 15-question held-out split remains outside the Stage 15 optimization loop.

### Stage 15.3 — Reproducible experiment runs

Complete. `backend/scripts/run_retrieval_experiment.py` executes DEV-only controlled runs through the existing same-execution retrieval endpoint and persists exact config snapshots, query inputs, dense/lexical/RRF/reranker rankings, timings, chunk fingerprints, and candidate records.

### Stage 15.4 — Comparison and findings

Complete. The first experiment varied only `candidate_k = 10, 20, 40` for Hybrid + Reranker. All three variants produced identical Top-5 DEV retrieval quality; larger candidate pools increased candidate volume and latency. Production Retrieval v1 remains unchanged at `candidate_k=20`.

See `docs/evaluation/STAGE15_RETRIEVAL_EXPERIMENT_FINDINGS.md`.

### Stage 15.5 — Portfolio finalization

In progress. Finalize the public README, documentation index, setup/verification instructions, known limitations, repository cleanup, and interview walkthrough. No further retrieval tuning is required for Stage 15.5.

## Stage 15.1 design rules

- Production Retrieval v1 is immutable from experiment APIs.
- Experiment configuration is explicit; no hidden parameter overrides.
- Every run stores an immutable configuration snapshot.
- Existing PDFs, canonical artifacts, Stage 5 chunks, and embeddings are referenced rather than duplicated per run.
- Retrieval scores are ranking/diagnostic values, not correctness probabilities.
- Historical experiment runs remain reopenable and explainable.
- Database migrations must be reversible and must not destructively alter production retrieval tables.
