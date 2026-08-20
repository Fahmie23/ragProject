# Stage 4.3 — Definition / Glossary Reconstruction

This patch fixes the structure failure exposed by `sc_aml_cft.pdf` on the Definitions page.

## Problem observed

The layout engine correctly found text regions, but the canonical layer interpreted a two-column definition list as ordinary headings and paragraphs:

- `3.DEFINITIONS` was structurally useful but missing numbering whitespace.
- `3.1Unless ...` was emitted as a generic list item.
- `AML/CFT/CPF` was incorrectly promoted to a subsection heading.
- `beneficial owner` was treated as an ordinary paragraph.
- `beneficiary`, because it appeared near the bottom of the page, was incorrectly left as a page footer.
- Definition paragraphs were not grouped with their term.
- A definition beginning at the bottom of one page could not be represented as continuing onto the next page.

## Stage 4.3 pipeline

```text
PyMuPDF4LLM layout boxes
        ↓
Document role refinement
        ↓
Structural numbering normalization
        ↓
Heading hierarchy
        ↓
Numbered-clause refinement
        ↓
Definition-context detection
        ↓
Two-column term/definition reconstruction
        ↓
Conservative cross-page continuation
        ↓
Section assignment
        ↓
DefinitionEntry records
        ↓
Canonical JSON schema 1.2
```

## New canonical element types

- `clause`
- `definition_term`
- `definition_text`

A definition term and its text retain the original layout class in `source.layout_box_class`, so a repaired false `page-footer` remains auditable.

## DefinitionEntry

The structured document now contains a top-level `definitions` array:

```json
{
  "definition_id": "def-2",
  "term": "beneficial owner",
  "section_id": "sec-11",
  "term_element_id": "p9-e5",
  "definition_element_ids": ["p9-e6", "p9-e7", "p9-e8", "p9-e9"],
  "start_page": 9,
  "end_page": 9,
  "spans_multiple_pages": false,
  "continues_to_next_page": false
}
```

## How definition detection works

It is not hard-coded for AML/CFT terms. A definition list is considered only while the document is inside a Definitions/Glossary/Interpretation-like section. Within that context the canonicalizer looks for:

1. a short label in the left portion of the page;
2. a substantial text region to its right;
3. strong vertical row alignment;
4. repeated term/definition geometry where present.

Right-column blocks between one term row and the next are grouped into the same definition entry.

## False footer repair

An item classified by the vendor as `page-footer` is only repaired when it also satisfies the definition-term geometry inside a definition context. The actual numeric page footer remains `page_footer`.

## Numbered clauses

Text such as:

```text
3.1Unless otherwise defined ...
```

becomes:

```text
3.1 Unless otherwise defined ...
```

and is represented as:

```json
{
  "type": "clause",
  "clause_number": "3.1"
}
```

It does not become a fake subsection.

## Cross-page continuation

If the last definition text on a page:

- ends near the bottom of the page,
- has no terminal punctuation, and
- the next page remains inside the same definition context,

right-column prose before the next definition term is conservatively attached to the previous `DefinitionEntry`.

This produces `spans_multiple_pages: true` when the continuation is actually attached. If the text still appears incomplete at the end of the available page, `continues_to_next_page` remains `true`.

## Frontend changes

The Structured Document view now supports filters and overlays for:

- Clause
- Definition term
- Definition text

The page-level Stage 4 JSON also contains `definitions_referenced_on_page`, so the selected page can be sent for debugging without exporting the whole document.

## Apply to an existing project

Back up first:

```bash
cd ~
cp -a ragProject ragProject_before_stage4_3
```

Copy these patch files into the same relative paths in `~/ragProject`:

```text
backend/app/schemas.py
backend/app/services/canonical.py
backend/tests/test_stage4_canonical.py
frontend/src/types.ts
frontend/src/App.tsx
frontend/src/styles.css
```

No new dependency is required.

Run backend tests:

```bash
cd ~/ragProject/backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Expected for this package:

```text
10 passed
```

Then restart FastAPI and rerun **Stage 4 only** on the existing `sc_aml_cft.pdf`. Stage 3 does not need to be rerun because the raw extraction is not the issue.

## Expected result for the page you showed

Conceptually:

```text
H2  3. DEFINITIONS
    Clause 3.1  Unless otherwise defined ...

    Definition: AML/CFT/CPF
      └─ means Anti-Money Laundering ...

    Definition: beneficial owner
      ├─ in the context of legal person ...
      ├─ Reference to “ultimately owns or controls” ...
      ├─ in the context of legal arrangements ...
      └─ Reference to “ultimate effective control” ...

    Definition: beneficiary
      └─ the meaning of the term beneficiary depends on ...
         [can continue on the next page]
```

The numeric page number should remain a `page_footer` and should not appear in body text.
