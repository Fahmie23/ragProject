# Stage 4.4 — Complex Structure Normalization

Stage 4.4 makes the canonical layer resilient to the complex layouts we found in the test documents: glossary pages, multipage tables, legal clauses, appendices, figures/illustrations, and footnotes.

The key rule is unchanged:

```text
Stage 3 = factual/raw extraction
Stage 4 = deterministic semantic reconstruction
Stage 5 = chunking (not started)
```

Stage 4.4 does **not** add OCR, LLM classification, embeddings, retrieval, or chunking.

## Processing order

```text
PyMuPDF4LLM Layout boxes
        ↓
Document role refinement
        ↓
Structural text normalization
        ↓
Figure-adjacent heading refinement
        ↓
Heading-level evidence
        ↓
Clause / subclause refinement
        ↓
Definition-list normalization
        ↓
Footnote repair
        ↓
Section hierarchy
        ↓
Document-level records
  ├─ definitions
  ├─ clauses
  ├─ appendices
  ├─ logical tables
  ├─ figures
  └─ relationships
        ↓
Canonical JSON schema 1.3
```

---

## 1. Robust definition-list normalization

A glossary may be represented by the layout engine in different ways:

```text
A. left-column term + right-column text boxes
B. a detected two-column table
C. mixed text/table layout across adjacent pages
```

Stage 4.4 normalizes A and B into the same `DefinitionEntry` model.

A detected table is considered definition-like only when:

- it is inside an active Definitions / Glossary / Interpretation context;
- it has at least two columns;
- most non-empty rows contain a short term in the first column and substantive definition text to the right;
- obvious header rows such as `Term | Definition` are ignored.

Definition records expose:

```json
{
  "definition_id": "def-7",
  "term": "digital asset",
  "source_kind": "table_rows",
  "definition_text": "refers collectively to a digital currency and digital token.",
  "items": [],
  "start_page": 10,
  "end_page": 10
}
```

Nested definition items such as `(a)`, `(b)`, `(c)` are retained as `items` when they occur inside a definition.

Text-column definitions can still continue across a page break. The continuation is attached to the existing definition until a new definition term or definition-like table begins.

---

## 2. Cross-page logical tables

Page-level table elements remain untouched for traceability. Stage 4.4 additionally creates a **logical table** that can span multiple pages.

A page N table and page N+1 table are merged only when there is strong deterministic evidence:

```text
previous fragment approaches page bottom
+
next fragment begins near page top
+
same column count
+
compatible left/right x boundaries
+
compatible section / appendix context
+
no substantive body content appears before the next fragment
```

For the table that starts on page 85 and continues on page 86, the canonical result should be conceptually:

```json
{
  "logical_table_id": "table-12",
  "fragment_element_ids": ["p85-e4", "p86-e1"],
  "start_page": 85,
  "end_page": 86,
  "spans_multiple_pages": true,
  "merge_source": "cross_page_geometry"
}
```

A `continues` relationship links the two page fragments.

If a continuation page repeats the same header row, the merged logical table keeps that header only once.

The merge is intentionally conservative: if a new paragraph/heading appears before the page-N+1 table, the tables remain separate.

---

## 3. Clause / subclause hierarchy

Legal or procedural numbering is represented separately from section headings.

Examples:

```text
2.5 ...   -> clause
3.1 ...   -> clause
1. ...    -> clause when it is prose, not a question heading
(a) ...   -> subclause
(b) ...   -> subclause
```

A subclause receives `parent_clause_id`, and a `parent_of` relationship links the numbered clause to the subclause.

FAQ questions that the layout engine already identified as section headers remain question sections rather than becoming clauses.

---

## 4. Appendix containers

Headers matching `APPENDIX C`, `APPENDIX D`, etc. create `AppendixRecord` objects.

The appendix stores:

- label;
- optional immediately following appendix title;
- start page;
- end page.

Membership is assigned using **document-order boundaries**, not the entire first page. This matters if an appendix begins halfway down a page: content appearing before the appendix label is not incorrectly assigned to the appendix.

Canonical elements inside the appendix receive `appendix_id`.

---

## 5. Figures / illustrations and relationships

The visual region remains a canonical `figure` element. Stage 4.4 adds deterministic relations around it:

```text
paragraph -> introduces -> figure
caption   -> caption_of -> figure
paragraph -> explains   -> figure
reference -> source_for -> figure
```

A sentence such as `The steps above are illustrated in the diagram below:` can be demoted from a false section heading to normal paragraph content when it sits directly above a figure.

Figure explanation grouping is conservative. When a new numbered clause/subclause or section begins after the figure, explanation grouping stops so normal document content is not swallowed into the figure.

No vision model is used yet; Stage 4 records the figure, its coordinates, its surrounding explanatory context, and provenance only.

---

## 6. Footnote versus footer repair

Long, small-font footer-like regions with a footnote marker can be reclassified as `footnote`.

Numeric page numbers remain `page_footer`.

Definition-list geometry is applied before the footer repair, so a glossary term near the page bottom can still be repaired into a `definition_term` when the left/right definition pattern strongly supports it.

---

## 7. Generic structural relationships

Schema 1.3 supports:

```text
parent_of
continues
introduces
explains
caption_of
source_for
belongs_to
```

This prevents Stage 4 from becoming a collection of unrelated one-off fields. Downstream stages can inspect the same relationship model regardless of whether the content is a clause, table, figure, or appendix.

---

## Canonical schema additions

Top-level collections:

```text
definitions
clauses
appendices
tables
figures
relationships
```

Page-element fields include:

```text
clause_id
parent_clause_id
subclause_marker
logical_table_id
figure_id
appendix_id
```

Canonical schema version:

```text
1.3
```

---

## Frontend

The Stage 4 overview now shows counts for:

```text
sections
clauses
definitions
appendices
logical tables
figures
relationships
```

Stage 4 page-level JSON contains only records relevant to the selected page:

```text
sections_referenced_on_page
definitions_referenced_on_page
clauses_referenced_on_page
appendices_referenced_on_page
logical_tables_referenced_on_page
figures_referenced_on_page
relationships_referenced_on_page
page
```

For a page that belongs to a multipage table, the page JSON includes the logical table record covering the full page range. This makes page 85 or page 86 sufficient for debugging the merged table.

---

## Tests

Run:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Expected:

```text
18 passed
```

The Stage 4 suite now covers:

- FAQ title/subtitle/metadata and question-answer grouping;
- heading evidence and structural-number normalization;
- text-column definition reconstruction;
- table-backed definition reconstruction;
- nested `(a)/(b)/(c)` definition items;
- cross-page definition continuation;
- false-footer definition-term repair;
- cross-page table merge;
- repeated table-header deduplication;
- negative table-merge case when new content appears first;
- clause/subclause parent-child relationships;
- appendix detection and document-order membership;
- figure introduction/explanation/source relationships;
- prevention of figure explanations swallowing a following numbered clause;
- footnote versus page-footer repair.

---

## Migration from Stage 4.3

Stage 1–3 data does not need to be regenerated.

1. Back up the current project.
2. Replace the changed Stage 4 backend/frontend files.
3. Install requirements only if needed.
4. Run the tests.
5. Restart FastAPI and Vite.
6. Re-run **Stage 4 only** for existing documents.

Old schema 1.2 structured JSON should be regenerated as schema 1.3.

Do **not** start Stage 5 until the real documents have been visually/JSON-checked for the complex structures above.
