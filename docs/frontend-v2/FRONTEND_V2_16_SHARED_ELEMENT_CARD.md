# Frontend v2.16 — Shared Structure / Review Element Card

Structure and Review now render page elements through the same `StructureElementCard` component.

This fixes the remaining visual drift where Structure displayed a two-line text preview but Review could show only the semantic chip and friendly context. The shared card now guarantees both views display:

- semantic type chip
- friendly context (`Element N` / `Row N`)
- compact two-line text preview when available
- the same selected-state behavior
- full technical ID and complete preview in title/ARIA metadata

Review retains its correction-selection click handler (including multi-select modifiers); only the visual renderer is shared.
