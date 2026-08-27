# Stage 4.5.8.8 — Multi-selection reliability

## Problem

In Layout correction, a Shift-click on a second overlay did not remain selected. The overlay selected on `pointerdown`, then selected again on `click`. Because multi-selection toggles membership, the second event immediately removed the region that the first event had added.

## Fix

- Selection is now handled once, on pointer-down.
- The redundant click-time selection handler was removed.
- Shift, Ctrl, and Cmd/Meta are accepted as multi-selection modifiers.
- Modifier-click is selection-only, so a tiny pointer movement cannot accidentally move a region while building a merge selection.
- The toolbar displays the current selected-region count and a short modifier-key hint.

## Expected workflow

1. Click region A.
2. Hold Shift (or Ctrl/Cmd) and click region B.
3. Both regions remain highlighted.
4. The toolbar shows `2 selected`.
5. `Merge selected` becomes enabled.
6. Modifier-click an already-selected region to remove only that region from the selection.

## Scope

This is a frontend interaction fix only. No correction-operation schema, Stage 3 extraction, Stage 4 canonicalization, or backend merge logic changed.

## Validation

- Backend regression suite: 58 passed.
- App.tsx TypeScript/TSX syntax transpilation: 0 syntax diagnostics.
- Source-level regression check confirms the editable overlay has a single selection trigger and modifier-click exits before drag state is created.
