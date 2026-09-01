# Stage 4.5.8.16.3 — Required Relation Placement

This patch moves the contextual DefinitionEntry relationship control into the selected corrected-region workflow.

## UI behavior

- A single selected `definition_text` shows **Required relation** inside the **Selected corrected region** card, after semantic type/geometry/actions.
- The relation selector only appears when the selected type requires it.
- Multi-selected `definition_text` elements keep one bulk relationship control immediately below the selected-region area so one DefinitionEntry can be assigned to the entire group.
- No resolver, correction operation, or backend validation behavior changed.

The reviewer flow is now: select region → correct type/geometry → assign required relation → save.
