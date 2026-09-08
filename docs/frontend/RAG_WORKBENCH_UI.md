# RAG Document Studio UI

## Product information architecture

The portfolio-facing navigation is intentionally compact:

```text
Overview | Documents | Search & Ask | Evaluation
```

The product identity is **RAG Document Studio**. The document parser/correction workbench is an expert document-intelligence module inside a broader RAG product rather than being the identity of the entire application.

## Overview

Provides the project/pipeline summary and routes reviewers toward the document module or live Search & Ask experience without turning the landing page into a benchmark dashboard.

## Documents

A selected document exposes:

```text
Overview | Content | Structure | Review | Knowledge | Search Index
```

The workspace supports:

- upload/intake and lifecycle state;
- extracted page evidence and overlays;
- canonical document structure;
- non-destructive human review/corrections;
- semantic chunks and knowledge representation;
- embedding/index controls and diagnostics.

Advanced correction controls use progressive disclosure so relation fields appear only when required by the selected semantic correction.

## Search & Ask

Search & Ask has two intentionally separate modes.

### Cited answer

The default production flow is:

```text
document + question
      ↓
POST /api/generation/answer
      ↓
retrieval + reranking + bounded context
      ↓
grounded answer
      ↓
deterministic citations
      ↓
validated source cards + visual evidence
```

Strongly related cited figures/tables may be promoted into the left answer panel as **related source evidence**, while the right-hand Validated Sources panel remains the complete evidence record. The UI explicitly states that Option-A visuals are source evidence rather than VLM-interpreted answer inputs.

### Retrieval experiment

Diagnostic mode can run dense, hybrid, or hybrid + reranker retrieval without calling the generation provider. It exposes candidate ranking and visual/source evidence but does not mutate the frozen production retrieval profile.

## Retrieval & context inspector

The production answer inspector renders retrieval/context information from the **same generation execution**. It shows dense candidates, lexical candidates, RRF union, reranker ordering, seed IDs and structurally attached context.

Opening the inspector performs no second retrieval. Scores are described as ranking/debugging signals, not probabilities.

## Citation provenance explorer

Inline citation markers and source actions can open a read-only provenance drawer with deterministic validation, evidence/chunk/PDF identity, associated claims, exact evidence text and optional deeper source-element lineage.

`Open source PDF` and visual `View highlighted page` actions navigate back to original-document provenance without modifying the source PDF.

## Evaluation

Evaluation renders frozen answer/citation benchmark artifacts. It is a portfolio/reproducibility surface and is explicitly separated from live Search & Ask so document-specific metrics are not misread as arbitrary-document quality estimates.

## State-safety principles

The frontend guards against stale document/request state, asynchronous request races and duplicated network work. Retrieval, generation, citation, visual-relationship and evaluation semantics remain backend-owned.
