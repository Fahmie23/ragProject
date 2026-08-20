# Stage 4.5.1 — JSON Preview Sandbox & Correction JSON Visibility

This is a frontend-only extension to Stage 4.5. It does **not** change Stage 3 extraction, automatic Stage 4 canonicalization, the correction schema, or backend persistence.

## Why this exists

Page-level JSON is already useful for debugging, but reading JSON alone does not tell a reviewer whether the coordinates and semantic types actually line up with the original page. The JSON Preview Sandbox closes that loop:

```text
real PDF page
    +
editable page JSON
    ↓
visual bounding-box preview
    ↓
baseline comparison
```

It is intentionally a sandbox. Editing JSON here cannot overwrite the automatic structure or saved Stage 4.5 corrections.

## New workspace tab

A new **JSON Preview** tab appears alongside:

```text
Overview
Raw extraction
Structured document
JSON Preview
JSON artifacts
```

The selected page is global, so Page 85 remains Page 85 when moving between Raw extraction, Structured document, and JSON Preview.

## Direct page navigation

The shared navigator remains:

```text
←  Page [85] / 118  →
```

Type a page number and press Enter, or click away from the input. Invalid values are clamped to the document range.

## Loading a baseline

The sandbox can load any available page-level artifact:

- **Stage 3 page** — raw blocks, images, tables, coordinates
- **Automatic Stage 4** — canonical elements before human correction
- **Resolved Stage 4.5** — canonical elements after saved corrections

Loading a baseline does four things:

1. fills the editor with that page JSON;
2. validates it;
3. renders it over the original PDF page;
4. stores a baseline for comparison.

## Editing and rendering

The left panel is an editable JSON textarea. The reviewer can change, for example:

```json
{
  "element_id": "p12-e3",
  "type": "page_header",
  "bbox": [70, 40, 530, 110]
}
```

to separate or test coordinates in a custom page payload, then click **Validate & render**.

The validator requires:

- a JSON object root;
- a positive `page_number`;
- positive page `width` and `height`;
- either `page.elements` (Stage 4 / 4.5) or `page.blocks` / `page.tables` (Stage 3);
- every renderable bbox to contain four finite numbers.

The sandbox page number must match the globally selected page. This prevents accidentally rendering Page 12 coordinates over Page 13.

## Visual comparison

The preview can show:

- **Baseline** — dashed boxes
- **Sandbox** — solid boxes

A diff summary reports:

```text
unchanged
changed
added
removed
```

Comparison is keyed by `element_id`, `block_id`, or `table_id`, and considers semantic type, bbox, and text.

This is useful for questions such as:

> If I change this `page_header` into `caption` and reduce its bbox, does the resulting region now align with the real caption?

## Correction JSON is now visible at page level

Previously, the Structured Document → **Corrections** inspector primarily showed readable operation cards. The persisted correction JSON already existed in the full JSON artifacts view, but it was not obvious at page level.

The Corrections inspector now has:

```text
Operations | Correction JSON
```

The page-level Correction JSON includes:

```json
{
  "stage": "stage_4_5_page_corrections",
  "document_id": "...",
  "page_number": 12,
  "saved_operations": [],
  "unsaved_operations": [],
  "operation_count": 0
}
```

It can be copied or downloaded just like the Stage 3 and Stage 4 page JSON.

The **full persisted** correction artifact remains available under:

```text
JSON artifacts → Corrections
```

## Important separation

```text
JSON Preview
= temporary experimentation only

Stage 4.5 Human Review
= persistent, auditable correction operations
```

The sandbox does not have an "Apply" button in this version. This is deliberate. A future apply workflow should convert sandbox differences into valid Stage 4.5 operations rather than directly replacing canonical JSON.

## Files changed

Frontend only:

```text
frontend/src/App.tsx
frontend/src/styles.css
frontend/package.json
```

No backend files or data schemas changed.

## Verification

Backend regression suite from Stage 4.5 remains unchanged:

```text
21 passed
```

The updated frontend source also passes strict TypeScript source checking. Run the real Vite build in your WSL environment:

```bash
cd ~/ragProject/frontend
npm install
npm run build
npm run dev
```
