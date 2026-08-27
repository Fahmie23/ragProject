# Stage 5.2.1 — Genericity and limits

Semantic v2 is not tuned to the AML/CFT sample document. The production chunking service contains no AML, CDD, PEP, reporting-institution, page-number, or clause-number-specific rules.

## What it generalizes from

It relies on the canonical contract produced by Stage 4/4.5:

- semantic element types;
- section ancestry;
- parent/child clause IDs and `parent_of` relations;
- `continues` relations;
- document order and page proximity;
- logical table rows;
- conservative punctuation/marker patterns;
- token budgets.

Therefore a new PDF can benefit without changing Stage 5 as long as its Stage 4 canonical structure is accurate enough.

## What it does not assume

- a specific legal/regulatory document;
- particular section names other than conservative navigation labels (`Contents`, `Table of Contents`, `Index`);
- fixed page positions;
- fixed clause numbering schemes;
- a particular vocabulary/domain;
- an external model or provider.

## Conservative fallback

When hierarchy or note attachment cannot be proven from canonical relations/markers, Semantic v2 leaves the units independent and exposes remaining quality signals instead of guessing. This protects unrelated PDF genres from over-aggressive merging.
