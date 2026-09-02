# Stage 4.5.8.15 — Definition Membership Completion & Precise Provenance

> **Superseded by 4.5.8.16 for correction behavior.** The automatic manual-definition inheritance described below is no longer active; reviewers now select the DefinitionEntry explicitly. Provenance fixes remain applicable.


This patch fixes a specific Stage 4.5 failure mode: manually relabelling or drawing a region as `definition_text` could leave the element semantically typed but unlinked from its `DefinitionEntry` and section. It also fixes over-broad Stage 3 span provenance on recovered glossary rows.

## Goals

Keep the correction model simple and deterministic:

- `definition_text` is still the only definition-body type for now; no `definition_item` schema is introduced.
- A final `definition_text` or `definition_term` must belong to a `DefinitionEntry`.
- Definition membership owns the section context for its term and text members.
- Existing Stage 4 remains immutable; Stage 4.5 only writes correction operations and the resolved projection.
- Exact Stage 3 span provenance must not claim the same coarse span for several synthetic definition children.

## 1. Cross-page definition membership completion

When a manually relabelled/drawn `definition_text` is the leading content on a page, the resolver may attach it to the immediately preceding page's open DefinitionEntry only when the evidence is narrow and deterministic:

- the previous DefinitionEntry ends on the immediately preceding page;
- the definition is explicitly marked `continues_to_next_page`, or its final member is near the page bottom and looks incomplete;
- the new element is in the same definition column;
- an existing section assignment does not conflict;
- the new text begins with an enumerated marker or a definition-introduction phrase.

Once the first item is linked, subsequent same-page `(a) -> (b) -> (c) -> (d)` definition-text items can inherit the same membership using the existing conservative marker-sequence rule.

If those conditions are not met, no definition is guessed. The reviewer assigns the DefinitionEntry explicitly.

## 2. Explicit DefinitionEntry picker

The Review → Definition links UI can now choose an existing DefinitionEntry directly. This is useful when the owning term is on another page.

Workflow:

1. Relabel/draw the target region as `definition_text`.
2. Open **Definition links**.
3. Choose the owning definition from **Existing definition**.
4. Select one or more `definition_text` regions with Shift/Ctrl/Cmd-click.
5. Click **Link selected text**.

The frontend still emits the existing `link_definition` correction operations; there is no new correction-operation schema.

## 3. Bidirectional relation completion

After membership resolution, the backend rebuilds all affected canonical fields together:

- `element.definition_entry_id`
- `element.section_id`
- `DefinitionEntry.definition_element_ids`
- `DefinitionEntry.definition_text`
- `DefinitionEntry.start_page` / `end_page`
- `DefinitionEntry.spans_multiple_pages`
- `SectionRecord.content_element_ids`
- derived cross-page definition `continues` relations

This prevents a manual element from remaining section-less or absent from the owning section record.

## 4. Strong definition integrity rule

A final canonical element with type `definition_term` or `definition_text` but no `definition_entry_id` is now a blocking integrity error:

`definition_member_unlinked`

Likewise, each definition-text member's section must agree with the DefinitionEntry section.

This makes `Validate Relations` catch the exact failure where a type was corrected but the relation was not.

## 5. Precise Stage 3 provenance for recovered definition rows

Earlier recovered glossary rows could copy the source trace of one large parent region, causing multiple synthetic term/text elements to claim the same large set of Stage 3 spans.

Recovered term/text children now recompute source traces from their own bbox. If one Stage 3 span geometrically crosses both children, that ambiguous span is removed from both exact `stage3_span_ids` lists rather than being falsely claimed by both. Coarse block/table provenance is still retained.

This preserves the distinction:

- `stage3_block_ids`: broad source evidence
- `stage3_span_ids`: exact text-span provenance only when geometry supports it

## Compatibility

No correction JSON schema shape changes are required in this patch. Existing saved `relabel`, `draw`, `move_resize`, `span_rebuild`, and `link_definition` operations remain valid.

Existing Stage 4 automatic artifacts remain immutable. Re-running Stage 4 is recommended if you want newly generated recovered definition rows to persist the improved exact span provenance directly.
