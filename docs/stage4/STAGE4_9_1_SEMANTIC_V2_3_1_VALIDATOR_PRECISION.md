# Stage 4 Semantic v2.3.1 — Validator Precision & Residual Ownership

## Purpose

A fresh local v2.3 reconstruction passed the v1.2 golden benchmark but still surfaced four semantic-review warning families. Inspection showed that these were mostly validator false positives rather than reconstruction defects. One real residual ownership gap also remained on page 99, where figure-layout fragments sat between an `as follows:` paragraph and its A/B/C list members.

## 1. Appendix descriptive-title confidence

Appendix descriptive titles are represented as `group_header` elements and linked to the appendix label by `belongs_to`. Hierarchy confidence calibration and semantic validation now treat that canonical appendix membership as resolved structure rather than incorrectly requiring an `introduces` edge.

This prevents valid appendix titles from being lowered to 0.60 confidence solely because they are not list/group introducers.

## 2. Cross-page continuation is valid ownership

A paragraph fragment that is the target/source of a `continues` relation is no longer flagged as a detached parent-clause tail.

Example:

```text
(iii) ... must be reviewed
              continues ->
periodically.
```

The cross-page relation already expresses the intended semantic continuity.

## 3. Form-heading style-split guards

The style-split validator now avoids false alarms for two generic form patterns:

- a heading/field label ending in `:` followed by instructions;
- a heading followed by a block containing multiple `Label : value` rows.

This preserves real form structure such as `Match with ... :` and `Details of ...` instead of suggesting an invalid paragraph merge.

## 4. Figure-interleaved list ownership

A paragraph that explicitly introduces an enumeration (`the following`, `as follows:`) can remain the active list owner across same-page figure-layout fragments. This is conservative: the paragraph must still clearly introduce an enumeration, and later paragraphs/sections/clauses close the scope.

This fixes the page-99 pattern:

```text
The beneficial ownership breakdown ... is as follows:
[figure-layout fragments]
A) ...
B) ...
C) ...
```

so all three list members receive explicit `introduces` relations from the paragraph.

## Golden benchmark v1.3

The benchmark now contains:

- 79 element assertions;
- 25 relationship assertions;
- 5 definition assertions;
- 2 appendix assertions;
- 2 logical-table assertions;
- 3 page assertions;
- 2 figure assertions.

Total: **118 checks — 112 required and 6 advisory**.

The newly uploaded fresh v2.3 JSON scores **109/112 required (97.3%)** against v1.3 because it predates the page-99 ownership fix. A diagnostic replay of the v2.3.1 relationship logic reaches **112/112 required and 6/6 advisory**. A fresh local Stage 4 rerun is still required for the official v2.3.1 score.

## Tests

The backend regression suite now contains **178 passing tests**. New tests cover:

- appendix-title membership confidence;
- cross-page continuation validator precision;
- form-heading false-positive guards;
- list ownership across intervening figure fragments.

## Stage 5

Stage 5 code is unchanged. Regenerate chunks only after a fresh v2.3.1 Stage 4 output has been reviewed/finalized.
