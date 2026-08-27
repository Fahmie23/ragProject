# Frontend V2.14 — BBox Draft Feedback

The Review correction inspector now makes bbox correction state explicit.

## Interaction states

- **No coordinate change:** `Apply bbox change` is disabled and the inspector says there is no bbox change to apply.
- **Coordinate edited:** the button enables and the inspector states that the bbox change can be added to the correction draft.
- **Applied to draft:** the button briefly changes to `Applied ✓`, the bbox card receives a success treatment, and a message explains that `Save corrections` is still required to persist the draft.
- **Invalid geometry:** validation remains blocking and the validation message is shown in the same status area.

The button compares against the displayed one-decimal bbox baseline so simply opening an element does not incorrectly appear dirty because the canonical bbox has higher internal precision.

This does not change backend correction semantics: `Apply bbox change` creates the existing `move_resize` session operation; `Save corrections` remains the persistence action.
