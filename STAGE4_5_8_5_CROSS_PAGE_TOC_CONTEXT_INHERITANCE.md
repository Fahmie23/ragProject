# Stage 4.5.8.5 — Cross-page TOC Context Inheritance

## Goal

Stage 4.5.8.4 intentionally allowed the merged-TOC-row repair only on pages with an explicit heading such as `CONTENTS` or `TABLE OF CONTENTS`. That was safe, but it meant a continuation page without a repeated heading could not receive the repair even when it was clearly the next fragment of the same table of contents.

Stage 4.5.8.5 adds conservative cross-page TOC-context inheritance.

## What changes

An explicit TOC page remains the only trust anchor. A following page may inherit that context only when all of the following are true:

1. The immediately previous page already has explicit or safely inherited TOC context.
2. The previous page has a table fragment approaching the bottom of the page.
3. The candidate table on the next page begins near the top of the page.
4. No substantive body element appears before the candidate table. Running page headers/footers are ignored.
5. The two table fragments have compatible column count and left/right table geometry.
6. Their assigned structural context is compatible after section assignment.
7. Both fragments independently look like a stable three-column `number | title | page` TOC.

Only the first continuing table fragment on the inherited page is eligible for automatic row repair. Other tables on that page remain untouched.

## Why this is safer than inheriting by page number alone

The implementation does **not** assume that page N+1 is part of the TOC simply because page N contained `CONTENTS`. The continuation must independently satisfy the same geometry/boundary predicate used by Stage 4 logical-table reconciliation.

This prevents TOC context from leaking into a new appendix, chapter, or unrelated table that begins on the next page.

## Multi-page propagation

Inheritance is transitive, but only while every page-to-page link continues to satisfy the same evidence:

```text
Page 3: explicit CONTENTS
  table reaches bottom
        |
        v
Page 4: inherited TOC context
  table starts near top and reaches bottom
        |
        v
Page 5: inherited TOC context
```

If any intermediate page fails the continuation checks, propagation stops immediately.

## Shared continuation predicate

The page-to-page continuation rules are now centralized in `_tables_form_cross_page_continuation(...)` and reused by:

- TOC-context inheritance; and
- logical multi-page table construction.

This prevents the two passes from drifting into different definitions of a table continuation.

## Derived data consistency

When an inherited TOC table is repaired, Stage 4 updates all representations together:

- `table.cells`
- `table.row_count`
- `table.col_count`
- `table.markdown`
- canonical element `text`

Therefore downstream logical-table merging, `body_text`, JSON inspection, and later chunking see the same repaired structure.

## Safety tests added

The backend regression suite now covers:

1. repair on a continuation page that does not repeat `CONTENTS`;
2. transitive inheritance across three TOC pages;
3. stopping inheritance when substantive content appears before the candidate table;
4. limiting inherited repair to the continuing top table only;
5. stopping inheritance when the candidate starts too low on the next page;
6. stopping inheritance when table geometry is incompatible;
7. the existing explicit-context positive case;
8. the existing no-explicit-context negative case; and
9. preservation of wrapped TOC titles such as a multi-line `7.6` entry.

Current backend result after this change:

```text
55 passed
```

## Rerun requirement

Stage 3 does not need to be rerun. Re-run Stage 4 so the canonical document can apply the new cross-page TOC-context rules.
