# RAG Workbench UI

## Product information architecture

The final portfolio-facing navigation is intentionally small:

```text
Overview | Documents | RAG Playground
```

The product identity is **RAG Workbench**. Document parsing/review is an expert Document Intelligence module rather than the only visible purpose of the application.

## Overview

Provides the project/pipeline summary and routes reviewers toward the document module or live RAG Playground without turning the landing page into an evaluation dashboard.

## Documents

The document workbench exposes the underlying pipeline for inspection:

- upload/intake status;
- extracted page evidence and overlays;
- canonical structure/tree;
- human Review workflow;
- semantic chunks;
- embedding/index controls and runtime diagnostics where relevant.

The advanced correction UI uses progressive disclosure so relation controls appear only when required by the selected corrected type.

## RAG Playground

The default user flow is the frozen production cited-answer path:

```text
document + question
      ↓
POST /api/generation/answer
      ↓
cited answer
      ↓
validated sources
      ↓
retrieval/context/provenance inspection
```

Production retrieval parameters are not presented as casual answer-generation knobs.

The UI can still expose diagnostic retrieval behavior without changing the frozen answer path.

## Retrieval & context inspector

The inspector renders `retrieval_trace_v1` from the **same generation execution**. It shows dense candidates, lexical candidates, RRF union, reranker ordering, seed IDs and structurally attached context.

Opening the inspector performs no second retrieval. Scores are described as ranking/debugging signals, not probabilities.

## Citation provenance explorer

Inline citation markers can open a read-only drawer with deterministic validation, evidence/chunk/PDF identity, associated claims, exact evidence text and optional deeper source-element lineage.

`Open PDF at page ...` navigates to the backend-owned deterministic citation page.

## Benchmark UI scope

The Stage 14 benchmark-report implementation remains preserved internally and can render frozen Stage 11 evidence. It is intentionally hidden from the primary product navigation because a single-document benchmark should not look like a live quality score for arbitrary uploaded PDFs.

## State-safety principles

The final frontend guards against stale document/request state, asynchronous request races and duplicated network work. Retrieval, generation, citation and scoring semantics remain backend-owned.
