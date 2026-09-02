# Stage 4.5.8.14 — Relation Hierarchy Compatibility Fix

> **Superseded by 4.5.8.16 for correction behavior.** Stage 4.5 no longer performs automatic legal-hierarchy parent repair. Existing relation data is preserved and ambiguous hierarchy is left for review.


This patch addresses relation errors that can remain after Stage 4.5.8.13 when the document was structured by an older Stage 4 build or when nested legal enumerations were flattened under one numbered clause.

## Root causes fixed

### 1. Nested subclauses were flattened

Older Stage 4 logic attached every subclause in a section to the latest numbered clause. A structure such as:

```text
8.3 ...
  (a) ...
    (i) ...
    (ii) ...
  (b) ...
    (i) ...
    (ii) ...
```

could therefore become:

```text
8.3
  (a)
  (i)
  (ii)
  (b)
  (i)
  (ii)
```

and the integrity validator correctly saw duplicate `(i)` / `(ii)` siblings. The real problem was the parent hierarchy, not the validator.

8.14 now resolves marker families with sequence and indentation evidence. Alphabetic children stay under the numbered clause, while roman items are nested under the nearest preceding alphabetic item when the evidence supports it. Ambiguous alphabetic sequences such as `(h) (i) (j)` remain alphabetic siblings.

Explicit Stage 4.5 structural parent edits are protected and are never overwritten by this compatibility repair.

### 2. Legacy definition table provenance was loaded as a live relation

Older artifacts could contain `source_table_element_id` before `source_kind` existed. Loading them with the newer schema gave `source_kind="layout_columns"` by default, which could trigger `definition_table_source_invalid` even though the ID was only historical provenance.

At resolve/validate time, 8.14 migrates any existing `source_table_element_id` to `source_kind="table_rows"` in memory. The stored automatic Stage 4 artifact is not mutated.

### 3. Baseline validation used legacy defects directly

The automatic baseline report is now calculated from a deep-copied compatibility view. Known schema/model migrations are applied before baseline validation so those legacy defects are not incorrectly attributed to the current correction session.

## Backward compatibility

You do not need to delete or re-upload the document just to validate an older Stage 4 artifact. The compatibility repair runs when Stage 4.5 resolves/validates it.

Re-running Stage 4 is still recommended eventually because fresh Stage 4 output now stores the corrected nested parent hierarchy directly.

## Safety

The repair does not invent parents for genuinely orphaned subclauses. A subclause whose `parent_clause_id` is truly absent remains parent-less and still produces `subclause_without_parent` for review.

## Validation

The regression suite covers:

- repeated nested roman markers under separate alphabetic parents;
- `(h) (i) (j)` alphabetic disambiguation;
- old table-definition provenance without `source_kind`;
- baseline compatibility validation;
- fresh Stage 4 clause-building behavior.
