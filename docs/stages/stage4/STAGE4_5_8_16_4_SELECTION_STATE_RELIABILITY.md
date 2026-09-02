# Stage 4.5.8.16.4 — Selection State Reliability

This patch hardens the simplified Stage 4.5 correction editor so semantic relabeling does not make the selected corrected region disappear.

## User-facing behavior

Operations that keep the same canonical element ID now keep that element selected:

- `relabel`
- `move_resize`
- `assign_definition`
- `unassign_definition`

The selected-region editor therefore stays open when a reviewer changes a semantic type, including when changing a region to `definition_text` so the contextual DefinitionEntry selector can appear immediately below it.

Operations that actually remove or replace element IDs are still allowed to change selection, for example suppress, split, and merge.

## Selection-safe rebuild

`rebuildWorking()` now reconciles the current selection against the rebuilt working element list. Existing selected IDs are preserved; only IDs that genuinely no longer exist are removed.

Semantic relabel explicitly passes the selected IDs through the rebuild so an in-place type change cannot collapse the selected-region editor.

## Resolved-artifact refresh safety

Previously the correction sandbox's broad reset effect depended on `resolved_at`. A parent refresh of the resolved artifact could therefore clear selection and unsaved editor state even when the reviewer had not changed page or document.

The document/page/Stage-4 reset remains explicit, but `resolved_at` now has a separate refresh effect:

- if unsaved session operations exist, the local editing session is preserved;
- otherwise the resolved page is refreshed;
- selected IDs are retained when those elements still exist.

## Session-operation reliability

A `sessionOpsRef` now mirrors the React state and is used as the authoritative current operation list when adding operations, validating, undoing, redoing, saving, and changing page. This avoids composing a new operation list from a stale render-time `sessionOps` snapshot during rapid sequential edits.

## Definition relationship safety

Any actual semantic type change now clears `definition_entry_id`. Definition membership is an explicit Stage 4.5 relationship decision and must not be silently carried from one semantic role into another. If the new type is `definition_text`, the reviewer can immediately select the correct DefinitionEntry from the contextual relation control.

## Version

Frontend package version: `0.4.5-8.16.4`.

No backend schema, correction operation schema, or Stage 5 readiness rules changed in this patch.
