# Stage 14.4 — Citation & Provenance Explorer

## Status
Candidate until local frontend build, Docker/browser smoke, and citation-navigation checks pass.

## Purpose
Make the frozen Stage 10 deterministic citation chain understandable without adding another retrieval, generation, or citation API call.

The live Playground already receives the facts required for provenance from `POST /api/generation/answer`:

`claim -> citation_id -> evidence_id -> frozen Stage 5 chunk -> source_element_ids -> canonical locator -> PDF page`.

Stage 14.4 only renders those backend-owned facts.

## Interaction
- The inline answer citation marker is the primary entry point to citation details.
- Claim citation chips can open the same citation drawer as a secondary technical entry point.
- Validated Sources stays focused on source reading: bounded preview, `Show full evidence`, and `Open source PDF`. It does not duplicate an `Inspect provenance` action.
- The drawer can be closed with its close button or Escape.
- The answer remains visible behind the non-modal fixed drawer.
- Deep lineage is collapsed behind `Show provenance chain` so normal citation details stay concise.
- The drawer contains an explicit `Open PDF at page ...` action.

## Drawer hierarchy
1. Deterministic validation status.
2. Citation/evidence/chunk/PDF summary.
3. Claims that reference the citation.
4. Optional exact evidence text.
5. Optional `Show provenance chain` disclosure containing the frozen chunk, canonical locators, and exact source element IDs.
6. Source PDF navigation.

## Semantics boundary
`validation_status=valid` means deterministic source provenance resolves against the frozen artifacts and does not escape the citation evidence. It is **not** a live semantic-entailment judgment or an answer-correctness probability.

Human semantic citation-entailment labels remain scoped to the frozen Stage 11 Evaluation view.

## Frozen behavior
Stage 14.4 must not modify:
- retrieval or retrieval parameters,
- reranking,
- Stage 8.2 context assembly,
- grounded generation,
- Stage 10 citation construction/validation,
- Stage 11 benchmark or semantic evaluation.

## Acceptance gates
- Stage 14 focused tests pass.
- Full backend regression passes.
- Stage 11 freeze/evaluation guards pass.
- Local `npm run build` passes.
- Clicking an inline citation opens the drawer without a new network request.
- Validated Sources has no duplicate provenance CTA.
- Deep lineage stays collapsed until `Show provenance chain` is opened.
- Provenance values match the returned citation/evidence/claim objects.
- `Open PDF at page ...` reaches the deterministic cited page.
- Escape and close button dismiss the drawer.
- Narrow/mobile layout stays within the viewport.
