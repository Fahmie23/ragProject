# Stage 4.5.6 — Definition & Cross-Page Structure Stabilization

This update resolves the remaining complex-definition failure modes without hard-coding any term, page number, or source PDF.

## Scope

Stage 4 now normalizes the following vendor representations into the same canonical `DefinitionEntry` model:

1. Separate term and definition boxes.
2. One wide merged term+definition region.
3. Parallel tall left/right column boxes containing many rows.
4. Glossary-like tables.
5. Nested enumerated definition content.
6. Definition content continuing across page boundaries.

It also introduces a reusable open-block reconciliation layer for non-definition paragraph/clause/list continuation.

## Processing order

```text
Stage 3 immutable extraction
        ↓
Stage 4 vendor layout
        ↓
Definition context detection
        ↓
Merged-row recovery
        ↓
Parallel-column stream recovery
        ↓
Definition-table semantic normalization
        ↓
Term ↔ definition grouping
        ↓
Nested item attachment
        ↓
Cross-page definition reconciliation
        ↓
General open-block reconciliation
        ↓
Canonical document schema 1.4
```

## 1. Parallel tall-column recovery

A vendor may emit one tall left box containing many terms and one tall right box containing many definitions. Stage 4.5.6 no longer treats each tall box as one logical element.

The recovery pass:

- learns or infers a normalized term/definition column split;
- reads Stage 3 lines/spans inside the coarse region;
- groups nearby left-only lines into multi-line terms;
- uses term vertical positions as row anchors;
- assigns right-column text until the next term anchor;
- requires at least two valid repeated rows before rewriting a coarse region.

No domain vocabulary is used.

## 2. Glossary table semantic normalization

A two-column table is **not automatically** treated as a glossary.

A table is promoted only when repeated evidence supports it:

- active Definitions/Glossary/Interpretation context;
- at least two term-like left cells;
- substantive right-hand text;
- most meaningful rows follow the same term → definition pattern;
- right-side text is materially richer than the label side.

When promoted, the canonical page contains `definition_term` and `definition_text` elements instead of one giant `table` element. The immutable vendor Layout JSON and Stage 3 table provenance remain available through source tracing.

Ordinary two-column numeric/key-value tables remain tables.

## 3. Nested definitions

Short introducers such as `means—`, `includes:`, or similar forms are accepted as valid definition content even when they are too short to look like an ordinary paragraph.

Repeated item markers are parsed generically, including common forms such as:

- `(a)`, `(b)`, `(c)`
- `(i)`, `(ii)`, `(iii)`
- `(1)`, `(2)`
- `1.`, `2.`
- `A.`, `B.`

When layout elements are already separated, item boundaries are taken from element boundaries first. This prevents a trailing explanation paragraph from being incorrectly swallowed into the final list item.

## 4. Cross-page nested definition continuation

The reconciliation engine now understands that an open definition may continue with:

- ordinary prose;
- a definition introducer;
- an enumerated/list item;
- additional explanatory paragraphs.

An item such as `(a)` at the top of the next page is therefore not automatically treated as a new clause when the open definition evidence is stronger.

The merge decision uses multiple signals:

- source fragment near the previous page bottom;
- next content near the following page top;
- horizontal/column alignment;
- compatible typography;
- active definition context;
- absence of a new definition term;
- absence of a genuine section/appendix boundary;
- textual incompleteness as supporting evidence.

A `continues` structural relation is stored for auditability.

## 5. General open-block reconciliation

A reusable `OpenBlockState` now represents cross-page state using semantic kind, source element, expected horizontal region, context, and allowed continuation forms.

Definitions use the richest version of this state. A conservative generic pass also creates `continues` relations for incomplete paragraph/clause/list flows when page-edge geometry and context agree.

Tables continue to use their specialized geometry/cell compatibility logic but emit the same `continues` relationship type.

This gives Stage 5 one consistent cross-page relationship concept instead of unrelated ad-hoc mechanisms.

## False-positive safeguards

The implementation intentionally prefers leaving content separate over making an uncertain merge.

Important safeguards include:

- no term-name allowlist;
- no page-number rules;
- normalized geometry rather than fixed PDF coordinates;
- at least two repeated rows before rewriting parallel coarse columns;
- at least two repeated glossary rows before promoting a table;
- ordinary wide prose is not split merely because it appears in a Definitions section;
- ordinary two-column numeric tables remain tables;
- genuine numbered sections and appendices stop continuation;
- footnotes/page headers/page footers are excluded from continuation candidates.

## Canonical schema

`StructuredDocument.schema_version` is now `1.4` because glossary tables may now be semantically represented as definition elements rather than canonical table blocks.

The raw Stage 3 extraction and PyMuPDF4LLM Layout artifact remain unchanged.

## Regression coverage

The backend suite now includes tests for:

- separate glossary rows;
- wide merged row recovery;
- multiple rows inside one vendor box;
- parallel tall-column recovery;
- glossary table promotion;
- rejection of ordinary two-column tables;
- nested definition items;
- trailing explanation preservation;
- cross-page enumerated definition continuation;
- ordinary cross-page definition continuation;
- general clause continuation;
- cross-page table continuation;
- negative boundary cases;
- vocabulary-agnostic synthetic terms.

Current result:

```text
34 passed
```

## Migration

Only backend canonicalization/schema/tests changed. Existing Stage 3 artifacts remain valid.

After applying the patch:

```bash
cd ~/ragProject/backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Expected:

```text
34 passed
```

Do not rerun Stage 3. Rerun Stage 4 for documents whose canonical structure should be regenerated using the new normalization logic.
