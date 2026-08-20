# Stage 4.5.3 — Contextual Collapsible UI

This is a frontend-only UX refinement on top of Stage 4.5.2. No extraction, canonicalization, correction, or backend API behavior changes.

## What is collapsible

### Already kept
- Main document sidebar remains collapsible as before.

### New
1. **Overview stage cards** — Stage 1, 2, 3, 4, and 4.5 can each collapse independently.
2. **Stage 3 inspector** — hide/show the Raw Page Inspection panel to give the PDF preview more width.
3. **Structured Document overview** — the document outline + structure summary are grouped under one collapsible `Outline & structure summary` panel.
4. **Stage 4 inspector** — hide/show the Canonical Page Inspection panel to enlarge the page preview.
5. **Correction Sandbox — After elements** — hide/show the right-side corrected-elements panel while visually editing bounding boxes.
6. **Correction Sandbox — selected region editor** — collapse the semantic type + numeric bbox editor after making a correction, without losing the selected region.

## What intentionally stays visible

These are **not** collapsible because hiding them would make the workflow harder or risk losing context:
- global document/header actions;
- pipeline stage rail;
- main workspace tabs;
- Correction Sandbox saved/unsaved status + Save/Reset controls;
- Correction Sandbox mode tabs (Preview, Before JSON, After JSON, Correction Log);
- page navigation.

## Persistence

Workspace-size preferences use `localStorage`:
- `rag-overview-stage-<step>-collapsed`
- `rag-stage3-inspector-collapsed`
- `rag-structure-overview-collapsed`
- `rag-stage4-inspector-collapsed`
- `rag-correction-elements-collapsed`

The selected-region editor is intentionally session-only and opens again when moving to another page/document.

## Recommended usage

For visual bbox correction:
1. collapse the left document sidebar if needed;
2. open Correction Sandbox;
3. hide **After elements**;
4. collapse the selected-region numeric editor when it is not needed;
5. the PDF preview expands to use the available width.

For JSON inspection, leave the page inspector open and switch to Page JSON.
