# Stage 4 Semantic v2.2 — Golden-Driven Structural Repairs

## Purpose

This revision uses the Stage 4 Golden Structure Specification as the acceptance contract for the primary 109-page benchmark PDF. It fixes root causes identified by the v2.27 baseline instead of adding document-page special cases.

The v2.27 artifact originally reported **49/77 required checks (63.6%)**. Inspection showed that several failures were evaluator false negatives caused by PDF glyph-spacing differences such as `(a)Full name;` versus `(a) Full name;`. After correcting benchmark matching, the unchanged v2.27 artifact reports **58/77 (75.3%)**.

The v2.2 semantic repair logic was then applied diagnostically to that same StructuredDocument and rebuilt through sections, definitions, clauses, relationships, and appendices. The projected repaired artifact satisfies **77/77 required** and **6/6 advisory** checks. A fresh local Stage 4 run is still required to establish the official post-v2.2 benchmark score because this packaging environment does not have `pymupdf4llm` installed.

## Repairs

### 1. Golden anchor normalization

Golden matching now treats harmless extraction spacing after structural markers as equivalent:

- `(a)Full name;` == `(a) Full name;`
- `(i)shareholders...` == `(i) shareholders...`
- `1Regulation...` == `1 Regulation...`

The semantic text is unchanged; only benchmark identity normalization is affected.

### 2. Correct Appendix A golden boundary

The benchmark now records Appendix A as PDF pages **68–78**. Appendix A1 starts on PDF page 79. The previous 68–77 range used the printed page numbering rather than the actual PDF page index used by StructuredDocument.

### 3. Cover-title recovery

A large, centered first-page text box can now be promoted from `paragraph` to `title` when its font size is substantially larger than the page baseline. Vendor layout role remains provenance evidence.

### 4. Appendix boundary resolver

A standalone `APPENDIX <label>` is a hard semantic boundary even when the layout engine labels it `page-header`.

The resolver:

- promotes exact appendix labels to `section_header`;
- preserves the original `layout_role`;
- gives appendix boundaries top-level outline scope;
- rebuilds all appendix containers by document order;
- allows a same-page paragraph to serve as the appendix title when appropriate.

This prevents later appendices from being incorrectly inherited into a previously detected appendix.

### 5. Major outline boundary protection

`PART`, `CHAPTER`, `BOOK`, and `DIVISION` headings are treated as major outline boundaries. An active local group can no longer demote a later major heading into `group_header`.

### 6. Numbered heading vs clause resolution

A bookmark/layout heading such as `1.8 Step 1: ...` is converted to a clause when:

- it does not own a deeper numbered family such as `8.1 -> 8.1.1`;
- same-depth numbering shows clause progression; and
- surrounding body structure is compatible with a clause.

Conventional `x.0` headings remain outline sections.

### 7. Local heading scope resolver

Unnumbered headings are demoted to `group_header` when semantic scope shows that they are local labels inside an existing outline region. Evidence includes:

- an active numbered outline whose next clause remains inside that outline;
- an active local-group scope;
- a preceding clause that explicitly introduces locally grouped content;
- guidance/callout headings local to the active substantive section.

Definition-term-like headings are protected and left for the specialized definition resolver.

### 8. Sequence-family consistency

Enumerated runs now use indentation boundaries. A nested sequence such as:

```
(i) ...
(ii) ...
(d) ...
```

is split at the return to the outer indentation rather than treated as one marker family.

When an explicit list introducer and parallel geometry establish a list family, one sentence-shaped member no longer becomes a `subclause` merely because it contains more prose. This fixes parallel stage lists and nested example lists while preserving true modal/propositional subclauses without explicit list context.

### 9. `continues` semantic contract

Generic `continues` now means the **same semantic unit** continues across a page break.

A target that starts a fresh:

- title/heading/group;
- numbered clause;
- bullet;
- `(a)/(b)/(i)` item;
- numbered item;

is a semantic boundary and cannot receive a generic `continues` edge. Cross-page sibling or child hierarchy belongs in structural relationships, not text continuation.

Specialized definition/table continuation logic remains separate.

### 10. Definition sub-item parsing

Definition item parsing now accepts extraction output where the visual space after a marker is absent. Definitions such as `constituent document` and PEP therefore populate structured `DefinitionEntry.items` from `(a)`, `(b)`, `(c)` members instead of storing only flattened definition text.

### 11. Local-group relationships

Local group relationships now distinguish:

- parallel clause-owned groups;
- leaving an indented clause-local group by returning to the clause column;
- nested consecutive local labels;
- a local label introducing the following numbered clause.

This supports structures such as:

```
Steps to identify beneficial owner
  -> Legal person
     -> Clause 1.7
```

without making those local labels persistent SectionRecords.

## Validation

Backend regression suite:

```
163 passed
```

Golden source validation against the benchmark PDF:

```
Golden specification valid.
Source SHA, page count, and every element text anchor were verified against the PDF.
```

Unchanged v2.27 artifact with corrected evaluator:

```
Required: 58/77 (75.3%)
Advisory: 5/6 (83.3%)
```

Diagnostic projection using the v2.2 semantic repair functions on the uploaded v2.27 StructuredDocument:

```
Required: 77/77 (100.0%)
Advisory: 6/6 (100.0%)
```

The diagnostic projection is not a substitute for a fresh Stage 4 run. Run Stage 4 locally with this revision and then execute the golden evaluator to obtain the official score.

## Stage 5

Stage 5 is intentionally unchanged in this revision.
