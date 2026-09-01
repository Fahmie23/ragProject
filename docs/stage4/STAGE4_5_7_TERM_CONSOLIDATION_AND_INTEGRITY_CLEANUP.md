# Stage 4.5.7 — Multi-line Term Consolidation & Canonical Integrity Cleanup

## Purpose

This patch addresses two remaining canonical-structure defects exposed by glossary pages:

1. a logical definition term can be split into multiple nearby left-column boxes (for example a name followed by a parenthesized acronym), and
2. semantic reconstruction can leave an empty or duplicate textual bounding box after source regions are split or promoted.

The implementation is deliberately term-agnostic and parser-agnostic. No document vocabulary, page number, or PDF-specific coordinates are hard-coded.

## 1. Multi-line definition-term consolidation

The canonicalizer now performs a consolidation pass after merged-row, parallel-column, and glossary-table recovery, but before assigning definition entry IDs.

A pair of left-column fragments is merged only when all of the following structural evidence is compatible:

- both fragments are short term-like labels;
- both occupy the learned/expected left-side term region;
- their left alignment or horizontal overlap is compatible;
- their vertical gap is very small relative to line height; and
- the second fragment behaves like a continuation, such as a parenthesized qualifier/acronym, a continuation after `-`, `/`, or `&`, or an extremely tight wrapped line.

The rule intentionally does **not** treat lower-case text alone as sufficient evidence because legal glossaries commonly contain many lower-case terms on adjacent rows.

When fragments are merged, their Stage 3 block/table provenance is unioned rather than discarded.

### Example canonical result

```
Synthetic Network Provider
(SNP)
```

becomes one element:

```json
{
  "type": "definition_term",
  "text": "Synthetic Network Provider (SNP)",
  "role_source": "definition_multiline_term_consolidation"
}
```

## 2. Post-reconstruction integrity cleanup

A final cleanup pass now runs after definition refinement and footnote refinement, before sections and summary records are built.

It removes only safe reconstruction artifacts:

- empty textual elements;
- textual elements with degenerate/near-zero geometry; and
- near-identical overlapping duplicate textual elements with the same normalized text and semantic type.

Figures, tables, and formulas are not removed merely because their text field is empty because their content may be visual/non-textual.

When duplicate textual elements are collapsed, the stronger semantic element is retained and Stage 3 provenance is merged.

## 3. Existing cross-page UI

No frontend change is required for this patch. The current Structured Document view already derives cross-page definition navigation from `start_page`, `end_page`, `spans_multiple_pages`, and canonical `continues` relationships.

After rerunning Stage 4, verify that the page-level JSON for a continued definition contains:

- a single `DefinitionEntry` spanning the relevant pages;
- `spans_multiple_pages: true`; and
- a `continues` relationship connecting the source and next-page definition fragments.

If the JSON is correct, the UI can display the existing continued-from / continues-to navigation without changing extraction semantics.

## 4. Regression coverage

The backend suite now includes dedicated tests for:

- a two-line definition term with a parenthesized qualifier;
- preservation of Stage 3 provenance across the term merge;
- dense adjacent glossary rows that must remain separate; and
- removal of an empty textual phantom box after reconstruction.

All prior tests for tables, wide rows, parallel columns, nested definition items, cross-page definitions, clauses, appendices, figures, and Stage 4.5 corrections continue to pass.

Expected result:

```text
37 passed
```

## 5. Re-run requirements

Stage 3 does not need to be rerun.

Stage 4 **must** be rerun because this patch changes canonical normalization. Existing saved Stage 4.5 corrections should be exported/backed up first because a Stage 4 regeneration intentionally invalidates corrections built against an older automatic structure.
