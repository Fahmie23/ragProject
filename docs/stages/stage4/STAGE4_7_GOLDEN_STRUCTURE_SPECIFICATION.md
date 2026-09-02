# Stage 4.7 — Golden Structure Specification

## Purpose

Stage 4 now has enough semantic behavior that further changes must be evaluated against a stable definition of **correct structure**, not only screenshots or one-off regressions.

The primary portfolio benchmark is the 109-page Securities Commission Malaysia guideline with SHA-256:

`e1d138edd3c55b3fa3dd36b3236876a1a8dd634c4d972cec74157e6bf816bc15`

The benchmark is intentionally **source-specific** because this is the project's primary demonstration document, but the semantic rules encoded by the benchmark are structural rather than keyword-specific.

The machine-readable specification is:

`backend/evaluation/golden/sc_aml_cft_stage4_v1.json`

## What is golden

Golden means the expected **semantic result**, not the current implementation output.

The following are therefore *not* golden identifiers:

- canonical element IDs;
- layout box indexes;
- Stage 3 block/line/span IDs;
- PyMuPDF4LLM box classes;
- current heuristic role sources.

Those values may legitimately change as extraction improves.

Golden assertions use:

1. PDF page number;
2. normalized text anchor;
3. expected semantic type / canonical record;
4. expected hierarchy or relationship when the relationship is semantically important.

This lets a future parser split or merge layout boxes differently while still being judged on the same document meaning.

## Three levels of benchmark certainty

### Required

High-confidence structural invariants. A required failure is a Stage 4 regression or an unresolved Stage 4 defect.

Examples:

- `8.1.6 ...` is a clause;
- `(a) Full name;` is a list item;
- `Legal persons` on Appendix E page 93 is a local group header, not a SectionRecord;
- clause `1.4` must not continue into fresh clause `1.5`;
- the `beneficiary` definition spans PDF pages 9–10.

### Advisory

Desired behavior that is useful but still being validated across the document family.

Advisory failures are visible but do not make the benchmark fail.

Examples include the current fallback treatment for guidance labels and later illustration semantics.

### Open questions

Taxonomy decisions that should **not** be turned into hard-coded rules yet.

The first specification records three open families:

- recurring `Guidance for paragraph ...` blocks;
- TOC/navigation semantics;
- illustration labels and their relation to figures/explanations.

## Core semantic decisions encoded by v1

### Section header vs group header

`section_header` represents a persistent document-outline scope. `group_header` represents a local label inside an existing section/appendix scope and must not create a `SectionRecord`.

Examples encoded as `group_header`:

- `CDD requirements for individual customer and beneficial owner`;
- `Identification and Verification`;
- `CDD requirements for legal persons`;
- `Business-based Risk Assessment (BbRA)`;
- `Relationship-based Risk Assessment (RbRA)`;
- `Legal persons` / `Legal arrangements` in Appendix E;
- `Steps to identify beneficial owner`;
- `Legal person`;
- `Methods to identify beneficial owners`;
- `Record-keeping of beneficial ownership`.

This deliberately treats embedded PDF bookmarks as evidence rather than final semantic truth.

### Clause vs list item vs subclause

Numbering alone never determines semantic type.

High-confidence list examples:

- `4.2 ... comprises three stages:` followed by `Placement`, `Layering`, `Integration`;
- `8.1.6 ... obtaining at least the following information:` followed by `Full name`, NRIC/passport, address, etc.;
- Appendix E `Legal persons` followed by company/entity categories.

High-confidence subclause examples:

- Appendix E `1.8` item `(d) In implementing Step 1 ... shall ...` because it is an independent proposition;
- non-face-to-face CDD `(a)`, `(b)`, `(c)` because each is a separate obligation/proposition under clause `8.1.23`.

Nested enumerations can still be `list_item` underneath a semantic subclause.

### Cross-page boundaries

Geometry alone must never create semantic continuation.

Fresh structural starts such as a new numbered clause are hard evidence against `continues`.

The benchmark explicitly forbids:

- Appendix E `1.4` → `1.5` continuation;
- page-36 `(b)` → page-37 `(c)` continuation under clause `8.1.23`.

These are sibling structural units, not text continuations.

### Definitions

Definitions remain a specialized Stage 4 subsystem and are evaluated independently from generic text classification.

The benchmark covers:

- `beneficial owner`;
- cross-page `beneficiary`;
- `constituent document` with three sub-items;
- `politically exposed person (PEP)` with enumerated definition items;
- cross-page `third-party institution`.

### Appendix scope and numbering reset

Clause numbers are not globally unique semantic paths.

The main body, Appendix A and Appendix E all reuse low clause numbers. Appendix membership therefore remains first-class canonical scope.

Golden records assert:

- Appendix A: pages 68–78;
- Appendix E: pages 92–102.

### Tables and figures

The benchmark includes:

- page-2 revision table presence;
- Appendix E logical tables spanning pages 96–97 and 97–98;
- the RBA process diagram on page 70;
- later illustration figures as advisory coverage.

## Coverage

The current golden specification (v1.3) contains **118 checks**:

- 79 element assertions;
- 25 relationship assertions;
- 5 definition assertions;
- 2 appendix assertions;
- 2 logical-table assertions;
- 3 page-level assertions;
- 2 figure assertions.

Of these, **105 are required** and **6 are advisory**.

Representative structural coverage includes front matter, revision tables, TOC, normal clauses, nested enumeration, definitions, cross-page definitions, guidance blocks, local headings, cross-page sibling structures, appendix numbering resets, figures, cross-page tables, same-unit semantic continuity, parent-clause tails, cross-page nested-list ownership, and appendix descriptive-title scope.

## Why the whole document is not manually labelled

This is an anchor-based regression benchmark, not a full corpus annotation project.

The goal is to cover every important structural archetype with high-value assertions while keeping manual truth review feasible. If a new Stage 4 failure is discovered, the preferred workflow is:

1. confirm the semantic truth from the PDF;
2. decide whether it is already covered by a golden archetype;
3. fix the generic Stage 4 rule;
4. add a new golden assertion only when it represents a new structural invariant.

Do **not** add assertions merely to make a current implementation score look better.

## Source validation

Before scoring Stage 4, verify that the specification itself still matches the intended PDF:

```bash
cd backend
PYTHONPATH=. python scripts/validate_stage4_golden_spec.py \
  --spec evaluation/golden/sc_aml_cft_stage4_v1.json \
  --pdf /path/to/sc_aml_cft.pdf
```

This checks:

- SHA-256;
- page count;
- internal reference integrity;
- every element text anchor;
- definition terms;
- appendix labels.

A golden source-validation failure means the benchmark is stale or incorrect. It must not be reported as a Stage 4 parser failure.

## Evaluate a Stage 4 result

After running Stage 4 in the application, evaluate the complete `StructuredDocument` JSON:

```bash
cd backend
PYTHONPATH=. python scripts/evaluate_stage4_golden.py \
  --structure data/structured/<document_id>.json \
  --spec evaluation/golden/sc_aml_cft_stage4_v1.json
```

For machine-readable output:

```bash
PYTHONPATH=. python scripts/evaluate_stage4_golden.py \
  --structure data/structured/<document_id>.json \
  --spec evaluation/golden/sc_aml_cft_stage4_v1.json \
  --json
```

The evaluator reports required and advisory scores separately and lists every failing assertion explicitly.

## Acceptance policy for future Stage 4 changes

For this portfolio benchmark:

1. source validation must pass;
2. no previously passing **required** golden assertion may regress without an explicit specification review;
3. new semantic behavior should be accompanied by a focused unit/regression test;
4. advisory checks can become required only after the semantic decision is reviewed;
5. Stage 5 should remain frozen while Stage 4 required benchmark failures are still being actively corrected.

## Generalization policy

This benchmark is intentionally optimized for the portfolio's primary PDF. It is not evidence that all PDF families are solved.

The architecture should still avoid document-specific vocabulary in production rules. After the primary document is stable, a separate generalization benchmark should add unrelated manuals/reports/SOPs rather than weakening this document's golden truth.
