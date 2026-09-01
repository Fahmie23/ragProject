# Stage 4 Semantic v2.2 — Golden-Driven Repair

This revision uses the Stage 4 golden benchmark to separate evaluator false negatives from real semantic reconstruction defects.

## Scope

1. Golden anchor normalization tolerates missing extraction whitespace after enumeration and footnote markers.
2. Local heading scope is resolved independently from PDF TOC/bookmark labels.
3. Standalone `APPENDIX X` labels override a vendor `page-header` role and create appendix boundaries.
4. Heading-looking numbered procedural steps can be promoted to `clause` when numbering context shows clause semantics.
5. Cross-page `continues` is blocked when the target starts a fresh explicit enumerated/list item.
6. Parallel list runs use indentation and explicit list-introduction context to avoid isolated sentence-shape over-promotion to `subclause`.
7. Definition-item parsing accepts extraction output with no whitespace after markers such as `(a)text`.
8. Large centered cover text can be recovered as the visible `title` while the PDF metadata title remains available at document level.

## Important architecture rule

Layout roles remain immutable evidence. Semantic v2.2 may override their meaning, but `layout_role` / source provenance is preserved. Examples: `page-header -> section_header` for an exact appendix label, or `section-header -> clause` for a numbered procedural step.

## Benchmark workflow

First rerun Stage 4, because semantic changes are applied during canonical reconstruction. Then evaluate the newly generated `data/structured/{document_id}.json`:

```bash
PYTHONPATH=. python scripts/evaluate_stage4_golden.py \
  --structure data/structured/<document_id>.json \
  --spec evaluation/golden/sc_aml_cft_stage4_v1.json
```

The old v2.27 artifact improves from 49/77 to 58/77 when evaluated with the corrected anchor matcher alone. That is an evaluator correction, not a parser improvement. The actual v2.2 parser score must be measured only after a fresh Stage 4 rerun.

## Regression coverage

The backend suite includes focused tests for cover-title recovery, appendix labels misread as page headers, numbered step headings, nested list indentation, marker-spacing normalization, definition item extraction, and the distinction between semantic continuation versus new cross-page siblings.
