# Stage 14.2 — Core Q&A Playground

Status: candidate until local browser + Docker validation passes.

## Goal

Make the first user-facing RAG flow correct and unambiguous without changing the frozen production pipeline.

The default playground path is:

`document -> question -> POST /api/generation/answer -> cited answer -> validated sources -> claim/evidence provenance`

## Product boundary

The screen has two explicit modes:

- **Cited answer** — production path. The user can choose a document and question only. Retrieval parameters are not configurable and remain frozen.
- **Retrieval experiment** — diagnostic path. Dense/Hybrid/Hybrid+Reranker controls are isolated here and never change the production answer profile.

This prevents Top-K/Candidate-K controls from being mistaken for generation settings.

## Stage 14.2 behavior

- Enter submits the active mode.
- Switching mode/document/question clears stale outputs.
- Starting retrieval clears any previous generated answer.
- Starting generation clears any previous experimental retrieval result.
- Generated citation markers are clickable and resolve through backend-owned deterministic citation objects.
- Citation source cards show the actual evidence chunk text returned by the generation endpoint.
- Abstentions render as insufficient evidence and do not fabricate citations.
- The old prototype evaluation numbers are removed from the visible UI. The detailed frozen Evaluation Explorer remains deferred to Stage 14.5.

## Non-goals

Stage 14.2 does not:

- tune retrieval, reranking, context assembly, prompts, or citations;
- calculate RAG/evaluation metrics in React;
- expose a production retrieval trace by executing retrieval twice;
- modify the held-out benchmark;
- implement the Stage 14.5 Evaluation Explorer.

## Acceptance gates

Before freezing Stage 14.2:

1. Stage 14.1 contract tests pass.
2. Stage 14.2 UI contract tests pass.
3. Stage 11 freeze guards pass.
4. Full backend regression passes.
5. `npm run build` passes with the Stage 13 locked frontend environment.
6. Docker frontend/backend are rebuilt and healthy.
7. Browser smoke proves:
   - Cited answer is the default mode.
   - Enter and the primary button run a real production answer.
   - Inline citation markers open the cited PDF page.
   - Source cards show matching evidence text.
   - Retrieval experiment remains isolated from cited-answer state/settings.
   - An out-of-scope/insufficient-evidence question renders abstention correctly.

No Stage 14.2 freeze/tag should be created until those gates pass locally.
