# Frontend V2.5 — Main Page Scroll Restoration

Desktop application scrolling now follows a two-level model:

1. The browser/main page scrolls normally when the application content exceeds the viewport.
2. Review sub-panels (Resolved Document Tree, PDF viewer, Correction Inspector) retain their own internal scrolling within the bounded Review workbench.

The desktop shell no longer uses `height: 100dvh` + `overflow: hidden`. It uses a minimum viewport height and normal document flow instead. A stable browser scrollbar gutter is reserved to avoid horizontal layout shifts when page scrolling is needed.
