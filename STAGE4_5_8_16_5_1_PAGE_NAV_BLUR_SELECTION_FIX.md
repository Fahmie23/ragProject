# Stage 4.5.8.16.5.1 — Page Navigation Blur Selection Fix

## Reproduction fixed

1. Type a page number in the Correction Sandbox page input.
2. Select an element on that page.
3. Click inside **Selected Corrected Region**.
4. Previously, the editor could disappear on that first interaction.

## Root cause

`PageNav` commits its draft both on Enter and on input blur. After a typed page had already become the current page, the later blur could commit that same page again. `CorrectionSandbox.safeSetPage()` treated every commit as real navigation and cleared `selectedIds` and other editor state before calling `setPageNumber(next)`.

## Fix

Two defensive no-op guards were added:

- `PageNav.goToDraft()` does not call `setPageNumber()` when the parsed page is already the current page.
- `CorrectionSandbox.safeSetPage()` immediately returns when `next === pageNumber`, before clearing any editor state.

Real page changes still clear page-scoped selection as before.
