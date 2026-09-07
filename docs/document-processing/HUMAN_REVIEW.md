# Human Review and Corrections

## Why a review layer exists

PDF structure reconstruction is not perfectly reliable. Stage 4.5 therefore provides a non-destructive human review layer between automatic canonical reconstruction and Stage 5 chunking.

```text
Stage 3 extraction         immutable evidence
        ↓
Stage 4 structured JSON    automatic result
        ↓                 ↘ preserved unchanged
correction operations
        ↓
resolved canonical JSON
        ↓
Stage 5 semantic chunks
```

## Current UI scope

The final review workflow is intentionally smaller than the historical development UI. The primary tools are:

1. **Element correction** — adjust a selected region's semantic classification/geometry where supported.
2. **Exact text spans** — reconstruct corrected text from immutable Stage 3 lines/spans rather than free-typing replacement text.
3. **Contextual required relation** — shown only when the corrected semantic type requires a relation. For `definition_text`, the reviewer selects an existing DefinitionEntry using **Belongs to definition**.

Older free-form structural/cross-page correction operations remain replayable for backward compatibility but are not primary product controls.

## Non-destructive storage

```text
backend/data/structured/{document_id}.json    automatic Stage 4
backend/data/corrections/{document_id}.json   manual operation log
backend/data/resolved/{document_id}.json      automatic + corrections
```

This allows comparison of automatic vs reviewed structure and prevents a manual edit from destroying the original Stage 4 evidence.

## Exact-span correction

When geometry/text is corrected, the backend rebuilds text from Stage 3 provenance inside the selected region. Stable/synthesizable line/span IDs make the correction auditable.

The goal is not a general PDF editor. Corrections should point back to immutable extraction evidence.

## Integrity and invalidation

Saving corrections runs structural integrity validation. Blocking inconsistencies prevent Stage 5 eligibility; non-blocking semantic warnings remain diagnostics.

If an upstream stage is rerun and element identity/provenance becomes stale, downstream review/chunk artifacts are invalidated rather than silently applying operations to the wrong content.

## Safety principles

- Prefer explicit user correction over automatic guesswork when semantics are ambiguous.
- Do not silently invent hierarchy.
- Preserve reading order and provenance.
- Keep automatic and reviewed artifacts independently inspectable.
- Treat table/definition/relationship changes conservatively because they affect downstream retrieval units.

## Frontend behavior

The Review workspace provides PDF-page navigation, overlays, selected-region inspection, document-tree context and correction controls. Selection state, page input, drawer focus and narrow-layout behavior are covered by regression/UI tests in the final implementation rather than separate permanent fix documents.
