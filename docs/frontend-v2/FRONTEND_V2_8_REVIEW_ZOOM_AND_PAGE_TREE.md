# Frontend V2.8 — Review Zoom + Current Page Structure

## Review PDF zoom

The Review PDF viewer now includes `−`, `Fit`, and `+` controls.

- `Fit` keeps the page fitted to the available viewer width.
- `−` / `+` switch to manual zoom in 15% increments.
- Manual zoom range: 50%–250%.
- Zoom changes the actual `.page-canvas` width rather than applying a CSS transform, so overlay percentages, pointer hit testing, draw mode, resize handles, and bbox corrections stay aligned.
- Manual zoom can exceed the viewer width; the existing PDF viewer scroll container provides horizontal/vertical scrolling.
- Zoom is preserved while moving between pages and resets to Fit when switching documents.

## Review tree scope

The Review screen no longer renders the full document tree for every page.

`DocumentTree` now supports:

- `scope="document"` — full canonical document tree (used by Structure).
- `scope="page"` — current page elements only, while retaining ancestor nodes required to understand section/clause/definition context.

Review uses `scope="page"` and labels the panel **Current page structure**.

Page-scoped behavior:

- Current-page canonical elements are shown.
- Parent nodes from other pages are retained as dimmed `context` nodes.
- Cross-page `continues` relations remain attached to the page elements and can navigate to the connected page.
- Orphan/root elements on the current page are still included.
- If a page has no canonical elements, an explicit empty state is shown.

The Structure screen remains the place for browsing the full-document hierarchy.
