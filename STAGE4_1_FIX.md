# Stage 4.1 — Document Role & Hierarchy Fix

This patch fixes the Stage 4 issue where a document title, subtitle, issued/revised line, and numbered FAQ questions could all be rendered as H1 section headers.

## What changed

1. **Document-level role refinement** happens before heading-level inference.
   - First-page title candidates are detected conservatively from layout labels + position/alignment.
   - A nearby secondary centered heading can become `subtitle`.
   - Issued/revised/effective/version lines become `document_metadata`.
   - The original PyMuPDF4LLM box class is still preserved in `source.layout_box_class`.

2. **Heading hierarchy now has a document-title root.**
   - When a real title element exists, it occupies H1.
   - TOC level 1 / numbering depth 1 therefore becomes H2.
   - `2.3 Methods` becomes H3 when the title root exists.
   - If there is no real title element, top-level sections still start at H1.

3. **Question/answer grouping is explicit.**
   - A section ending in `?` is recorded as `kind: "question"`.
   - Following paragraphs/tables/etc. receive that section's `section_id`.
   - Each `SectionRecord` stores `content_element_ids`.

4. **Metadata stays traceable but is excluded from `body_text`.**
   - This prevents issued/revised/version text from polluting later chunks.

5. **Canonical schema version is now `1.1`.**

## Expected FAQ result

```text
H1  FREQUENTLY ASKED QUESTIONS
     Subtitle: LICENSING HANDBOOK
     Metadata: (Issued: 14 April 2023; Revised: 1 October 2024)

H2  1. Why did the SC revise the Licensing Handbook?
    └── answer paragraph

H2  2. ...?
    └── answer paragraph
```

## Files changed

Backend:
- `backend/app/schemas.py`
- `backend/app/services/canonical.py`
- `backend/tests/test_stage4_canonical.py`

Frontend:
- `frontend/src/types.ts`
- `frontend/src/App.tsx`
- `frontend/src/styles.css`

## Apply to your current project

Back up first:

```bash
cd ~
cp -a ragProject ragProject_before_stage4_1
```

Copy the changed files from the patch package into the same locations in `~/ragProject`.

Then test the backend:

```bash
cd ~/ragProject/backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Expected for this package:

```text
8 passed
```

Restart FastAPI if needed:

```bash
uvicorn app.main:app --reload
```

For the frontend:

```bash
cd ~/ragProject/frontend
npm run dev
```

## Important: regenerate Stage 4

Your existing `structured/<document_id>.json` was created by the old hierarchy logic. After applying this patch, **run Stage 4 again for the same PDF**. You do not need to rerun Stage 3 unless you also changed extraction.

Then verify:

- `FREQUENTLY ASKED QUESTIONS` → document title / H1 root
- `LICENSING HANDBOOK` → subtitle
- issued/revised line → document metadata
- numbered questions → H2 siblings
- answers → same `section_id` as their question
- page number/footer → excluded from body text
