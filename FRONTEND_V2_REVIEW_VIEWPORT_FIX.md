# Frontend V2 — Review Viewport Layout Fix

The Review workspace is now treated as a bounded workbench instead of a long page.

## Fixed

- Resolved Document Tree, PDF viewer, and Correction Inspector stay in one desktop row when space permits.
- Each column owns its own scrolling instead of growing the browser page.
- Removed large sticky/min-height behavior that caused the inspector and page elements to be pushed far below the PDF.
- With the application sidebar collapsed, the three-column Review layout is preserved at narrower desktop widths.
- With the sidebar expanded at narrower widths, Review falls back to a compact two-column layout with a bounded inspector row.
- Mobile/tablet still stacks the workspace intentionally.

This is a layout-only change. Stage 4.5 correction semantics, page selection, cross-page continuation, and backend contracts are unchanged.
