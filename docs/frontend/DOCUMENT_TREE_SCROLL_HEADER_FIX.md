# Document Tree Scroll/Header Stability Fix

## Scope

This fix applies to both **Structure** and **Review** because both screens render the shared `DocumentTree` component.

## Problem

When the tree body became tall enough to require vertical scrolling, the flex-column layout allowed the tree header to shrink. If the helper sentence wrapped to an additional line, that line could be pushed underneath the nearby-page navigator and appear clipped.

## Fix

- The tree header now uses `flex: 0 0 auto` so its height is always content-driven.
- The nearby-page navigator remains a non-shrinking region.
- Only `.document-tree-scroll` is allowed to consume remaining height and scroll.
- `.document-tree-scroll` uses `scrollbar-gutter: stable` so scrollbar appearance does not change available content width.
- The helper text explicitly allows normal wrapping and visible overflow.

## Result

The tree is now partitioned conceptually as:

1. Header — fixed by content, never scrolls/shrinks.
2. Nearby-page navigator — fixed by content, never scrolls/shrinks.
3. Tree body — fills remaining height and owns vertical scrolling.

This behavior is shared by both Structure and Review.
