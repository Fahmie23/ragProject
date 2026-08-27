> **Superseded gate behavior:** Stage 4.5.8.16.2 keeps the integrity validator and warning diagnostics from this release, but explicit relationship approval is no longer required for Stage 5. Stage 5 readiness now depends only on blocking integrity errors.

# Stage 4.5.8.12 — Relationship Semantic Validation & Approval

This release makes the Stage 4.5 relationship graph an explicit safety gate before downstream chunking.

## Why this change exists

A canonical graph can be internally connected and still be semantically wrong. For example, a subclause may point to a real parent clause but the parent can occur after the child, sibling markers can repeat, or a cross-page continuation can join incompatible content. Those errors are much harder to notice than a bad bounding box and can silently damage chunking.

Stage 4.5.8.12 separates three questions:

1. **Graph integrity** — are IDs, records, back-references, and required derived edges internally consistent?
2. **Semantic consistency** — are hierarchy order, sibling sequence, page ranges, fragment ordering, and continuation semantics plausible?
3. **Human approval** — has the current saved relationship graph been explicitly reviewed for Stage 5?

## Schema changes

### Stage 4 canonical structure

`StructuredDocument.schema_version` is now `1.6`.

Every `StructuralRelation` now carries provenance:

```json
{
  "relation_id": "rel-...",
  "type": "parent_of",
  "source_element_id": "p14-e2",
  "target_element_id": "p14-e3",
  "evidence": "canonical clause parent membership",
  "provenance": "derived"
}
```

Allowed provenance values are:

- `automatic` — emitted by automatic Stage 4 reconstruction;
- `manual` — created by an explicit Stage 4.5 relationship correction;
- `derived` — regenerated from authoritative canonical records during resolution.

### Stage 4.5 corrections

`CorrectionArtifact.schema_version` is now `1.6` and stores a `relationship_review` object. Any correction save creates a new correction revision and resets relationship approval.

### Resolved Stage 4.5

`ResolvedStructureArtifact.schema_version` is now `1.2` and includes:

```json
{
  "integrity": {
    "status": "pass",
    "semantic_status": "review_required",
    "errors": [],
    "warnings": []
  },
  "review": {
    "status": "needs_review",
    "approved_issue_ids": [],
    "pending_issue_ids": [],
    "approved_at": null,
    "note": null,
    "stage5_eligible": false
  }
}
```

## Semantic checks added

### Section hierarchy

- parent section must exist;
- parent section must occur before the child;
- cycles are rejected;
- child heading level should be deeper than the parent; level conflicts require review;
- record page number must agree with the source header element.

### Clause and subclause hierarchy

- parent clause must exist;
- parent must occur before the child;
- parent and child section membership must agree;
- duplicate sibling clause numbers are errors;
- duplicate sibling subclause markers are errors;
- suspicious sibling ordering or numbering gaps are review-required warnings;
- clause/subclause record page number must agree with the source element.

### Definitions

- term/text membership remains bidirectionally checked;
- repeated definition-text membership is rejected;
- `start_page` / `end_page` must match actual members;
- `spans_multiple_pages` must match the page range;
- `definition_element_ids` must be in document order;
- `continues_to_next_page` must match the last definition-text geometry/content.

### Logical tables

- fragments must be stored in document order;
- page range and `spans_multiple_pages` must match fragment pages;
- fragment and logical column counts must agree;
- fragment `row_count` / `col_count` must agree with cells;
- logical `row_count` and cells must match the ordered fragment cells;
- cross-page continuation edges remain derived from logical-table membership.

### Figures and appendices

- figure page number must agree with its source figure element;
- appendix page range must agree with its label/title elements;
- existing figure/appendix membership and derived-edge checks remain active.

### Continuation relationships

Warnings such as different semantic types, partial definition/table membership, large page gaps, and untyped `belongs_to` edges are now explicitly marked as requiring human review where appropriate.

## Integrity issue IDs

Every integrity warning/error receives a deterministic `issue_id` such as:

```text
ri-98b302d7fe2b4b11
```

Approval references these IDs rather than warning text, so stale approvals can be detected reliably.

## Stage 5 approval gate

Saving corrections does **not** approve them for Stage 5.

The workflow is:

```text
Save corrections
    ↓
Validate relationships
    ↓
Graph integrity PASS?
    ├─ no → fix errors
    └─ yes
         ↓
Review required warnings
         ↓
Explicitly approve current saved revision
         ↓
Stage 5 eligible
```

Any later correction save invalidates approval automatically.

New API:

```text
POST /api/documents/{document_id}/corrections/approve-relationships
```

The request includes the Stage 4 timestamp, the exact saved correction revision timestamp, approved warning issue IDs, and an optional note. Approval is rejected if corrections changed, Stage 4 changed, graph integrity fails, or a review-required warning was not approved.

## Frontend

The Review workspace now distinguishes:

- **Graph integrity**: PASS / FAIL;
- **Semantic status**: clear / review required / blocked;
- **Stage 5 gate**: READY / REVIEW REQUIRED / BLOCKED.

Review-required warnings have explicit checkboxes. The reviewer must check all required warnings before approval. The selected-element graph also displays relationship provenance.

## Deliberate restrictions

Generic relabel/draw still does not create record-bearing structural types such as tables, figures, sections, or document metadata without the appropriate structured editor. This is intentional: blocking an unsupported structural promotion is safer than creating valid-looking but incomplete relation JSON.

## Validation

The backend regression suite contains 110 passing tests after this release, including new tests for:

- parent-before-child validation;
- duplicate subclause markers;
- sibling sequence review warnings;
- definition page metadata;
- logical-table metadata;
- manual vs derived relation provenance;
- Stage 5 approval gating;
- approval invalidation when corrections are saved again.
