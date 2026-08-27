# Stage 5.2 — Deterministic Semantic v2

## Goal

Improve retrieval chunk quality before embeddings with a fully deterministic refinement pipeline. Semantic v2 keeps `semantic_v1` as a legacy baseline and makes the improved deterministic strategy the default.

## Generic design

The rules are intentionally independent of the current AML/CFT PDF. They do not contain domain keywords, fixed page numbers, or fixed clause numbers. Decisions use only reusable document signals:

- canonical semantic type;
- `parent_of` and `continues` relationships;
- clause parent IDs as a hierarchy fallback;
- section identity / ancestry;
- document order and page proximity;
- introductory punctuation/patterns;
- token budgets;
- conservative numbered-note marker matching;
- logical table row structure.

This means the same code can process policies, manuals, contracts, reports, standards, handbooks, and other digitally born PDFs as long as Stage 4 produces trustworthy canonical structure.

## Pipeline

```text
Resolved JSON
  -> cleaning
  -> semantic-v1 base units
  -> dependency grouping
  -> continuation merging
  -> contextual-note attachment
  -> conservative short-sibling packing
  -> row-aware table splitting
  -> context injection
  -> hard max-token validation
  -> deterministic quality report
  -> chunks.json
```

## Important rules

### Parent + dependent children

A canonical parent with dependent children is treated as one semantic component. If the component fits under `max_tokens`, it is emitted together. If it is too large, Semantic v2 splits only between semantic child units. Later groups receive the parent as `context_text`, and the parent IDs are recorded separately in `context_element_ids`.

### Soft minimum

`soft_min_tokens=100` is a signal, not a hard floor. Tiny definitions and genuinely independent short clauses are allowed. Short standalone sibling clauses in the same section may be packed toward `target_tokens` when doing so does not cross hierarchy or section boundaries.

### Navigation filtering

Content below conservative navigation sections (`Contents`, `Table of Contents`, `Index`) is excluded from retrieval while remaining untouched in Resolved JSON.

### Notes

Typed footnotes are attached using section/page proximity. Numbered paragraph notes are only attached when a matching inline marker is found in the preceding semantic unit.

### Tables

Large tables split on row boundaries. Later table chunks repeat the header as retrieval context rather than cutting ordinary rows arbitrarily.

## Quality report

Each artifact reports:

- tiny chunk signal count;
- orphan dependent children;
- dangling introductory parents;
- navigation leakage;
- chunks with repeated parent context;
- dependency groups;
- continuation merges;
- short sibling packs;
- row-aware table splits;
- contextual-note attachments.

`orphan_child`, `dangling_intro`, and navigation leakage are hard structural review signals. Tiny chunks alone do not fail quality.

## Regression coverage

Tests intentionally include non-AML synthetic structures, including an employee safety manual hierarchy, generic table of contents, cross-page procedure continuation, numbered maintenance note, and large equipment table. This prevents the strategy from being validated only against the original regulatory PDF.
