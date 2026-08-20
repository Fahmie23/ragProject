# Stage 4.5.8.2 — Manual Cross-Page Relationship Correction

## Baseline

This implementation continues directly from **Stage 4.5.8.1**, which itself was built from Stage 4.5.8. It does **not** use Stage 4.5.9.

## Goal

Automatic cross-page hierarchy reconciliation remains best-effort. When Stage 4 misses or incorrectly creates a cross-page continuation, the user can now correct the relationship manually inside the existing Correction Sandbox without mutating automatic Stage 4 JSON.

The resolved structure is still produced as:

```text
Automatic Stage 4
      +
page-local correction operations
      +
manual relationship operations
      ↓
Resolved Stage 4.5 structure
```

## Correction Sandbox UX

`Preview & Edit` now contains two correction scopes:

```text
Layout correction
Cross-page relationships
```

### Add a continuation

1. Open **Cross-page relationships**.
2. Select the source element on the earlier page.
3. Click **Use selected as source**.
4. Navigate with the normal page-number input or arrows to a later page.
5. Select the target/continuation element.
6. Click **Link continuation**.
7. Inspect **After JSON** and **Correction Log**.
8. Save corrections.

The source selection survives page navigation. The target must be on a later page because `continues` is directional.

### Remove an incorrect automatic/manual continuation

The Cross-page panel lists all `continues` relationships touching the current page. Click **Remove link** to preview removal, inspect the After JSON, then save.

### Before / After

- **Before JSON** remains immutable automatic Stage 4.
- **After JSON** now includes relationship changes from the current unsaved session.
- **Correction Log** contains the auditable `add_relationship` / `remove_relationship` operations.

## Correction schema

The correction artifact schema is now `1.1`. Older page-local correction JSON remains compatible because the new `relationships` field defaults to an empty list.

New operation types:

```text
add_relationship
remove_relationship
```

Relationship snapshots contain:

```json
{
  "relation_id": "manual-rel-...",
  "type": "continues",
  "source_element_id": "p28-e17",
  "target_element_id": "p29-e2",
  "source_page_number": 28,
  "target_page_number": 29,
  "evidence": "manual cross-page hierarchy continuation"
}
```

The page numbers make correction logs self-describing, but the backend verifies them against the final corrected element locations before applying a link.

## Backend safety rules

For a manual `continues` relationship:

- source and target IDs must exist after all page-local corrections;
- source and target cannot be the same element;
- the target must be on a later page;
- source/target page metadata must match the actual canonical elements;
- an equivalent relationship cannot already exist;
- relationship IDs cannot collide with existing relationships.

`remove_relationship` stores a full snapshot and verifies the ID, type, source, and target before removal.

Relationship edits are applied after page-local element edits. Therefore a relationship can safely target a saved/manual element created by split/draw operations as long as that element exists in the resolved element set.

## Page reset semantics

A relationship correction is considered to touch both its source and target page. Therefore:

- page-level correction counters include incoming and outgoing relationship corrections;
- **Reset page** removes saved relationship corrections touching that page;
- the Correction Log on either endpoint page exposes the relationship operation.

## Resolved structure

Manual links become normal canonical `StructuralRelation` objects:

```json
{
  "relation_id": "manual-rel-...",
  "type": "continues",
  "source_element_id": "p28-e17",
  "target_element_id": "p29-e2",
  "evidence": "manual cross-page hierarchy continuation"
}
```

The existing Structured Document cross-page banner therefore works for manual links automatically when viewing **Resolved** mode.

## Scope

The current UI intentionally exposes only manual `continues` editing because this milestone targets cross-page hierarchy continuation. The backend relationship snapshot uses the generic canonical relation type, so future UI work can add `parent_of` or `belongs_to` workflows without replacing the storage model.

## Verification

Backend regression suite:

```text
47 passed
```

New tests cover:

- adding a manual cross-page continuation;
- removing an automatic continuation;
- resolved relation summary count;
- rejecting a backwards `continues` link.

Python compile check passes.

A strict TypeScript source check also passes using temporary React type stubs. Run the real dependency-backed build in WSL:

```bash
cd ~/ragProject/frontend
npm install
npm run build
```

## Migration

You do **not** need to rerun Stage 3 or Stage 4 merely to install this correction feature.

Existing Stage 4.5.8.1 structured JSON can be corrected immediately through the sandbox. If you independently rerun Stage 4 later, existing corrections are still invalidated by the existing stale-correction protection and should be reviewed against the new automatic structure.
