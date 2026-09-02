# Stage 4.5.8.10 — Exact Text-Span Correction

This release adds a lower-level correction mode that uses the immutable Stage 3 text spans as the evidence source. It complements the existing element-level correction workbench; it does not replace it.

## Why this exists

Element-level correction is appropriate when a whole canonical region is wrong. It is less precise when one extracted region contains several semantic pieces, for example:

```text
financial group        means a group that consists ...
```

Span correction lets the reviewer select the exact Stage 3 spans that should become a canonical element instead of drawing a new bbox and asking the resolver to infer text by overlap.

## Schema changes

### Stage 3 extraction — schema 1.1

`TextLine` now has an optional stable `line_id` and `TextSpan` has an optional stable `span_id`.

Fresh extraction persists IDs such as:

```json
{
  "line_id": "p10-b20-l1",
  "spans": [
    {
      "span_id": "p10-b20-l1-s1",
      "text": "financial group",
      "bbox": [112.68, 545.21, 178.4, 557.8]
    }
  ]
}
```

Older Stage 3 schema 1.0 artifacts remain readable. The resolver synthesizes the same deterministic IDs from block/line/span nesting without rewriting the immutable extraction file.

### Canonical structure — schema 1.5

`CanonicalSourceTrace` now carries:

```json
{
  "stage3_block_ids": ["p10-b20"],
  "stage3_line_ids": ["p10-b20-l1"],
  "stage3_span_ids": ["p10-b20-l1-s1"],
  "stage3_table_ids": []
}
```

This gives every canonical text element finer-grained provenance when the source geometry supports it.

### Correction artifact — schema 1.4

A new `span_rebuild` correction operation uses exact Stage 3 span IDs:

```json
{
  "operation": "span_rebuild",
  "page_number": 10,
  "source_element_ids": ["p10-e17"],
  "result_elements": [
    {
      "element_id": "p10-manual-term-1",
      "type": "definition_term",
      "bbox": [112.68, 545.21, 178.4, 557.8],
      "source_span_ids": ["p10-b20-l1-s1"]
    },
    {
      "element_id": "p10-e17",
      "type": "paragraph",
      "bbox": [311.4, 545.21, 547.2, 612.9],
      "source_span_ids": ["p10-b20-l1-s2", "p10-b20-l2-s1"]
    }
  ]
}
```

The second result is the residual source content. This is intentional: selecting one span from a larger source element must never silently delete the unselected text.

## Lossless repartition rule

`span_rebuild` is treated as a lossless repartition of every canonical source element it replaces.

If a source element contains these spans:

```text
s1  financial group
s2  means a group that consists ...
s3  continuation ...
```

and the reviewer selects only `s1`, the frontend automatically keeps `s2 + s3` as a residual result. The backend independently verifies that every non-empty source span is still assigned to some result.

The save is rejected if:

- a source span would be silently discarded;
- the same span is assigned to more than one result;
- an unknown span ID is supplied;
- the submitted bbox does not match the union of the selected span bboxes;
- selected non-contiguous spans skip other text inside their derived bbox;
- a selected span belongs to canonical content that is not included as a source replacement;
- the operation tries to create or replace a record-bearing structural type such as a table, section, clause, figure, title, subtitle, or document metadata.

## Frontend workflow

Open:

```text
Review → Preview & Edit → Text spans
```

Then:

1. Click one Stage 3 span.
2. Shift/Ctrl/Cmd-click additional spans that belong to the same semantic element.
3. Review the exact text preview and derived bbox.
4. Choose a safe semantic type such as `definition_term`, `definition_text`, `paragraph`, `caption`, `page_header`, or `page_footer`.
5. Click **Apply span correction**.
6. If the selected spans came from only part of a canonical element, the remaining source spans are preserved automatically as a residual element.
7. Review **After JSON** before saving.
8. Save the correction artifact.

The original Stage 3 extraction and automatic Stage 4 structure remain unchanged.

## Backward compatibility

Re-running Stage 3 is recommended if you want `line_id` and `span_id` persisted directly in the extraction JSON, but it is not required. Legacy extraction artifacts use deterministic synthesized IDs at review time.

Re-running Stage 4 with this release writes canonical schema 1.5 and persists line/span provenance in each source trace.

## Current limitation

The correction granularity is the Stage 3 span itself. If PyMuPDF extracted this as one span:

```text
PART II 7
```

then span mode cannot yet select `PART II` separately from `7`. Character- or word-level geometry would be required for that. Use the existing element correction tools when the required boundary is finer than the available Stage 3 span.

Likewise, generic span correction intentionally does not create new document-level structural records. Dedicated section/table/clause/figure editors should own those operations.

## Validation

The backend regression suite covers:

- persisted Stage 3 line/span IDs;
- deterministic legacy span IDs;
- canonical line/span provenance;
- exact span reconstruction;
- unknown and reused span rejection;
- stale bbox rejection;
- lossless residual preservation;
- silent-text-loss rejection;
- missing-element creation from unrepresented spans;
- non-contiguous span selection rejection;
- unsafe structural-type rejection;
- all pre-existing Stage 3/4/4.5 correction behavior.
