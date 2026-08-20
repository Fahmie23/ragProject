# RAG Document Pipeline — Stages 1–4.5

A portfolio-oriented RAG ingestion pipeline that makes each document-processing stage inspectable before chunking or embeddings.

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
5. Chunking (not implemented yet)
```

## Stage 4 design

Stage 4 does two separate things:

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
             Canonical normalizer
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

Stage 4.4 also creates document-level logical records for definitions, clauses, appendices, cross-page tables, figures, and structural relationships. The canonical schema is `1.3`.

PyMuPDF4LLM Layout currently exposes corresponding page box classes such as `text`, `picture`, `table`, `caption`, `title`, `section-header`, `page-header`, `page-footer`, `list-item`, `footnote`, and `formula`.

## Hierarchy evidence

For `section_header` elements, heading level is determined conservatively in this order:

1. PDF bookmark / TOC match
2. Explicit heading numbering such as `2.3.1`
3. Dominant font-size rank from Stage 3 spans
4. Unknown when no evidence exists

The selected source is persisted as:

```json
{
  "heading_level": 2,
  "heading_level_source": "pdf_toc"
}
```

No artificial confidence score is generated.

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

Stage 4.5 adds a non-destructive human correction layer before chunking. The reviewer can move/resize, relabel, split, merge, draw, or delete page regions. Corrections are persisted independently of automatic Stage 4:

```text
data/structured/{document_id}.json   automatic Stage 4
data/corrections/{document_id}.json  manual operation log
data/resolved/{document_id}.json     automatic + manual corrections
```

For geometry-changing operations, corrected text is rebuilt from immutable Stage 3 spans inside the edited bounding box. If Stage 3 or Stage 4 is rerun, Stage 4.5 artifacts are invalidated rather than silently applied to stale element IDs.

The page navigator also accepts direct numeric input (`Page [85] / 118`) in addition to previous/next arrows.

See `STAGE4_5_HUMAN_REVIEW.md` for the correction model, API contract, workflow, and current v1 boundaries.

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
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

Stage 5 should consume `structured/{document_id}.json`, not raw PyMuPDF or vendor Layout output.

## Stage 4.1 role/hierarchy refinement

This package includes the Stage 4.1 correction for title/subtitle/document-metadata classification, title-root-aware heading levels, and explicit question/answer section grouping. See `STAGE4_1_FIX.md` before migrating an existing Stage 4 project.

## Stage 4.2 frontend UX

Stage 4.2 adds a collapsible document sidebar plus page-scoped JSON inspection for Stage 3 and Stage 4. See `STAGE4_2_UX.md`.

## Stage 4.3 — Definitions / glossary reconstruction

Stage 4.3 added the first deterministic definition-list reconstruction baseline. Stage 4.4 supersedes the downstream canonical schema with `1.3` while preserving that logic.


## Stage 4.4 — Complex structure normalization

Stage 4.4 adds robust definition normalization across text/table layouts, conservative cross-page table merging, clause/subclause relationships, appendix containers, figure relations, and footnote repair. See `STAGE4_4_COMPLEX_STRUCTURE.md`.
