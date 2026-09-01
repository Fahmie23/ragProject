# Stage 4 Semantic v2.3 — Semantic Continuity & Hierarchy Completion

## Purpose

Semantic v2.3 addresses the remaining Stage 4 defects discovered after the v2.2 golden benchmark reached 100% on its original coverage. The new failures were not primarily element-type mistakes. They were failures of **semantic continuity** and **hierarchy completeness**:

- one logical subclause split into two layout boxes;
- a bold sentence prefix misread as a section heading;
- correctly-classified list items with no semantic owner;
- unnumbered prose that resumes a parent clause after an embedded list;
- appendix descriptive titles duplicated as empty outline sections.

The implementation remains deterministic and document-agnostic. No AML/CFT/beneficial-owner vocabulary is used by the production rules.

## Golden benchmark expansion

The primary benchmark specification is now version `1.3` and contains:

- 79 element assertions;
- 25 relationship assertions;
- 5 definition assertions;
- 2 appendix assertions;
- 2 logical-table assertions;
- 3 page assertions;
- 2 figure assertions.

Total: **118 checks — 112 required and 6 advisory**.

New coverage includes pages 43, 94, 95, 103, 105 and 107 for:

- `clause opening -> embedded list -> clause tail`;
- same-unit subclause continuation;
- cross-page nested list ownership;
- style-split sentence reconstruction;
- appendix descriptive-title scope.

The evaluator also supports `expect_count: 0`, allowing the golden specification to assert that a layout fragment must disappear as a standalone canonical element after a successful semantic merge.

## 1. Same-unit semantic continuation

New module:

```text
backend/app/services/semantic/continuity.py
```

The resolver merges adjacent layout fragments only when the evidence is strong:

- same physical page;
- adjacent reading order;
- same Stage 3 source text block;
- compatible font size;
- compatible horizontal geometry;
- no fresh clause/list marker on the right fragment;
- the left fragment ends mid-thought;
- the right fragment begins like grammatical continuation.

The left canonical element id is retained. Stage 3 block/line/span provenance and bbox coverage are unioned, so no source evidence is lost.

Example:

```text
(c) Shareholders may ... take actions
+
and make decisions for the entity ... where:
```

becomes one `subclause`, after which `(i)` and `(ii)` can be attached to that subclause.

### False-positive guards

The resolver deliberately does **not** merge:

- short local headings followed by ordinary prose;
- definition terms followed by `means`, `refers to`, `includes`, etc.;
- fresh numbered/enumerated units;
- fragments with incompatible indentation/columns;
- fragments that cross terminal punctuation boundaries.

## 2. Style-split sentence reconstruction

A typography-only `section_header` can be demoted and merged into the following paragraph when both boxes come from the same Stage 3 text block and form one sentence.

This fixes Appendix G, where bold styling split:

```text
Regulation 3 of the Strategic Trade (...)
```

from:

```text
Regulations 2010 (...) requires the following ...:
```

The result is one `paragraph`, not a fake SectionRecord.

## 3. Dependent-list ownership

`_build_group_and_list_relations()` now tracks:

- active clause;
- active subclause;
- active local group;
- unnumbered list-introducing paragraph;
- nested list-item parents by indentation.

Correctly-classified list items therefore receive explicit `introduces` relationships instead of remaining semantically orphaned.

Ownership can continue across physical page breaks as long as the section/context remains compatible.

## 4. Parent-clause tail reconstruction

Legal/policy prose commonly has:

```text
parent clause opening
  -> (a)
  -> (b)
parent clause trailing prose
```

The trailing prose is neither a new standalone semantic topic nor part of `(b)`. Semantic v2.3 records:

```text
trailing paragraph --belongs_to--> parent clause
```

If that trailing paragraph itself introduces a nested list, it can simultaneously own that list via `introduces` relationships.

## 5. Sequence-family refinements

The sequence resolver now preserves two additional generic patterns:

### Inherited obligation

When the parent supplies a deontic predicate such as:

```text
A reporting institution is required to–
```

parallel `(a)/(b)/(c)` verb phrases remain `subclause` even if each item omits its own modal verb.

### Cascading step with nested members

A substantive enumerated item that ends in `:` and introduces a deeper list remains a `subclause` rather than being flattened into `list_item` merely because its parent said `the following ...`.

This preserves structures such as:

```text
8.1.11 ... following cascading steps:
  (a) ... this includes identifying:
      (i) ...
      (ii) ...
```

while descriptive list families such as Appendix G `(a)-(d)` remain `list_item`.

## 6. Spaced alphanumeric clause numbering

Clause-number extraction now accepts forms such as:

```text
6 A.1
```

and normalizes the semantic number to:

```text
6A.1
```

without changing the source text.

## 7. Appendix descriptive-title scope

The first unnumbered heading immediately following an appendix label on the same page is already represented as `AppendixRecord.title`.

Semantic v2.3 demotes that duplicate outline node to `group_header` when appropriate:

```text
APPENDIX F                     section_header / appendix boundary
Guidance on ...                group_header / AppendixRecord.title
1.0 Introduction               section_header
```

Numbered appendix headings remain genuine SectionRecords.

## 8. Stronger semantic validation

The advisory validator now reports:

- dependent list items without `introduces`/`parent_of` ownership;
- detached clause-tail paragraphs;
- residual same-block heading/paragraph style splits;
- appendix titles that are already represented by AppendixRecord metadata but still create duplicate SectionRecords;
- existing low-confidence, empty-section, orphan-group and suspicious-continuation conditions.

The validator still does not invent repairs and remains non-blocking at automatic Stage 4.

## Validation

Backend regression suite:

```text
174 passed
```

Golden source validation against the exact 109-page PDF:

```text
Golden specification valid.
Source SHA, page count, and every element text anchor were verified against the PDF.
```

Historical v2.3 development baseline against the earlier v1.2 benchmark reported:

```text
Required: 88/105 (83.8%)
Advisory: 6/6 (100.0%)
```

That lower score is intentional: the benchmark now captures defects that the older 77-check contract did not test.

A diagnostic replay of the v2.3 semantic/relationship passes over the earlier v1.2 contract satisfied:

```text
Required: 105/105 (100.0%)
Advisory: 6/6 (100.0%)
```

This diagnostic replay is not a substitute for a fresh local Stage 4 reconstruction because this packaging environment does not have `pymupdf4llm` installed. Run Stage 4 locally with this revision, then run the golden evaluator to obtain the official v2.3 score.

## Stage 5

Stage 5 is unchanged. Regenerate Stage 5 chunks only after Stage 4.5 has finalized a fresh v2.3 resolved structure.
