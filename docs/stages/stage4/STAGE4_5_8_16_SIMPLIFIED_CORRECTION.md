# Stage 4.5.8.16 — Simplified Correction Workflow

This patch simplifies Stage 4.5 around one rule:

> The reviewer supplies semantic intent; the backend owns derived JSON consistency.

The workbench no longer asks the reviewer to manually construct document graphs during ordinary correction.

## Active correction workflow

The visible Stage 4.5 editor now has only two correction modes:

1. **Element correction** — select/draw one or more regions, correct semantic type and geometry. Multi-selection can apply one safe semantic type to the whole group in one correction operation.
2. **Exact text spans** — rebuild a safe element from exact Stage 3 span evidence.

The previous dedicated **Structured semantics**, **Definition links**, and **Cross-page relationships** editors are removed from the active UI. Their legacy correction operations remain replayable in the backend so existing correction artifacts do not break.

## Contextual relation selection

A relation selector appears only when the selected semantic type needs one.

For `definition_text`:

1. Shift/Ctrl/Cmd-select the relevant regions;
2. if needed, set **Type → Definition Text** once for the whole selection;
3. choose **Belongs to definition**;
4. select an existing `DefinitionEntry`;
5. click **Apply** once for the whole selection.

The frontend writes one intent-level operation:

```json
{
  "operation": "assign_definition",
  "page_number": 14,
  "source_element_ids": [
    "p14-e1",
    "p14-e2",
    "p14-e3",
    "p14-manual-02e2ac30"
  ],
  "definition_id": "def-25"
}
```

The reviewer does not enter `section_id`, reading order, document order, provenance, or bidirectional membership lists.

## Deterministic backend updates

`assign_definition` requires an existing DefinitionEntry and one or more `definition_text` elements on the correction page. The resolver then derives:

- `element.definition_entry_id`
- `element.section_id` from the selected definition term/entry
- `DefinitionEntry.definition_element_ids`
- `DefinitionEntry.definition_text`
- definition page range / cross-page flags
- `SectionRecord.content_element_ids`
- derived definition continuation relations

`unassign_definition` clears definition membership for the selected definition-text elements but does not erase ordinary section membership.

## No automatic definition guessing

Stage 4.5 no longer guesses that `(d)` belongs to a definition merely because it follows `(c)`, has matching geometry, or continues on the next page.

After relabel/draw:

```text
(d) definition_text
    definition_entry_id = null
```

remains unlinked until the reviewer selects the owning DefinitionEntry. Integrity validation reports an unlinked final `definition_text` as an error, so an incomplete relation cannot silently reach Stage 5.

## No aggressive hierarchy repair

The correction resolver also stops rewriting legacy clause/subclause parents by marker/indentation inference. Unknown or imperfect automatic hierarchy remains visible for review rather than being silently changed.

This does not remove the legacy correction schema: saved `set_structure`, `link_definition`, `unlink_definition`, `add_relationship`, and `remove_relationship` operations are still accepted for backward compatibility. They are simply no longer part of the primary UI workflow.

## Compatibility

- Stage 3 remains immutable.
- Automatic Stage 4 remains immutable.
- Existing Stage 4.5 artifacts from earlier versions can still be replayed.
- Correction artifact schema is `1.9`.
- The new `definition_id` field is optional and used by `assign_definition`.

## Acceptance criteria for a definition sequence

After selecting `(a)`, `(b)`, `(c)`, `(d)` and assigning them to one DefinitionEntry:

```text
(a).definition_entry_id == def-X
(b).definition_entry_id == def-X
(c).definition_entry_id == def-X
(d).definition_entry_id == def-X

all section_id == def-X.section_id

def-X.definition_element_ids contains all four
section.content_element_ids contains all four
```

The reviewer makes one semantic decision; the backend keeps the JSON graph consistent.
