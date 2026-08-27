# Stage 4.5.8.3 — TOC Row Repair & Table Inspection

## Goal

This patch addresses a real table-of-contents extraction error where a visual heading row and the following numbered TOC entry are merged into one vendor table row.

Observed shape:

```text
PDF
PART II: RISK-BASED APPROACH APPLICATION
7    Risk-Based Approach Application    25
```

Vendor table row:

```json
[
  "PART\n7",
  "II: RISK-BASED APPROACH APPLICATION\nRisk-Based Approach Application",
  "25"
]
```

Correct canonical rows:

```json
[
  ["PART", "II: RISK-BASED APPROACH APPLICATION", ""],
  ["7", "Risk-Based Approach Application", "25"]
]
```

## Backend repair

The repair is intentionally conservative and document-agnostic.

A row is split only when:

- the surrounding table already behaves like a 3-column number/title/page TOC;
- the left cell contains at least two visual lines;
- the middle cell contains at least two visual lines;
- the right cell contains one numeric page reference;
- the final left-cell line is a numbered TOC marker;
- the first left-cell line is not itself a numbered marker;
- the first middle-cell line looks like an uppercase heading.

This means an ordinary wrapped title remains one row. For example:

```text
7.6    Risk Management and Mitigation in Third-Party Deposits and
       Payments                                                 29
```

is not split because the left column contains only one marker.

When a repair occurs, Stage 4 now keeps these representations aligned:

- `CanonicalTable.cells`
- `CanonicalTable.row_count`
- table Markdown
- canonical table `text`
- document-level logical-table cells

No PDF-specific term such as `PART II` is hard-coded.

## Inspector improvements

Both Stage 3 and Stage 4 page viewers now have an optional **Labels** toggle.

Stage 3 labels show:

```text
p3-b16 · text
p3-t1 · table
```

Stage 4 labels show canonical reading order and type:

```text
4 · table
5 · section header
```

When a table is selected in either Stage 3 or Stage 4, the right inspector now shows a full row-level table view instead of only the truncated mini preview.

The table inspector also checks for the same obvious heading+entry merge signature. If found, the affected row number is highlighted so it can be compared directly against the PDF.

## Verification

Backend regression suite:

```text
48 passed
```

The new regression test uses the observed TOC pattern and verifies that:

- the merged `PART + 7` row becomes two rows;
- the `7` entry retains page `25`;
- a wrapped `7.6` title remains one logical row;
- the document-level logical table receives the repaired rows;
- canonical text and Markdown agree with the repaired cell structure.

`App.tsx` also passes a TypeScript transpile/syntax check. A full Vite build could not be executed in this environment because frontend npm dependencies were not available locally; run `npm install && npm run build` in the normal WSL project environment.

## Migration

Stage 3 does **not** need to be rerun for the TOC repair.

Stage 4 **does** need to be rerun so the canonical table rows are regenerated.

As with the existing pipeline, review/export saved Stage 4.5 corrections before regenerating Stage 4 because stale automatic element structure invalidates corrections by design.
