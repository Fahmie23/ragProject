# Responsive UI Test Matrix

Use browser DevTools responsive mode or resize the browser to these widths. Keep the same document/page selected while crossing breakpoints to verify state preservation.

## 1. Large desktop — 1600 × 900

Expected:
- Document sidebar can be expanded/collapsed manually.
- Review shows `Resolved Tree | PDF | Inspector` in one row.
- PDF owns the largest horizontal area.
- Tree, PDF, and Inspector scroll independently.
- Browser/main workspace does not become multiple PDF-pages tall.

State test:
1. Select a PDF region.
2. Change semantic type or relationship without saving.
3. Resize to 1300px.
4. Selected element and unsaved correction must remain.

## 2. Standard desktop — 1366 × 768

Expected:
- Sidebar is automatically a 72px document rail.
- No sidebar expand handle is shown.
- Review remains three columns.
- Inspector never drops below the PDF.
- Long tree labels truncate instead of widening the tree.

State test:
1. Enter a page number.
2. Select a corrected region.
3. Click into the correction inspector.
4. Selection must remain visible and editable.

## 3. Compact laptop/tablet — 1024 × 768

Expected:
- Desktop sidebar is hidden.
- Sticky top document bar provides document selection and PDF upload.
- PDF is the primary Review canvas.
- Bottom Review dock shows `Tree | PDF | Correct | Page`.
- Tree opens as a left drawer over the PDF.
- Correct/Page open as a right drawer over the PDF.
- Drawers never push the PDF downward.

State test:
1. Select a PDF element. `Correct` drawer should open.
2. Close drawer and open Tree.
3. Choose a tree node on another page.
4. Tree closes, PDF navigates, and the element remains selected.
5. Open Correct again and verify the same selection.

## 4. Mobile — 390 × 844

Expected:
- Compact document bar remains available.
- Workflow navigation horizontally scrolls.
- PDF remains the primary Review surface.
- Tree and Inspector become full-width task panels.
- Bottom dock remains reachable.
- No desktop sidebar appears.

State test:
1. Select a region.
2. Open Correct.
3. Rotate/resize to tablet width and back.
4. Selected page/element and unsaved correction must remain.

## 5. Cross-page continuation

At any width:
1. Select an element with a `continues` relationship.
2. Use `continues on page N` / `continued from page N`.
3. Navigation must use the existing guarded page-change path.
4. Unsaved corrections must trigger the existing discard confirmation before leaving the page.
5. The target continuation element should become selected after navigation.

## 6. Regression checks

- Resizing must not reset `selectedIds`.
- Resizing must not reset selected Stage 3 spans.
- Resizing must not clear unsaved `sessionOps`.
- Same-page PageNav blur must not clear selection.
- Desktop `Hide elements` preference must not be changed by compact/mobile Correct/Page tabs.
- Stage 4.5 save/reset behavior must remain unchanged.
