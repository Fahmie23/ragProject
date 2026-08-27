# RAG Document Pipeline — Stages 1–5

A portfolio-oriented RAG ingestion pipeline that makes extraction, structure, human review, retrieval cleaning, and semantic chunking inspectable before embeddings or indexing.

## Current pipeline

```text
Document
   │
   ▼
1. Intake
   │  original file + SHA-256
   ▼
2. Validation & Classification
   │  format / PDF type / safety checks
   ▼
3. Deterministic Extraction
   │  PyMuPDF blocks / lines / spans / images / tables / coordinates
   ▼
4. Layout & Structure Reconstruction
   │  PyMuPDF4LLM Layout + canonical normalization
   ▼
4.5 Human Review & Layout Correction
   │  non-destructive bbox / semantic overrides
   ▼
Resolved Canonical Document JSON
   │
   ▼
5. Retrieval Preparation & Semantic Chunking
   │  deterministic cleaning + semantic refinement + quality validation
   ▼
Chunk JSON
```

## Stage 4 design

Stage 4 now separates layout evidence from semantic meaning. PyMuPDF4LLM remains the layout provider, while the canonical semantic-v2 resolver owns ambiguous structural classification:

```text
PDF
  │
  ├─ Stage 3 raw extraction ----------------------┐
  │                                               │
  └─ PyMuPDF4LLM Layout                          │
       │                                          │
       ▼                                          │
  data/layout/{document_id}.json                 │
       │                                          │
       └──────────────┬───────────────────────────┘
                      ▼
             Initial canonical layout roles
                      │
                      ▼
             Semantic feature extraction
                      │
                      ▼
           Sequence/context resolver
                      │
                      ▼
             Heading scope resolver
                      │
                      ▼
          Specialized reconstruction
                      │
                      ▼
        data/structured/{document_id}.json
```

The vendor Layout output is intentionally persisted separately from our canonical schema. This gives us a stable internal contract for later RAG stages and a way to debug layout-model errors independently from our normalization logic.

## Canonical element types

```text
title
subtitle
document_metadata
section_header
group_header
clause
subclause
definition_term
definition_text
paragraph
list_item
table
figure
caption
page_header
page_footer
footnote
formula
unknown
```

Stage 4.4 also creates document-level logical records for definitions, clauses, appendices, cross-page tables, figures, and structural relationships. The canonical Stage 4 schema is `1.8`. Schema 1.8 preserves each vendor `layout_role`, adds `group_header`, and adds auditable semantic classification metadata (`confidence`, `evidence`, and alternatives).

PyMuPDF4LLM Layout currently exposes corresponding page box classes such as `text`, `picture`, `table`, `caption`, `title`, `section-header`, `page-header`, `page-footer`, `list-item`, `footnote`, and `formula`. These values are now retained as **layout evidence**, not treated as final semantic truth. Ambiguous structural text is resolved from numbering, geometry, typography, punctuation, proposition shape, neighboring elements, and marker sequences. See `STAGE4_6_SEMANTIC_V2_ARCHITECTURE.md` and `STAGE4_6_1_SEMANTIC_TAXONOMY.md`.

## Hierarchy evidence

For initial `section_header` candidates, heading level evidence is determined in this order:

1. PDF bookmark / TOC match
2. Explicit heading numbering such as `2.3.1`
3. Dominant font-size rank from Stage 3 spans
4. Unknown when no evidence exists

Semantic v2.1 then resolves local heading scope. TOC/numbering evidence is stronger than typography-only evidence, but no single source is treated as universal semantic truth. A weak heading immediately before a stronger outline heading can become `group_header` rather than an empty sibling section.

The selected source is persisted as:

```json
{
  "heading_level": 2,
  "heading_level_source": "pdf_toc"
}
```

Semantic classification also persists deterministic support metadata. When alternatives exist, their scores are normalized into the remaining confidence mass, and unresolved hierarchy can lower confidence without changing the selected type. These values are review aids, not statistically calibrated probabilities.

## Canonical body text

The canonical body retains semantic content but deliberately excludes repetitive or non-body regions such as:

```text
page_header
page_footer
figure
```

Those elements remain present in the page element list for provenance and frontend inspection.

Tables use their structured cells and Markdown representation when available.

## Traceability

Every canonical element records both:

- the PyMuPDF4LLM Layout box that classified it
- overlapping Stage 3 raw block/table IDs

Example:

```json
{
  "source": {
    "layout_box_index": 3,
    "layout_box_class": "section-header",
    "stage3_block_ids": ["p1-b4"],
    "stage3_table_ids": []
  }
}
```

## Stage 4.5 human review

Stage 4.5 adds a non-destructive human correction layer before chunking. In the simplified 4.5.8.16 workflow, the active UI focuses on element correction and exact Stage 3 text-span reconstruction. When a semantic type needs a parent relation, the relevant selector appears contextually. For example, one or more `definition_text` elements can be assigned to an existing DefinitionEntry in one operation; the backend derives section and bidirectional membership fields automatically. Corrections are persisted independently of automatic Stage 4:

```text
data/structured/{document_id}.json   automatic Stage 4
data/corrections/{document_id}.json  manual operation log
data/resolved/{document_id}.json     automatic + manual corrections
```

For geometry-changing operations, corrected text is rebuilt from immutable Stage 3 spans inside the edited bounding box. If Stage 3 or Stage 4 is rerun, Stage 4.5 artifacts are invalidated rather than silently applied to stale element IDs.

The page navigator also accepts direct numeric input (`Page [85] / 118`) in addition to previous/next arrows.

Stage 4.5.1 adds a frontend-only **JSON Preview Sandbox**. It can load page-level Stage 3, automatic Stage 4, or resolved Stage 4.5 JSON into an editable JSON panel, validate it, render the supplied bounding boxes over the original PDF page, and compare the edited JSON against the loaded baseline. The sandbox never writes to the ingestion pipeline.

The Structured Document → Corrections inspector now has both **Operations** and **Correction JSON** views, while the full persisted correction artifact remains available under **JSON artifacts → Corrections**.

Stage 4.5.8.3 adds conservative repair for TOC rows where an uppercase heading and the following numbered entry were merged into one vendor table row. Stage 3 and Stage 4 viewers also expose optional overlay labels, and selecting a table opens a full row-level inspector with a suspicious-row warning. See `STAGE4_5_8_3_TOC_TABLE_ROW_REPAIR_AND_INSPECTOR.md`.

Stage 4.5.8.4 adds a safety guard around that repair: automatic TOC row splitting is allowed only on pages with an explicit heading-like `CONTENTS` / `TABLE OF CONTENTS` context. TOC-shaped tables elsewhere are preserved unchanged. See `STAGE4_5_8_4_TOC_CONTEXT_GUARD.md`.

Stage 4.5.8.5 adds carefully gated cross-page TOC-context inheritance. A continuation page without a repeated `CONTENTS` heading is eligible only when the previous and next table fragments satisfy the same geometry, boundary, column-compatibility, section-context, and TOC-shape checks used by logical-table reconciliation. Inheritance can propagate across multiple adjacent TOC pages and stops as soon as any continuation signal fails. See `STAGE4_5_8_5_CROSS_PAGE_TOC_CONTEXT_INHERITANCE.md`.

Stage 4.5.8.6 reorganizes the frontend into a document workbench and adds a dedicated **Layout** workspace. The Layout view can reconstruct a page directly from Stage 3/Stage 4 JSON, compare that reconstruction with the original PDF, inspect bounding boxes/reading order/table content, and locally render pasted page JSON without changing saved pipeline data. See `STAGE4_5_8_6_WORKBENCH_FRONTEND.md`.

See `STAGE4_5_HUMAN_REVIEW.md` for the correction model and `STAGE4_5_1_JSON_SANDBOX.md` for the JSON preview workflow.

Stage 4.5.8.16 simplifies the correction workflow: dedicated structured-semantics, definition-link, and free-form cross-page relationship editors are removed from the active UI. `definition_text` membership is now explicit through a contextual **Belongs to definition** selector and one bulk `assign_definition` operation. Stage 4.5 no longer guesses definition membership or repairs clause hierarchy automatically; legacy operations remain replayable for backward compatibility. See `STAGE4_5_8_16_SIMPLIFIED_CORRECTION.md`.

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload
```


API:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

UI:

```text
http://localhost:5173
```

The UI is organized into:

```text
Overview
Raw extraction
Structured document
JSON Preview
JSON artifacts
```

### Structured document view

Provides:

- document section outline
- page image
- semantic bounding-box overlays
- canonical reading order
- element-type filtering
- hierarchy evidence
- Stage 3 source trace
- separate canonical / Layout / Stage 3 JSON inspection
- page-scoped Stage 4 JSON for definitions, clauses, appendices, logical tables, figures, and relationships

## API endpoints

### Stages 1–3

```text
POST /api/documents/upload
GET  /api/documents
GET  /api/documents/{document_id}
GET  /api/documents/{document_id}/file
POST /api/documents/{document_id}/extract
GET  /api/documents/{document_id}/extraction
GET  /api/documents/{document_id}/pages/{page_number}/preview
```

### Stage 4

```text
POST /api/documents/{document_id}/structure
GET  /api/documents/{document_id}/structure
GET  /api/documents/{document_id}/layout
```

### Stage 4.5

```text
GET    /api/documents/{document_id}/corrections
PUT    /api/documents/{document_id}/corrections
DELETE /api/documents/{document_id}/corrections
GET    /api/documents/{document_id}/resolved-structure
POST   /api/documents/{document_id}/corrections/validate
POST   /api/documents/{document_id}/corrections/approve-relationships
```

## Stage boundaries

Stage 4 does **not** do:

- LLM metadata generation
- semantic chunking
- embeddings
- vector indexing
- retrieval
- answer generation

It also runs PyMuPDF4LLM Layout with OCR disabled in this implementation so OCR does not silently alter the established Stage 3 text source.

Stage 5 consumes **only** a saved Resolved Stage 4.5 artifact with passing structural integrity. If the automatic Stage 4 result needs no edits, Review can be finalized with an empty correction set to create the resolved artifact. Stage 5 never consumes raw PyMuPDF or vendor Layout output directly.

## Stage 5 — Retrieval preparation & semantic chunking

Stage 5 is implemented as a deterministic, auditable layer between resolved document structure and future embeddings/indexing. It writes `data/chunks/{document_id}.json` and never mutates `resolved/{document_id}.json`. **Semantic v2 is now the default**, while Semantic v1 remains available as a legacy baseline.

The active Stage 5 implementation is fully deterministic: it has no external model provider, model API key, model SDK, or model-generated chunk plan.

Semantic v2 is generic rather than tuned to the current AML/CFT test PDF. It uses canonical hierarchy/continuation relationships, section identity, semantic type, adjacency, punctuation and token budgets. It adds parent/dependent-child grouping, parent context on oversized hierarchy splits, conservative short-sibling packing, contextual-note attachment, navigation-only section filtering, cross-page continuation merging, and row-aware table splitting. The chunk artifact now includes `context_element_ids`, `refinement_tags`, and a deterministic quality report (`orphan_child`, `dangling_intro`, navigation leakage, and repair counters).

Key behavior:

- eligibility requires a saved resolved artifact with passing structural integrity;
- page headers, page footers, margin page numbers, repeated margin text, empty content, and overlapping duplicate text can be excluded from retrieval with explicit reasons;
- section headers are retained as context rather than standalone retrieval noise;
- definition term + definition text are grouped as one semantic unit, including cross-page definitions;
- logical tables use canonical cell structure; figure records use available textual caption/explanation context;
- clauses/subclauses absorb immediately following prose/list content until the next semantic boundary;
- oversized units are split deterministically under a hard maximum with bounded overlap;
- every chunk retains page, canonical element, Stage 3 span/block/table, and relationship provenance;
- token counts use `regex_estimate_v1` and are explicitly estimates, not model-specific tokenizer counts;
- any Stage 3, Stage 4, or Stage 4.5 change invalidates the saved Stage 5 artifact.

API:

```text
POST   /api/documents/{document_id}/chunks
GET    /api/documents/{document_id}/chunks
DELETE /api/documents/{document_id}/chunks
```

See `STAGE5_RETRIEVAL_PREPARATION_AND_CHUNKING.md` for the full contract and UI behavior.

## Stage 4.1 role/hierarchy refinement

This package includes the Stage 4.1 correction for title/subtitle/document-metadata classification, title-root-aware heading levels, and explicit question/answer section grouping. See `STAGE4_1_FIX.md` before migrating an existing Stage 4 project.

## Stage 4.2 frontend UX

Stage 4.2 adds a collapsible document sidebar plus page-scoped JSON inspection for Stage 3 and Stage 4. See `STAGE4_2_UX.md`.

## Stage 4.3 — Definitions / glossary reconstruction

Stage 4.3 added the first deterministic definition-list reconstruction baseline. Stage 4.4 supersedes the downstream canonical schema with `1.3` while preserving that logic.


## Stage 4.4 — Complex structure normalization

Stage 4.4 adds robust definition normalization across text/table layouts, conservative cross-page table merging, clause/subclause relationships, appendix containers, figure relations, and footnote repair. See `STAGE4_4_COMPLEX_STRUCTURE.md`.

## Stage 4.5.2 — Correction Sandbox

Manual Stage 4.5 editing is now centralized in **Correction Sandbox**. Structured Document is read-only and can switch between automatic and resolved structure. The sandbox provides visual editing plus **Before JSON**, **After JSON**, and **Correction Log** views for the currently selected page. See `STAGE4_5_2_CORRECTION_SANDBOX.md`.

## Stage 4.4.1 — Cross-page reconciliation

The canonicalizer now uses a multi-signal, term-agnostic cross-page definition reconciliation pass. It can repair next-page continuation fragments that a layout engine mislabels as headings, preserve multi-page `DefinitionEntry` objects, and emit explicit `continues` relationships. See `STAGE4_4_1_CROSS_PAGE_RECONCILIATION.md`.

## Stage 4.5.8.7 — Manual Correction Workbench

The Review workspace now supports a complete auditable correction loop: move/resize, relabel, draw, split, merge, suppress, undo/redo, same-page definition term↔text membership correction, and existing cross-page continuation editing. Automatic Stage 3/4 artifacts remain immutable; only correction operations are saved. See `STAGE4_5_8_7_MANUAL_CORRECTION_WORKBENCH.md`.

## Stage 4.5.8.8 — Multi-selection reliability fix

The Review workspace now keeps modifier-click selections stable for merge/suppress workflows. Selection happens once on pointer-down; Shift/Ctrl/Cmd-click adds or removes a region without also starting a drag. The toolbar shows a live selected-region count and a modifier-key hint. This fixes the case where the second region appeared selected briefly and was immediately deselected by the subsequent click event. Backend behavior and saved correction schema are unchanged.


## Stage 4.5.8.9 — Correction integrity & safety

Stage 4.5 manual correction has been hardened before chunking. This release adds duplicate-ID enforcement, exclusive split text assignment, safe contiguous merge validation, canonical-record reconciliation, conservative reading-order repair, cross-page definition membership, bbox validation, small-region provenance recovery, table safety restrictions, structural-promotion guards, controlled split positioning, pointer-cancel handling, and a closer frontend/backend After preview. See `STAGE4_5_8_9_CORRECTION_INTEGRITY_AND_SAFETY.md` for details.

## Stage 4.5.8.10 — Exact text-span correction

The Review workspace now exposes immutable Stage 3 text spans as a lower-level correction surface. Fresh Stage 3 extraction uses schema `1.1` with stable line/span IDs, canonical Stage 4 uses schema `1.5` with line/span provenance, and correction artifacts use schema `1.4` with the new `span_rebuild` operation. Partial span corrections are lossless: unselected source spans are preserved automatically and the backend rejects any operation that would silently drop text. See `STAGE4_5_8_10_TEXT_SPAN_CORRECTION.md`.


## Stage 4.5.8.12 — Relationship semantic validation & approval

Historical patch. It introduced semantic validation, stable issue IDs, and explicit relationship approval. **4.5.8.16.2 supersedes the approval gate:** warnings remain diagnostic, but Stage 5 readiness now depends only on blocking structural-integrity errors. Relationship provenance validation remains in place.

See `STAGE4_5_8_12_RELATIONSHIP_SEMANTIC_VALIDATION_AND_APPROVAL.md`.


## Stage 4.5.8.13 — Relation model corrections

Relation validation now avoids false sibling-marker errors for parent-less subclauses, treats normalized definition source-table IDs as provenance rather than live canonical foreign keys, inherits definition section/context across manual links and obvious sequential drawn rows, downgrades page-boundary duplicate clauses to explicit continuation review candidates, and separates automatic Stage 4 baseline issues from correction-introduced issues in the Review UI. Correction artifacts use schema `1.7`; resolved Stage 4.5 uses schema `1.3`. See `STAGE4_5_8_13_RELATION_MODEL_CORRECTIONS.md`.

## Stage 4.5.8.14 — relation hierarchy compatibility

Historical patch. It added automatic compatibility repair for flattened legal hierarchy. **4.5.8.16 supersedes that correction behavior:** Stage 4.5 no longer guesses missing clause/subclause parents. Existing hierarchy is preserved unless the reviewer explicitly changes it. Legacy definition-provenance normalization remains supported.

See `STAGE4_5_8_14_RELATION_HIERARCHY_COMPATIBILITY.md`.

## Stage 4.5.8.15 — definition membership completion & precise provenance

Historical patch. It added precise recovered-definition provenance and automatic/manual definition-membership completion. **4.5.8.16 keeps the provenance improvements but removes automatic manual-definition guessing.** Definition text is now assigned explicitly through a contextual DefinitionEntry selector.

See `STAGE4_5_8_15_DEFINITION_MEMBERSHIP_AND_PROVENANCE.md`.

## Stage 4.5.8.16 — simplified correction workflow

The active Review UI now exposes only **Element correction** and **Exact text spans**. Dedicated structured-semantics, definition-link, and free-form cross-page relationship editors are removed from the primary workflow. When selected elements are `definition_text`, a contextual **Belongs to definition** selector appears; one bulk `assign_definition` operation can assign the entire selection to an existing DefinitionEntry. The backend derives section membership and rebuilds canonical DefinitionEntry/SectionRecord back-references. Stage 4.5 no longer auto-guesses definition membership or legal hierarchy parents. Legacy correction operations remain replayable for compatibility. Correction artifacts use schema `1.9`.

See `STAGE4_5_8_16_SIMPLIFIED_CORRECTION.md`.

## Stage 4.5.8.16.1 — frontend compile fix

Fixes six `TS2304` errors caused by stale calls to `setCrossPageSource` and `setDefinitionTermSource` after those legacy UI states were removed in the simplified correction workflow. No backend schema or correction semantics changed. See `STAGE4_5_8_16_1_FRONTEND_COMPILE_FIX.md`.


## Stage 4.5.8.16.2 — simplified structure status & automatic Stage 5 readiness

The large Canonical Relationship Integrity / Stage 5 approval panel has been removed from the active correction workflow. Reviewers now see only a compact **structure status** (`VALID`, `NEEDS FIX`, or `PENDING`) beside the correction controls. Saving still performs the same blocking integrity validation internally. Semantic warnings remain available in the resolved JSON as diagnostics but do not block Stage 5.

Explicit relationship approval is no longer required. `review.stage5_eligible` is automatically `true` whenever the resolved structure has zero blocking integrity errors. The legacy approval endpoint remains backend-only for compatibility with older clients. Resolved Stage 4.5 artifacts use schema `1.5`; frontend package version is `0.4.5-8.16.2`.

See `STAGE4_5_8_16_2_SIMPLIFIED_STATUS_GATE.md`.

## Stage 4.5.8.16.2.1

Frontend compile cleanup: removed stale `setApprovedIssueIds` calls after relationship approval state removal.

## Stage 4.5.8.16.3 — relation placement

The DefinitionEntry selector now appears as part of the selected corrected-region workflow instead of above it. Single-element relationship correction is integrated into the selected-region card; multi-selection keeps a compact bulk relation control directly below that area. Backend behavior is unchanged.

## Stage 4.5.8.16.4 — selection state reliability

Semantic relabeling and other in-place corrections now preserve the selected corrected region instead of allowing the editor to disappear during a working-element rebuild. Resolved-artifact refreshes no longer wipe an active unsaved correction session, operation accumulation uses an authoritative ref to avoid stale state, and definition membership is cleared on real semantic type changes so the explicit relation selector remains the source of truth. Frontend package version is `0.4.5-8.16.4`.

See `STAGE4_5_8_16_4_SELECTION_STATE_RELIABILITY.md`.

## Stage 4.5.8.16.5

Fixes the first-interaction selection race in the Correction Sandbox. The selected-region editor is no longer cleared by a late Stage 4 timestamp refresh; document/page changes remain the only hard-reset triggers.


## Latest patch

Stage 4.5.8.16.5.1 prevents the page-number input blur from re-committing the current page and clearing the first selected corrected region. See `STAGE4_5_8_16_5_1_PAGE_NAV_BLUR_SELECTION_FIX.md`.

## Stage 4.6 — Semantic reconstruction v2

Stage 4.6 introduces a dedicated deterministic semantic layer under `backend/app/services/semantic/`. PyMuPDF4LLM box classes are retained as `layout_role` evidence, while ambiguous structural roles are resolved from reusable element features plus neighboring sequence context. Canonical schema `1.8` adds `group_header` and per-element classification audit metadata (`selected_type`, confidence, evidence, alternatives). The old isolated `(a) => subclause` promotion path is no longer active. Local list/group dependencies use `introduces` so ClauseRecord-backed `parent_of` integrity remains strict. The Review inspector shows the automatic classification and evidence for the selected region. See `STAGE4_6_SEMANTIC_V2_ARCHITECTURE.md` and `STAGE4_6_1_SEMANTIC_TAXONOMY.md`.

## Stage 4.6.2 — Semantic v2.1 scope and continuation

Semantic v2.1 adds parallel local-group propagation, conservative heading-scope resolution, semantic vetoes for false cross-page continuation into fresh numbered clauses, normalized classification alternatives, hierarchy-aware confidence calibration, and stronger advisory semantic validation. Stage 5 code is unchanged. See `STAGE4_6_2_SEMANTIC_V2_1_SCOPE_AND_CONTINUATION.md`.

## Stage 4.7 — Golden structure benchmark

The primary 109-page portfolio PDF now has a machine-readable Stage 4 golden specification at `backend/evaluation/golden/sc_aml_cft_stage4_v1.json`. The benchmark uses stable page/text anchors rather than canonical element IDs and currently contains 83 checks (77 required, 6 advisory) across element semantics, relationships, definitions, appendices, logical tables and figures. `scripts/validate_stage4_golden_spec.py` validates the benchmark against the exact PDF SHA/page count/text anchors, while `scripts/evaluate_stage4_golden.py` scores a generated `StructuredDocument`. See `STAGE4_7_GOLDEN_STRUCTURE_SPECIFICATION.md`.
