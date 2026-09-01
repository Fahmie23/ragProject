# Stage 4.5.8.7 — Manual Correction Workbench

This patch completes the first practical manual-review loop for visually correcting Stage 4 structure while keeping automatic extraction immutable.

## Design invariant

Automatic Stage 3 and Stage 4 artifacts are never overwritten by human review.

```text
Stage 3 extraction (immutable)
        ↓
Stage 4 automatic structure (immutable)
        ↓
Stage 4.5 correction operations (auditable)
        ↓
Resolved Stage 4.5 structure
```

If Stage 4 is rerun, previous Stage 4.5 corrections are invalidated because element IDs and geometry may have changed.

## Review workflow

The Review workspace now guides the reviewer through four steps:

1. Select a region.
2. Correct geometry/type or semantic links.
3. Compare before and after.
4. Save correction operations.

### Layout correction

Supported operations:

- move / resize a bounding box;
- edit exact `x0, y0, x1, y1` coordinates;
- change semantic type;
- draw a missing region;
- split one region horizontally;
- merge multiple regions;
- suppress a false-positive region;
- undo / redo unsaved edits;
- reset one page or the whole manual layer.

The UI calls the internal operation `delete`, but presents it as **Suppress** because the automatic Stage 4 artifact remains unchanged. The operation is stored only in the correction layer.

Text is reconstructed from immutable Stage 3 text spans after a geometry correction; reviewers do not need to retype extracted text.

## Definition links

A new **Definition links** mode allows a reviewer to correct same-page term-to-definition membership.

Workflow:

```text
select definition_term
        ↓
Use selected as term
        ↓
select definition_text
        ↓
Link selected text
        ↓
repeat for additional definition text blocks
```

Linked text blocks can be individually unlinked.

The correction operations are:

- `link_definition`
- `unlink_definition`

If a term has no automatic `definition_entry_id`, the backend creates a deterministic manual ID based on the term element ID. If definition text is reassigned from another definition, the corrected membership wins in the resolved structure.

After corrections are applied, layout-column `DefinitionEntry` records are rebuilt from the corrected element membership. Table-row definitions are preserved when their source table still exists and remains a table.

## Cross-page relationships

The existing cross-page relationship editor remains separate from same-page definition membership. It supports adding and removing audited `continues` relationships between elements on different pages.

## Correction audit metadata

`CorrectionOperation` now includes an optional `note` field. UI-generated suppression and definition-link operations populate this field so the correction log explains intent.

Correction artifact schema version is now `1.2`.

## Before / After behavior

- **Before JSON** shows immutable automatic Stage 4 page data.
- **After JSON** shows the live corrected page plus unsaved correction operations.
- `definition_membership_preview` is included in the live After JSON so definition-link changes are visible before saving.
- **Correction Log** shows saved and unsaved operations and notes.

## Safety rules

The backend rejects malformed definition links when:

- the source is not a `definition_term`;
- the target is not `definition_text`;
- either element does not exist on the correction page;
- an unlink request targets elements that are not currently linked.

Bounding boxes are still clamped to the page and must remain at least one PDF point in width and height.

## Validation

Backend suite:

```text
58 passed
```

New tests cover:

- manually linking a definition term and definition text;
- rebuilding the resulting canonical `DefinitionEntry`;
- unlinking the final definition text and removing the now-empty definition entry;
- rejecting definition links with incompatible semantic types.

Frontend TypeScript was syntax/type-checked with local React declaration shims because package installation is unavailable in the execution environment. A normal project machine should still run:

```bash
cd frontend
npm install
npm run build
```

## Recommended usage for the example definition page

For a suspicious empty box near `legal person`:

1. Open **Review** → **Layout correction**.
2. Click the empty after-overlay.
3. Confirm the selected element ID and bbox.
4. Click **Suppress selected region**.
5. Inspect **After JSON**.
6. Save the correction.

If a term and its definition text are linked incorrectly:

1. Correct their semantic types in **Layout correction** if necessary.
2. Switch to **Definition links**.
3. Select the term and click **Use selected as term**.
4. Select the correct definition-text region.
5. Click **Link selected text**.
6. Unlink any incorrect existing member.
7. Review and save.
