# Stage 4.4.1 — General Cross-Page Definition Reconciliation

This update fixes logical definitions that start near the end of one PDF page and continue on the next page.

It is intentionally **not** hard-coded to a term, page number, document, or phrase.

## Why the previous rule failed

The earlier implementation only merged a definition when:

- its final text block was near the bottom of the page,
- the text looked incomplete, and
- the next-page block was already classified as ordinary right-column body text.

In real PDFs, the layout engine can label the first continuation fragment on the next page as a `section-header`. That false heading could also make the document appear to have left the Definitions section too early.

## New processing order

```text
Stage 4 page normalization
        ↓
Definition / glossary context propagation
        ↓
Per-page definition term ↔ text reconstruction
        ↓
Cross-page definition reconciliation
        ↓
DefinitionEntry spanning one or more pages
        ↓
Explicit `continues` relationship
```

## Definition context is more robust

An active Definitions / Glossary context is no longer closed merely because the vendor produced another `section-header`.

The context ends only on stronger evidence, such as:

- a numbered same/higher-level section,
- an appendix boundary,
- or a same/higher-level unnumbered heading positioned in the normal left/central heading region.

A short heading-like fragment deep in the right definition column therefore does not automatically terminate the Definitions section.

## Multi-signal continuation decision

The cross-page reconciler scores evidence from both sides of the page break.

Previous-page signals include:

- last definition fragment near the bottom,
- no later meaningful body element,
- incomplete-looking text,
- established definition-column geometry.

Next-page signals include:

- left edge aligned with the previous definition column,
- horizontal overlap with the expected definition column,
- first candidate near the top of the next page,
- compatible font size,
- no strong structural boundary,
- prose/definition-like text,
- no new definition term before the candidate.

A merge happens only when the evidence passes conservative thresholds.

## Stop conditions

After the first continuation fragment is accepted, later compatible blocks in the same definition column are attached until a boundary such as:

- the next detected definition term,
- a definition table,
- a numbered clause/section,
- a new appendix,
- a strong left/central section heading,
- a title/figure/table boundary.

## Vendor mistakes remain traceable

If the layout engine classified:

```text
"the context."
```

as `section-header`, the canonical layer may resolve it as:

```json
{
  "type": "definition_text",
  "role_source": "cross_page_definition_reconciliation",
  "source": {
    "layout_box_class": "section-header"
  }
}
```

The original vendor class remains available in `source`.

## Explicit relationship

A successful page-break merge creates:

```json
{
  "type": "continues",
  "source_element_id": "p9-e10",
  "target_element_id": "p10-e1",
  "evidence": "cross-page definition continuation score=..."
}
```

The evidence field records the structural signals used by the rule.

## Canonical result

A logical definition can now look like:

```json
{
  "definition_id": "def-14",
  "term": "some term",
  "start_page": 9,
  "end_page": 10,
  "spans_multiple_pages": true,
  "definition_element_ids": [
    "p9-e10",
    "p10-e1",
    "p10-e2",
    "p10-e3"
  ],
  "definition_text": "..."
}
```

The individual page elements remain separate for provenance and visual debugging.

## Frontend

The Structured Document view now surfaces cross-page definitions with compact navigation controls:

```text
some term continues to page 10 →
```

and on the continuation page:

```text
← some term continued from page 9
```

The buttons jump directly between the page fragments.

Page-level JSON already includes both `definitions_referenced_on_page` and `relationships_referenced_on_page`, so the exact continuation is inspectable in JSON.

## Tests

The backend suite now contains 24 passing tests.

New tests cover:

1. next-page continuation misclassified as a section header,
2. multiple continuation blocks until the next term,
3. explicit `continues` relationship,
4. genuine new numbered section prevents a merge,
5. unrelated glossary vocabulary to prove the algorithm is term-agnostic.

## Migration

No Stage 3 rerun is required.

After applying the patch:

```bash
cd ~/ragProject/backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Expected:

```text
24 passed
```

Then rerun **Stage 4** for the affected document so the canonical structure and relationships are regenerated.

Any Stage 4.5 corrections based on the old Stage 4 output are intentionally invalidated by the existing dependency rules.
