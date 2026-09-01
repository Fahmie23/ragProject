# Frontend v2.15 — Canonical Element List Cleanup

## Problem
The Stage 4 / Stage 4.5 canonical page inspection list was behaving like a mini inspector. Each row displayed semantic type, internal element ID, full text, structural metadata, provenance, and sometimes table previews. On narrow inspector widths this made text visually collide with neighbouring cards and made scanning difficult.

## Change
The element list is now a compact navigation surface:

- semantic type remains visible;
- raw IDs such as `p14-e4-r3-definition` are replaced in the card header by human-readable context such as `Row 3` or `Element 3`;
- text is whitespace-normalized and clamped to at most two lines;
- table cards use a simple placeholder when no text preview exists;
- the same human-readable context is used in the Review page-element navigator for consistency;
- technical IDs and complete element data remain available in Page JSON / advanced inspection;
- the full ID and complete text are also retained in the card title/accessible label;
- selected cards receive a subtle left accent so selection remains obvious.

## Data / pipeline impact
None. No canonical IDs, text, provenance, correction data, or backend behavior are modified. This is presentation-only.
