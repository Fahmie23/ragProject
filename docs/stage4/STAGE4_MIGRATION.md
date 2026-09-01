# Stage 4 Migration Guide

This package extends the Stage 3 project with **Stage 4: Layout & Structure Reconstruction**.

It preserves the existing Stage 1–3 architecture and adds two new persisted artifacts:

```text
backend/data/
├── raw/          # Stage 1 source files
├── metadata/     # Pipeline status / deterministic metadata
├── extracted/    # Stage 3 raw PyMuPDF extraction
├── layout/       # Stage 4 raw PyMuPDF4LLM Layout output
└── structured/   # Stage 4 canonical document JSON
```

## 1. Back up the current project

From WSL:

```bash
cd ~
cp -a ragProject ragProject_stage3_backup
```

Do not delete your current `backend/data` folder.

## 2. Copy the Stage 4 source over the project

Extract the Stage 4 archive somewhere temporary, then copy the source while preserving your current data.

Example:

```bash
rsync -av \
  --exclude 'backend/data/raw/*' \
  --exclude 'backend/data/metadata/*' \
  --exclude 'backend/data/extracted/*' \
  rag_document_pipeline_stage4/ ~/ragProject/
```

The new `layout/` and `structured/` folders will be created automatically by the backend if they do not exist.

## 3. Update backend dependencies

```bash
cd ~/ragProject/backend
source .venv/bin/activate
pip install -r requirements.txt
```

Stage 4 adds:

```text
pymupdf4llm==1.28.0
```

Do **not** install `pymupdf-layout` separately. Current PyMuPDF4LLM installs and activates the compatible Layout package automatically.

## 4. Run all backend tests

```bash
cd ~/ragProject/backend
source .venv/bin/activate
pytest -q
```

Expected for this package:

```text
7 passed
```

## 5. Start the backend

```bash
uvicorn app.main:app --reload
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## 6. Update/start the frontend

```bash
cd ~/ragProject/frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## 7. Correct testing order

Use one normal digital PDF first.

```text
Upload
  ↓
Stage 1 Intake
  ↓
Stage 2 Validation
  ↓
Run Stage 3
  ↓
Inspect Raw extraction
  ↓
Run Stage 4
  ↓
Inspect Structured document
  ↓
Compare canonical output with the original PDF
```

Check these Stage 4 outputs carefully:

- Page reading order
- `title`
- `section_header`
- `paragraph`
- `list_item`
- `table`
- `figure`
- `caption`
- `page_header`
- `page_footer`
- `footnote`
- `formula`
- section hierarchy
- headers/footers excluded from canonical body text
- table cells preserved
- source trace points back to Stage 3 blocks

## 8. New endpoints

```text
POST /api/documents/{document_id}/structure
GET  /api/documents/{document_id}/structure
GET  /api/documents/{document_id}/layout
```

### `/layout`

Raw vendor-level PyMuPDF4LLM Layout result. Keep this for debugging.

### `/structure`

Our stable canonical schema. Downstream Stage 5 chunking should consume **this artifact**, not the vendor-specific Layout JSON.

## 9. Important Stage 4 behavior

Stage 4 deliberately calls PyMuPDF4LLM with OCR disabled:

```text
use_ocr = false
```

This prevents Stage 4 from silently changing the text source established in Stage 3.

For scanned/mixed documents, Stage 4 may still classify visual regions, but image-only text may remain unavailable. OCR should be introduced explicitly as a separate controlled branch rather than hidden inside structure reconstruction.

## 10. Re-running Stage 3

A new Stage 3 extraction changes the input to Stage 4. Therefore this implementation automatically deletes any existing:

```text
layout/{document_id}.json
structured/{document_id}.json
```

and resets:

```text
structure_status = not_started
```

This prevents stale Stage 4 results from being served after Stage 3 changes.
