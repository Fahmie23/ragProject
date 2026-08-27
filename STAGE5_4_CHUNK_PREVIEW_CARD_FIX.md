# Stage 5.4 — Chunk Preview Card Ownership Fix

## Problem

In the Stage 5 Chunk Preview browser, semantic-type metadata such as `FIGURE`, `TABLE`, `CLAUSE`, and `DEFINITION` could appear visually between adjacent cards. With a long chunk list this made it ambiguous which chunk owned the semantic type and page label.

## Root cause

The left browser used a grid-based scroll list. In the observed runtime layout, many chunk rows were visually compressed, while their metadata/content continued painting close to adjacent rows. The semantic-type text therefore looked detached from its chunk.

## Fix

- Replaced the chunk-list grid with a vertical flex stack.
- Added `flex: 0 0 auto` to every chunk card so rows cannot shrink under list pressure.
- Kept a minimum card height and clipped all child content to the card boundary.
- Added explicit three-row card structure: header, metadata, preview.
- Replaced loose uppercase purple semantic text with a contained, subtle semantic-type pill.
- Semantic-type labels are now humanized (`Clause`, `Definition`, `Table`, etc.).
- Page metadata remains on the same contained metadata row.
- Long semantic labels and preview text are safely truncated inside the card.

## Result

Each chunk is visually self-contained:

```text
Chunk 12                         183 est. tokens
[ Clause ]                               p7–8
2.2 In the case of foreign operations...
```

The semantic type can no longer appear as if it belongs to the card above or below.

## Scope

This is a frontend-only Stage 5 Chunk Preview UI/UX correction. Chunk generation, semantic-v2 logic, provenance, and backend APIs are unchanged.
