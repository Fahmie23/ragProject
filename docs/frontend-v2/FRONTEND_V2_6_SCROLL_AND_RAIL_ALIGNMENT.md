# Frontend V2.6 — Main-page scroll and collapsed-rail alignment

## Changes

- The manually collapsed large-desktop sidebar now treats the rail as a centered vertical control strip.
- The collapse/expand button uses a 40×40 centered control slot, aligned with Upload and document controls.
- Desktop Review no longer forces the entire correction sandbox to fit inside `100dvh`.
- The Review workspace remains bounded (`clamp(620px, 72vh, 820px)`) so Tree/PDF/Inspector retain independent scrolling.
- Review internal scrollers now use normal scroll chaining, so a mouse wheel/touchpad can continue scrolling the main page after an inner panel reaches its boundary.

## Intended scroll model

1. Browser/main page: normal vertical scrolling.
2. Resolved tree: independent vertical scrolling while pointer is over the tree.
3. PDF viewer: independent scrolling while pointer is over the PDF.
4. Correction inspector/page elements: independent scrolling while pointer is over those panels.
5. At an internal scroll boundary, scrolling chains back to the browser page.
