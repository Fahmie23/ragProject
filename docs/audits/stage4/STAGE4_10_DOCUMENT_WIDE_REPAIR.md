# Stage 4.10 — Document-Wide Structural Repair

## Goal

Repair the structural defects discovered by cross-checking the 109-page Securities Commission Malaysia AML/CFT/CPF guideline PDF against the Stage 4 JSON, without hard-coding page numbers or document-specific phrases.

The repair is implemented as reusable Stage 4 semantics: numbering-aware hierarchy, callout scope, nested enumeration, continuation validation, fragment normalization, footnote/figure cleanup, and stronger golden evaluation.

## Confirmed repaired failure classes

### 1. TOC navigation must not become body outline
- TOC pages are detected and suppressed from persistent body `SectionRecord` creation.
- Multi-page TOC context is inherited so later TOC pages are not mistaken for body sections.

### 2. Numbered heading hierarchy
- Numbering depth/parentage is used as a primary structural signal.
- Sibling numbered headings such as `7.1`, `7.2`, `7.3` are kept under the same numbered parent.
- A numbered heading emitted near the bottom of a page as `page_footer` can be recovered when surrounding numbering proves it is a real heading.

### 3. Callout / guidance / note scope
- Added a narrow reusable callout matcher in `semantic/patterns.py`.
- `Guidance for ...`, `Note:`, `Warning:`, explanatory notes and source/reference labels can be scoped locally instead of becoming persistent document sections.
- Broad titles such as `Guidance on ...` are intentionally *not* automatically treated as callouts because they can be genuine appendix/document titles.
- Fresh numbered clauses terminate local callout scope.
- Callout-owned paragraphs and their nested lists can be represented with `introduces` relationships.

### 4. Nested enumeration restoration
- Enumeration runs are split by indentation as well as document order.
- The resolver can return from a nested Roman list to the previous outer alpha sequence.
- Example class: `(c) -> (i)..(v) -> (d) -> (e)`.
- Previous same-level subclause family outranks a nearer nested list introducer when the outer sequence resumes.
- Nested lists under an already-resolved subclause remain list items rather than polluting the legal clause registry.

### 5. Normative versus descriptive enumeration
- Longer deontic constructions such as `must conduct ... to determine the following:` are recognized without relying on a brittle fixed word window.
- Descriptive field inventories such as `required to identify ... by obtaining the following information:` remain `list_item` families.
- A modal in an earlier completed sentence does not turn a later descriptive tail into subclauses.

### 6. Cross-page continuation precision
- Continuation decisions now use stronger semantic guards in addition to geometry/font compatibility.
- Completed source sentences, fresh headings, callouts and new clauses are rejected as continuation targets.
- Genuine continuation remains supported, including continuation lines before a following list marker.

### 7. Same-page fragment normalization
- Marker-only fragments can be merged with the immediately following aligned content.
- Wrapped heading/name fragments can be reconstructed when geometry/font/source provenance support the merge.
- This prevents isolated `(ii)` markers or wrapped names from becoming separate semantic objects.

### 8. Appendix topic boundaries
- Repeated appendix topic headings are distinguished from persistent body sections and local groups using numbering/context.
- Appendix topic changes can create the correct local section boundary without inheriting the previous topic incorrectly.

### 9. Footnotes
- Bottom-page, marker-like small text receives a dedicated footnote refinement pass.
- Footnotes are prevented from remaining ordinary body paragraphs when the page geometry/style strongly indicates footnote semantics.

### 10. Figure/text duplication
- Textual picture shells that duplicate canonical body text can be suppressed.
- Provenance from the removed visual shell is merged into the retained canonical element so source traceability is preserved.

### 11. Structural validation
New semantic validation checks detect, among other issues:
- numbered section-parent conflicts;
- clauses assigned outside the matching numbered section ancestry;
- callout scope leaking into fresh numbered clauses;
- suspicious continuation relationships;
- hierarchy/relationship incompatibilities.

### 12. Golden benchmark expansion
- Benchmark version: **1.4**.
- Required checks: **235**.
- Advisory checks: **6**.
- The benchmark covers the document-wide failure classes discovered during PDF↔JSON review.
- PDF SHA, page count and text anchors are validated against the source PDF.

## Changed source files

- `backend/app/services/canonical.py`
- `backend/app/services/evaluation/stage4_golden.py`
- `backend/app/services/semantic/continuity.py`
- `backend/app/services/semantic/heading_resolver.py`
- `backend/app/services/semantic/patterns.py` **(new)**
- `backend/app/services/semantic/sequence_resolver.py`
- `backend/app/services/semantic/validator.py`
- `backend/evaluation/golden/sc_aml_cft_stage4_v1.json`
- `backend/tests/test_stage4_canonical.py`
- `backend/tests/test_stage4_golden.py`

## Verification results

### Backend unit/regression suite

```text
213 passed, 0 failed
```

Command:

```bash
cd backend
PYTHONPATH=. python -m pytest -q
```

### Python compilation

```text
compileall: OK
```

### Golden source validation

```text
Golden specification valid.
Source SHA, page count, and every element text anchor were verified against the PDF.
```

### Original Stage 4 JSON against expanded benchmark

```text
Required: 159/235 (67.7%)
Advisory: 6/6 (100.0%)
```

This is expected: the expanded benchmark deliberately exposes the defects discovered in the original JSON.

### Repaired semantic diagnostic replay

```text
Required: 235/235 (100.0%)
Advisory: 6/6 (100.0%)
```

The diagnostic replay rebuilds Stage 4 semantics from the existing extracted Stage 4 source geometry/text/provenance so the repaired Stage 4 logic can be evaluated over the full 109-page document.

## Important verification boundary

A completely fresh `PDF -> PyMuPDF4LLM layout -> Stage 3 -> repaired Stage 4` ingestion was **not** executed in this environment because the project-pinned `pymupdf4llm` dependency is not installed here. The semantic repair, regression suite, golden anchors, source PDF validation and full-document diagnostic replay are verified.

On the development machine, the final acceptance run should therefore be:

```bash
# from backend venv after dependencies are installed
PYTHONPATH=. python -m pytest -q

# run a fresh document ingestion/extraction through the application
# then evaluate the newly generated Stage 4 structure:
PYTHONPATH=. python scripts/evaluate_stage4_golden.py \
  --structure <fresh-stage4-json> \
  --spec evaluation/golden/sc_aml_cft_stage4_v1.json
```

## Open taxonomy questions (not test failures)

The benchmark intentionally leaves three product/taxonomy decisions open:
1. whether recurring guidance blocks should eventually gain a dedicated `guidance_header/advisory_block` type instead of `group_header`;
2. whether TOC navigation semantics should become a dedicated Stage 5 `navigation_only` concept;
3. whether illustrations deserve a dedicated subtype when it materially improves retrieval/provenance.

These are design decisions, not unresolved structural defects in the current Stage 4 benchmark.
