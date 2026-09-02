# Stage 4.12 - Fresh v1.5 JSON Audit, Semantic Consistency, and Golden Benchmark Repair

## Purpose

This phase validates the fresh end-to-end Stage 4 JSON generated from the original 109-page SC AML/CFT/CPF PDF after the v1.5 parser changes.

The audit found that the fresh JSON is structurally sound. Four remaining v1.5 golden failures all referred to one nested structure under paragraph 7.3.5(c). On review against the active Stage 4 semantic taxonomy, those failures were caused by an incorrect golden expectation rather than an incorrect parser result.

## Semantic decision corrected

Paragraph 7.3.5 has this structure:

- 7.3.5 - "A reporting institution is required to:"
  - (a) ...
  - (b) ...
  - (c) "take commensurate measures to manage and mitigate the risks:"
    - (i) "where higher PF risks are identified, a reporting institution must ensure ..."
    - (ii) "where lower PF risks are identified, reporting institution must ensure ..."

The Roman children are sentence-complete conditional obligations with their own modal predicate (`must ensure`). Under the Stage 4 semantic taxonomy they are therefore `subclause`, not `list_item`.

Correct ownership is:

```text
7.3.5 clause
├── (a) subclause
├── (b) subclause
└── (c) subclause
    ├── (i) subclause   parent_of
    └── (ii) subclause  parent_of
```

This differs from dependent enumerations such as page 37, where the Roman members are gerund/phrase continuations of "must undertake one or more of the following measures". Those remain `list_item` and use `introduces`.

## Parser consistency fix

v1.5 could classify the same nested modal structure differently depending on pagination: a multi-member run fitting on one page could be forced into `list_item`, while the same run split across a page break could become `subclause`.

v1.6 removes that pagination dependency. The resolver now distinguishes nested independent modal/conditional propositions under an inherited deontic parent (`subclause` + `parent_of`) from nested dependent phrase/gerund/example inventories (`list_item` + `introduces`).

## Golden specification v1.6

The benchmark was updated from v1.5 to v1.6:

- `pf-7-3-5-nested-i`: expected `subclause`;
- `pf-7-3-5-nested-ii`: expected `subclause`;
- relations from 7.3.5(c) to (i)/(ii): expected `parent_of`;
- added direct clause-parent hierarchy checks for both nested children.

The corrected v1.6 benchmark contains **268 required checks** and **6 advisory checks**.

## Verification results

- backend tests: **216 passed**
- v1.6 required golden checks: **268 / 268**
- v1.6 advisory golden checks: **6 / 6**
- semantic validator warnings: **0**
- golden source/PDF anchor validation: **valid**
- structural integrity scan: **0 dangling IDs, cycles, duplicate IDs, or registry mismatches**
- low-confidence semantic elements (<0.65): **0**
- mean PDF-to-canonical token recall: **99.883%**
- median token recall: **100%**
- minimum page recall: **97.581% on page 25**

The page-25 difference is token normalization only (`6E` in the PDF vs normalized `6 E.` in canonical JSON), not missing substantive text.

## Previously identified structures rechecked

- page 6 parallel `(a)/(b)` family: both `list_item`;
- pages 28-29 7.3.5 outer `(a)/(b)/(c)`: `subclause`;
- pages 28-29 7.3.5(c)(i)/(ii): nested independent `subclause`;
- page 37 Roman dependent measures `(i)-(v)`: `list_item`;
- page 41 `8.4 Politically exposed persons (PEPs)`: real section;
- pages 60-65 guidance/note handling: local callout/group scope;
- Appendix D topic boundaries: restored;
- Appendix F true page-103 -> page-104 continuation: retained;
- previously identified false cross-page continuations: absent.

## Remaining source warning

The JSON retains one expected extraction warning: OCR was disabled, so image-only regions may remain without text. The source PDF is digitally text-backed and the document-wide coverage audit found no substantive text loss.

## Recommendation

Stage 4 is **acceptance-ready for this benchmark**. Keep this document as the primary adversarial/golden fixture, add other document layouts for generalisation testing, and proceed to Stage 5 semantic chunking with the Stage 4 golden suite kept as a regression gate.
