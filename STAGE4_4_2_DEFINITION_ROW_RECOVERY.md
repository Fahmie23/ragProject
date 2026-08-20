# Stage 4.4.2 — Definition Row Recovery

## Problem

A glossary / Definitions section can be segmented by a layout engine in several different ways even though the source document has the same semantic structure:

1. separate term and definition boxes;
2. a detected table;
3. one wide body box containing both the left term column and right definition column;
4. one vendor box containing more than one glossary row.

Stage 4 must normalize all of these representations into the same canonical `DefinitionEntry` structure.

## General solution

Stage 4.4.2 adds a merged-definition-row recovery pass before normal definition grouping.

```text
Definitions context
      ↓
learn reliable term/definition column geometry
      ↓
inspect unresolved wide body regions
      ↓
prefer immutable Stage 3 line/span coordinates
      ↓
recover left term column + right definition column
      ↓
if Stage 3 exposes only one spanning text run:
use conservative definition-introducer fallback
      ↓
normalize to definition_term + definition_text
      ↓
run the existing generic definition grouping / cross-page reconciliation
```

No glossary vocabulary, legal term, filename, or page number is hard-coded.

## Column model

Reliable already-separated definition rows are used to learn normalized page ratios for:

- term-column left edge;
- term-column right edge;
- definition-column left edge;
- the gap/split between both columns.

Ratios are used instead of fixed pixels so the learned layout remains useful on pages with slightly different media boxes or margins.

If there are no previously recognized rows, the recovery pass can infer a split from a strong horizontal gap between Stage 3 spans.

## Stage 3 span recovery

When a vendor layout element spans both columns, Stage 4 consults Stage 3 rather than trusting the wide layout bbox.

Example:

```text
Stage 4 vendor element
┌──────────────────────────────────────────────┐
│ nominator         means an individual ...   │
└──────────────────────────────────────────────┘

Stage 3 spans
nominator               x=112..180
means an individual...  x=310..550
```

The canonical layer reconstructs:

```text
definition_term | definition_text
```

while both elements retain source trace back to the same original layout box and Stage 3 block.

## Lexical fallback

Sometimes Stage 3 exposes only one text run across the whole row. In that case geometry alone cannot identify the internal text boundary. Stage 4 uses a conservative set of generic definition introducers such as:

- `means` / `shall mean`;
- `refers to`;
- `includes`;
- `in relation to`;
- `in the context of`;
- `has the meaning of`;
- `is defined as`.

The prefix before the introducer must still satisfy generic definition-term constraints, and the element must already be inside an active Definitions / Glossary context with compatible wide-row geometry.

## Multiple rows inside one vendor box

If Stage 3 line/span geometry reveals multiple separated term/definition rows inside one large layout box, Stage 4 creates multiple canonical row pairs rather than forcing them into one definition.

## Safety / negative evidence

The recovery pass does **not** split a wide region merely because it occurs inside a Definitions section. It also requires a recoverable two-column span pattern or a conservative definition-introducer pattern.

Ordinary wide explanatory prose remains a paragraph.

## Provenance

Recovered elements keep the original source trace. Their `role_source` indicates how the recovery happened:

- `definition_row_recovery_span_columns`
- `definition_row_recovery_text_pattern`

The raw Stage 3 JSON and raw PyMuPDF4LLM layout JSON remain unchanged.

## Pipeline position

```text
Stage 3 raw extraction
      ↓
Stage 4 layout output
      ↓
Definitions context detection
      ↓
Stage 4.4.2 definition-row recovery
      ↓
normal definition grouping
      ↓
cross-page definition reconciliation
      ↓
Canonical DefinitionEntry[]
      ↓
Stage 4.5 human correction, if required
```

## Verification

The backend regression suite now includes tests for:

- recovering a wide merged row using Stage 3 span columns;
- recovering a merged row when Stage 3 exposes only one text run;
- recovering multiple definition rows from one vendor box;
- preserving ordinary wide prose without false splitting;
- vocabulary-agnostic recovery with synthetic terms;
- all previous FAQ, definitions, cross-page definitions, tables, figures, clauses, appendices, footnotes, and correction behavior.

Expected result:

```text
28 passed
```
