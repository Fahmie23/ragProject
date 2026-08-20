# Stage 4.5.2 — Unified Correction Sandbox

This update moves all Stage 4.5 manual editing out of **Structured document** and into one dedicated **Correction Sandbox**.

## Why this change

The previous UI mixed inspection and modification in the same Structured Document tab. That made it harder to understand whether the user was looking at automatic Stage 4, resolved Stage 4.5, or an unsaved edit session.

Stage 4.5.2 separates those responsibilities:

```text
Structured Document
= read-only inspection

Correction Sandbox
= human editing, before/after comparison, correction log, save/reset
```

The backend correction model is unchanged: automatic Stage 4 remains immutable, corrections are stored as operations, and the resolved Stage 4.5 artifact is generated from Stage 4 + corrections.

## Structured Document

Structured Document is now read-only.

It supports:
- Automatic / Resolved toggle
- Page-number input plus previous/next arrows
- Bounding-box overlays
- Element inspection
- Page JSON
- `Open Correction Sandbox`

It no longer exposes move, resize, split, merge, draw, relabel, delete, undo, redo, or save controls.

## Correction Sandbox

The sandbox is now the single editing workspace.

### Preview & Edit

Supports:
- Move / resize bbox
- Exact bbox numeric input
- Relabel semantic type
- Split horizontally
- Merge selected elements
- Draw missing region
- Delete false-positive region
- Undo / redo unsaved operations
- Reset current page
- Reset all saved corrections
- Save correction operations

The preview can display both:
- **Before**: immutable automatic Stage 4 regions, dashed
- **After**: resolved Stage 4.5 + current unsaved operations, editable

### Before JSON

Shows the immutable automatic Stage 4 JSON for the selected page.

### After JSON

Shows a live page-level Stage 4.5 preview containing:
- saved corrections already represented by the resolved structure
- current unsaved correction operations
- the current corrected element geometry/types

After saving, the backend may refine text fields by re-reading immutable Stage 3 spans inside corrected bounding boxes.

### Correction Log

Shows both human-readable operations and raw page-level correction JSON:
- saved operations
- unsaved operations
- operation IDs
- source element IDs
- relabel targets / result regions

## Page navigation

All relevant workspaces keep the direct page-number input:

```text
←  Page [ 85 ] / 118  →
```

Typing a page number and pressing Enter jumps directly to it. If the Correction Sandbox has unsaved operations, changing page asks for confirmation before discarding them.

## Data safety

Nothing about the backend persistence model changed.

```text
data/structured/   automatic Stage 4

data/corrections/  auditable Stage 4.5 operations

data/resolved/     automatic Stage 4 + saved corrections
```

Stage 5 should consume the resolved artifact when it exists, otherwise the automatic structured artifact.

## Apply to an existing Stage 4.5.1 project

Only frontend files changed:

```text
frontend/src/App.tsx
frontend/src/styles.css
frontend/package.json
```

No backend migration is required.

Run:

```bash
cd ~/ragProject/frontend
npm install
npm run build
npm run dev
```

Backend regression tests for the packaged project remain:

```text
21 passed
```
