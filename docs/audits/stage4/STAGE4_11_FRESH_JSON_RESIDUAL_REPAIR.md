# Stage 4.11 — Fresh JSON Residual Enumeration Repair (v1.5)

## Why this phase exists

The first fresh end-to-end Stage 4 JSON generated with the v1.4 repaired pipeline passed the v1.4 golden benchmark (235/235 required checks). A second document-wide audit then found three remaining semantic-family/ownership edge cases that were not represented in the v1.4 benchmark.

This phase fixes those root causes generically and extends the golden benchmark so they become permanent regression tests.

## Residual cases discovered

### 1. Parallel descriptive siblings split into list_item + subclause

Pattern:

```text
1.1 ... issued pursuant to the following:
(a) ...;
(b) ...:
    (i) ...
    ...
```

The second sibling was sentence-shaped and introduced a nested list, so it was promoted to `subclause` while `(a)` remained `list_item`.

Repair: a multi-member, non-obligation, same-indent enumeration introduced as a descriptive list now preserves one semantic family even when one sibling introduces a nested list.

### 2. Numbered clause styled as a section-header resolved too late

Pattern:

```text
7.3.5 A reporting institution is required to:
(a) ...;
(b) ...; and
(c) ...:
    (i) ...
    (ii) ...
```

The layout engine labeled `7.3.5 ...:` as `section-header`. In v1.4 the numbered-clause promotion pass ran before heading-scope repair but ignored `section_header`, so child enumeration was classified without its obligation-clause context.

Repair: `_promote_numbered_clauses()` now accepts a *narrow* `section_header` case only when all of the following are true:
- a clause number is present;
- the text is sentence/list-introduction shaped;
- finite/modal or sentence evidence is present.

This occurs before enumerated-run classification, allowing `(a)/(b)/(c)` to become sibling subclauses of the numbered clause. A nested `(i)/(ii)` dependent list under `(c)` remains `list_item` and is linked through `introduces`.

### 3. One modal member broke a nested dependent list family

Pattern:

```text
(c) ... must undertake one or more of the following measures:
(i) Requesting ...
(ii) Substantiating ...
...
(v) Using ... which should be linked ...
```

The incidental modal phrase `which should ...` caused `(v)` to become a `subclause` while `(i)-(iv)` remained `list_item`. This also contaminated later Roman sequences at the same indentation.

Repair: for a multi-member nested dependent enumeration, if the majority of siblings are phrase/dependency shaped and there is no established parallel `subclause` family, the complete nested run remains `list_item`.

## Files changed from v1.4

- `backend/app/services/semantic/sequence_resolver.py`
- `backend/tests/test_stage4_canonical.py`
- `backend/evaluation/golden/sc_aml_cft_stage4_v1.json`
- `docs/audits/stage4/STAGE4_11_FRESH_JSON_RESIDUAL_REPAIR.md`

## Tests added

1. `test_semantic_v25_descriptive_parallel_family_stays_list_when_one_member_introduces_nested_list`
2. `test_semantic_v25_numbered_heading_clause_intro_resolves_before_enumerated_children`
3. `test_semantic_v25_nested_dependent_run_keeps_relative_modal_member_in_list_family`

## Verification

Backend suite:

```text
216 passed
```

Python compilation:

```text
compileall OK
```

Golden specification:

```text
spec_version: 1.5
PDF/source-anchor validation: valid
```

The fresh v1.4-generated JSON intentionally does **not** pass all new v1.5 checks. It scores 247/266 required checks (92.86%). The 19 failures map to the three residual semantic-family/ownership cases above. This is expected and proves the v1.5 benchmark can detect them.

## Acceptance procedure

Generate Stage 4 JSON again using the v1.5 project and the same source PDF. Then run:

```bash
cd backend
PYTHONPATH=. python scripts/evaluate_stage4_golden.py \
  --structure /path/to/new-stage4.json \
  --spec evaluation/golden/sc_aml_cft_stage4_v1.json
```

Expected target:

```text
Required checks: 266/266
Advisory checks: 6/6
```

Do not manually edit the generated JSON before evaluation.
