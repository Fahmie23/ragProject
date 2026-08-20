# Stage 4.5 — Human-in-the-Loop Layout Correction

Stage 4.5 is a review layer between automatic structure reconstruction (Stage 4) and future chunking (Stage 5).

It is intentionally **non-destructive**:

```text
Stage 3 raw extraction                 data/extracted/
          │
          ▼
Stage 4 automatic structure            data/structured/
          │
          ├──────────────┐
          │              │
          ▼              ▼
manual correction log   immutable Stage 4 remains available
 data/corrections/
          │
          ▼
resolved canonical structure           data/resolved/
          │
          ▼
Stage 5 later reads resolved output when it exists
```

The original Stage 3 extraction and automatic Stage 4 JSON are never overwritten by a manual edit.

## Why Stage 4.5 exists

Page-layout engines can make locally incorrect decisions even when the page is otherwise extracted well. Examples include:

- one box contains both a page header and a figure caption;
- a caption is labelled as a paragraph;
- two adjacent caption boxes should be one box;
- a valid region is missing;
- a false-positive box should be ignored;
- a box has the right semantic type but slightly wrong coordinates.

Stage 4.5 lets the reviewer repair those local mistakes without editing the PDF or Stage 3 text manually.

## Supported correction operations

The first version supports six operations:

1. **Move / resize** — drag a selected region or use the numeric x0/y0/x1/y1 inputs.
2. **Relabel** — change the semantic type, for example `page_header` → `caption`.
3. **Split** — split one region horizontally into two regions.
4. **Merge** — merge two or more selected regions into one region.
5. **Draw** — create a missing region by drawing a new bounding box.
6. **Delete** — remove a false-positive canonical element from the resolved structure.

The frontend also provides **Undo**, **Redo**, **Reset page**, and **Reset all** controls.

## Text is reconstructed from Stage 3

A reviewer changes geometry and semantic roles, not the document text.

For move/resize, split, merge, and draw operations, the backend finds Stage 3 spans that intersect the corrected bounding box and reconstructs text in coordinate order:

```text
corrected bbox
     │
     ▼
Stage 3 spans inside/intersecting bbox
     │
     ▼
sort by line position + x position
     │
     ▼
resolved element text
```

This is important for provenance: a user does not need to retype a caption after splitting it out of a header.

## Example: header and caption extracted as one region

Automatic Stage 4:

```text
┌──────────────────────────────────────┐
│ Securities Commission Malaysia      │
│ Figure 2: Risk-Based Approach        │
└──────────────────────────────────────┘
page_header
```

In Stage 4.5:

1. Select the box.
2. Click **Split horizontal**.
3. Adjust the split boxes if required.
4. Select the lower result and relabel it to `caption`.
5. Save corrections.

Resolved output:

```text
┌──────────────────────────────────────┐
│ Securities Commission Malaysia      │  page_header
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ Figure 2: Risk-Based Approach        │  caption
└──────────────────────────────────────┘
```

The automatic Stage 4 artifact remains unchanged and the manual operations are stored separately.

## Page navigation

The page toolbar now supports direct page-number entry:

```text
←   Page [ 85 ] / 118   →
```

You may:

- type a page number and press **Enter**;
- type a page number and click elsewhere;
- continue using the previous/next arrows for adjacent pages.

Values are clamped to the valid range `1..page_count`.

The selected page is still shared between the Stage 3 and Stage 4/4.5 workspaces.

## Backend storage

Two new directories are used:

```text
backend/data/
├── structured/     # automatic Stage 4 canonical JSON
├── corrections/    # Stage 4.5 operation log
└── resolved/       # automatic Stage 4 + saved human corrections
```

### Correction artifact

Example:

```json
{
  "schema_version": "1.0",
  "document_id": "...",
  "source_sha256": "...",
  "base_structure_schema_version": "1.3",
  "base_structured_at": "...",
  "operations": [
    {
      "operation_id": "op-...",
      "operation": "split",
      "page_number": 12,
      "source_element_ids": ["p12-e3"],
      "result_elements": [
        {
          "element_id": "manual-p12-...-a",
          "type": "page_header",
          "bbox": [70, 40, 530, 70]
        },
        {
          "element_id": "manual-p12-...-b",
          "type": "caption",
          "bbox": [70, 70, 530, 110]
        }
      ]
    }
  ]
}
```

### Resolved artifact

`data/resolved/{document_id}.json` contains the complete corrected canonical document plus correction provenance. This is the preferred input for Stage 5 when it exists.

## API endpoints

Stage 4.5 adds:

```text
GET    /api/documents/{document_id}/corrections
PUT    /api/documents/{document_id}/corrections
DELETE /api/documents/{document_id}/corrections
GET    /api/documents/{document_id}/resolved-structure
```

`PUT /corrections` requires the `base_structured_at` timestamp returned by the automatic Stage 4 artifact. If Stage 4 changed while the user was editing, the API returns HTTP 409 rather than applying stale corrections to a different structure.

## Invalidation rules

Manual corrections depend on Stage 4, which depends on Stage 3.

Therefore:

```text
rerun Stage 3
    ↓
invalidate Stage 4 + Stage 4.5

rerun Stage 4
    ↓
invalidate old Stage 4.5 corrections + resolved output
```

This prevents a correction such as `p12-e3 → caption` from silently being applied to a newly generated structure where `p12-e3` may mean something different.

When Stage 5 is added, saving or resetting Stage 4.5 corrections must invalidate Stage 5+ artifacts.

## Frontend workflow

```text
Structured document
      ↓
Edit layout
      ↓
select / draw region
      ↓
move · resize · relabel · split · merge · delete
      ↓
review unsaved operations
      ↓
Save corrections
      ↓
resolved canonical structure
```

The Stage 4 inspector includes a **Corrections** subview so saved and unsaved page operations can be inspected directly.

The full **JSON artifacts** view includes:

- Resolved Stage 4.5
- Correction log
- Automatic Stage 4
- Layout engine JSON
- Stage 3 JSON

## Current v1 boundaries

Stage 4.5 is deliberately a **page-region correction layer**, not a second document-understanding engine.

- It can correct bounding boxes and semantic element types.
- It can recover corrected text from Stage 3 spans.
- It reconciles/prunes automatic higher-order records when their source elements no longer exist or no longer have compatible roles.
- It does **not** automatically rebuild a brand-new section hierarchy, definition list, logical table grid, or figure relationship graph from arbitrary manual edits.
- A newly drawn `table` region does not parse a new table cell grid; table parsing remains an automatic structure task.
- The first split tool is horizontal; a future version can add arbitrary split lines if real documents require it.

These boundaries keep human edits auditable and deterministic. If repeated manual corrections reveal a systematic parser failure, that failure should be fixed in Stage 4 automation rather than hidden behind manual edits.

## Tests

Stage 4.5 adds tests for:

- splitting one automatic header into header + caption;
- rebuilding split text from Stage 3 spans;
- sequential move/resize + relabel operations;
- API persistence of correction and resolved artifacts;
- invalidating Stage 4.5 when Stage 4 is rerun.

The complete backend suite currently contains **21 passing tests**.

## Apply to an existing Stage 4.4 project

Back up your project first:

```bash
cd ~
cp -a ragProject ragProject_before_stage4_5
```

Copy the matching files from the Stage 4.5 patch into `~/ragProject/`.

Then run:

```bash
cd ~/ragProject/backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
uvicorn app.main:app --reload
```

Expected test result:

```text
21 passed
```

For the frontend:

```bash
cd ~/ragProject/frontend
npm install
npm run dev
```

No Stage 3 re-extraction is required merely to install Stage 4.5. Existing Stage 3 and automatic Stage 4 artifacts can be reviewed directly.
