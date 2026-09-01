# Stage 4.5.8.13 — Relation Model Corrections

This patch fixes relation-integrity false positives and separates canonical graph integrity from historical provenance.

## Problems fixed

### 1. Orphan subclauses are not siblings

A `subclause` with `parent_clause_id = null` is now reported only as `subclause_without_parent`. It is not grouped with every other parent-less marker in the same section for duplicate-marker or sequence validation.

This prevents unrelated `(i)`, `(ii)`, `(a)`, `(b)` structures from creating false `duplicate_subclause_marker` failures.

### 2. Definition source-table IDs are provenance

For `DefinitionEntry.source_kind = "table_rows"`, `source_table_element_id` is historical provenance. A table used to derive normalized `definition_term` / `definition_text` elements may intentionally be absent from the final canonical element list.

The validator therefore no longer treats that missing normalized source table as a dangling canonical foreign key. If the table still exists as a canonical table, its section membership is still validated.

### 3. Definition membership owns section context

When a `definition_text` element is manually linked to a `definition_term`, it inherits the term's `section_id` automatically. Rebuilt `DefinitionEntry` records also normalize all definition-text members to the term's section before `SectionRecord.content_element_ids` is rebuilt.

For the conservative enumerated case, a newly drawn manual `definition_text` is also attached automatically when it immediately follows an already-linked `definition_text`, continues the marker sequence (for example `(c)` → `(d)`), stays in the same column, and is vertically adjacent. Ambiguous prose is left unlinked for review.

This fixes manually drawn definition text that previously showed no section or definition membership while neighboring definition text belonged to the same definition.

### 4. Adjacent-page duplicate clauses are reviewed before being rejected

A repeated clause number across adjacent page-boundary elements is now recognized as a possible cross-page continuation when:

- both records are sibling clauses,
- the second page immediately follows the first,
- the first element ends near the bottom of its page, and
- the second begins near the top of the next page.

Such a case becomes `possible_cross_page_clause_continuation` and requires human review instead of immediately becoming `duplicate_clause_number`.

True same-context duplicates that do not meet the page-boundary continuation guard remain hard errors.

### 5. Baseline issues are separated from correction impact

Resolved Stage 4.5 schema `1.3` now exposes:

```json
{
  "baseline_integrity": { "...": "automatic Stage 4 report" },
  "integrity": { "...": "current resolved Stage 4.5 report" }
}
```

The Review UI compares stable issue signatures and shows:

- Automatic Stage 4 baseline errors/warnings
- Issues introduced by current corrections
- Baseline issues still present
- Baseline issues resolved by corrections
- Grouped issue counts by root-cause code

Individual issues are collapsible so a large pre-existing document report does not overwhelm a page-local correction workflow.

## Schema versions

- Stage 4 canonical structure: `1.6` (unchanged)
- Stage 4.5 correction artifact: `1.7`
- Resolved Stage 4.5 envelope: `1.3`

Older resolved artifacts remain readable because `baseline_integrity` is optional.

## Validation policy

The Stage 5 approval gate still uses the current resolved `integrity` report, not the baseline report. Baseline information is diagnostic only: it explains whether a problem already existed before the current correction.

## Regression coverage

New tests cover:

- duplicate orphan subclause markers not becoming sibling errors,
- normalized table-row definition provenance,
- definition section inheritance, automatic sequential definition-context inheritance, and section-membership rebuild,
- adjacent-page duplicate clause continuation review,
- separate automatic baseline integrity in resolved artifacts.
