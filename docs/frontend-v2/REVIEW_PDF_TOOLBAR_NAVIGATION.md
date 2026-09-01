# Review PDF Toolbar Navigation (v2.11)

## Decision
Page navigation belongs to the PDF viewer because it changes the page being displayed. The Review header now contains only review-level information; previous/current/next page controls are located beside the PDF zoom controls.

## Behavior
- Uses the existing `PageNav` component and the existing guarded `safeSetPage` function.
- Typing the already-current page remains a no-op, preserving the Stage 4.5 page-number blur/selection fix.
- Tree continuation/page-context navigation and PDF toolbar navigation continue to converge on the same page state.

## Responsive presentation
- >= 1440px: PDF title and viewer controls share one toolbar row.
- 1180–1439px: viewer controls use a second toolbar row if necessary rather than shrinking the PDF workspace.
- 768–1179px: page navigation remains inside the PDF card while Tree/Inspector use compact drawer behavior.
- < 768px: the `Page` word is hidden, but arrows, editable page number, total pages, and zoom remain available.

No backend contract or correction data model changes are required.
