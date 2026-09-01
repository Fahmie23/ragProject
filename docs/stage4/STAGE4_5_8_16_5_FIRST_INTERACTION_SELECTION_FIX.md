# Stage 4.5.8.16.5 — First-Interaction Selection Fix

## Problem

On the first correction interaction, a reviewer could select an element and see the **Selected corrected region** editor, then have that editor disappear when trying to interact with it. Re-selecting the element often made the problem disappear.

## Root cause addressed

The sandbox's hard-reset effect was also keyed to `structure.structured_at`. A late Stage 4 artifact refresh was therefore allowed to run the same destructive reset used for actual document/page navigation, including `setSelectedIds([])`. This could race with the reviewer's first interaction.

## Fix

- Hard resets now occur only on a real document or page change.
- Stage 4 timestamp refreshes use a non-destructive synchronization path.
- The refresh preserves selected element IDs that still exist on the page.
- Unsaved correction sessions remain protected from artifact refreshes.
- Pointer/click events inside the **Selected corrected region** editor are isolated from surrounding correction-surface handlers.

## Expected behavior

1. Select a page element.
2. The **Selected corrected region** editor appears.
3. Click Semantic type, a bbox input, Suppress, or a required-relation control.
4. The editor stays visible unless the action intentionally removes/replaces the selected element.
5. This behavior is the same on the first interaction and later interactions.

No backend correction semantics were changed.
