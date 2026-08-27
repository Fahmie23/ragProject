# Stage 4.5.8.9 — Correction Integrity & Safety

This release hardens the Stage 4.5 manual-correction layer before Stage 5 chunking. Automatic Stage 3 and Stage 4 artifacts remain immutable; corrections are still stored as auditable operations and resolved into Stage 4.5.

## Problems addressed

1. **Duplicate result element IDs** are now rejected both per operation and globally in the resolved document.
2. **Split text duplication** is prevented by assigning each Stage-3 text span to at most one split result.
3. **Unsafe non-contiguous merge** is rejected when an unselected element sits inside the union of selected boxes.
4. **Stale canonical records** are reconciled after correction: sections, clause records, logical tables, figures, metadata IDs, relationships, and section content references are validated against corrected elements.
5. **Reading order after geometry edits** is reconciled conservatively. Only edited/new elements are repositioned, and only against horizontally-overlapping anchors, so unrelated columns keep their previous relative order.
6. **Generic table editing is hardened.** Generic split/merge/draw-table operations are rejected. Table bbox move/resize is geometry-only; relabeling a table away from `table` removes stale logical-table records.
7. **Cross-page definition membership** is now a real definition operation, not merely a `continues` relationship. A term on one page may own `definition_text` elements on later pages. `target_page_number` is stored for auditability.
8. **Small manual boxes recover Stage-3 provenance/text** using overlap relative to the smaller geometry as well as centre containment.
9. **Invalid bbox values** (`NaN`, infinity, non-numeric values, degenerate geometry) are rejected before save; the frontend disables Apply and displays a validation message.
10. **After preview is closer to backend resolution.** The frontend now mirrors relabel metadata cleanup, text/provenance recovery, reading-order reconciliation, and canonical record cleanup for the live preview.
11. **Selection behavior is consistent.** Normal click replaces selection; Shift/Ctrl/Cmd + click adds/removes selection both on overlays and in the element list.
12. **Pointer cancellation** resets an interrupted drag/resize/draw rather than leaving transient geometry behind.
13. **Split is controlled instead of automatic.** The reviewer chooses the horizontal split position with a visible guide and confirms it before an operation is created.
14. **Unsafe structural promotion is blocked.** The generic relabel/draw tools cannot create titles, document metadata, sections, clauses/subclauses, tables, or figures because those types require associated canonical records. Existing structural elements may still be relabeled away, and dedicated structural editors can be added later.

## Safe merge rules

Generic merge is permitted only for compatible text-like types:

- `paragraph`
- `definition_text`
- `list_item`
- `caption`
- `footnote`
- `formula`

All selected sources must have the same semantic type and section. `definition_text` sources must also belong to the same definition entry. An unselected element inside the merged union blocks the merge.

## Safe split rules

Generic split is allowed for the text-like types above, plus `page_header` and `page_footer`. The split results must stay within the source region (with a small extraction tolerance), must not overlap, and must cover at least 75% of the source bbox.

The frontend no longer immediately splits at 50%. `Split…` opens a split-position control and displays a dashed guide on the selected region. The reviewer chooses the boundary and then presses **Confirm split**.

## Cross-page definitions

The correction operation now supports an optional `target_page_number`:

```json
{
  "operation": "link_definition",
  "page_number": 9,
  "target_page_number": 10,
  "source_element_ids": ["p9-e11", "p10-e2"]
}
```

`page_number` is the term page. `target_page_number` is checked against the final target element location. Stage 4.5 rebuilds the canonical `DefinitionEntry`, so `start_page`, `end_page`, `spans_multiple_pages`, and `definition_element_ids` reflect the corrected membership.

## Reading-order safety

A full page sort by `(y, x)` is intentionally **not** used because that can damage multi-column PDFs. Instead:

- unchanged elements retain their relative order;
- only elements touched by `move_resize`, `split`, `merge`, or `draw` are candidates for repositioning;
- an edited element is compared only with horizontally-overlapping anchors;
- ambiguous/overlapping layouts preserve the prior order instead of guessing.

## Structural-promotion safety

The generic bbox/type editor is intentionally limited to operations that can be represented completely by an element plus provenance. Creating record-bearing structures such as `section_header`, `clause`, `subclause`, `table`, or `figure` requires a dedicated editor that also captures the associated section/clause/table/figure record. Title/subtitle/document-metadata promotion is likewise blocked because it changes document-level metadata. This prevents a visually correct correction from producing an internally incomplete canonical graph.

## Table safety

Until row/cell geometry editing exists, generic correction tools do not attempt to rebuild table cell semantics:

- move/resize table bbox: allowed, geometry only;
- suppress table: allowed;
- relabel table to another type: allowed, logical-table record is reconciled;
- split table: rejected;
- merge table: rejected;
- draw new table: rejected;
- relabel non-table to table: rejected.

## Validation

Backend regression suite after this release:

```text
76 passed
```

New regression coverage includes:

- duplicate split IDs;
- boundary-crossing span split without text duplication;
- non-contiguous merge rejection;
- stale clause cleanup;
- stale section content cleanup;
- stale logical-table cleanup;
- reading-order update after a clear vertical move;
- preservation of untouched cross-column order;
- small-bbox text/provenance recovery;
- cross-page definition membership;
- cross-page definition target-page verification;
- non-finite bbox rejection;
- generic table split/draw rejection;
- generic structural relabel/draw promotion rejection;
- stale appendix membership cleanup;
- stale document metadata/root references after relabel.

Frontend checks:

- TypeScript transpile diagnostics: clean;
- semantic TypeScript check with local React type stubs: clean.

A full Vite build still requires the project's npm dependencies to be installed locally.

## Remaining intentional limitations

- Table **row/cell** editing is not implemented yet. Table bbox correction is geometry-only.
- If Stage 3 exposes only a very coarse text span, a tiny manual box can recover the whole coarse span because Stage 4.5 cannot invent word geometry that Stage 3 never produced. The provenance is preserved rather than silently returning empty content.
- Generic split is horizontal only in this release. Vertical/column splits should be implemented as a separate reviewed interaction rather than inferred automatically.
