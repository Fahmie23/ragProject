# Stage 4.5.8 — Stage-3 Term Completion & Geometry Snap

This patch fixes two real-world cases that Stage 4.5.7 did not cover.

## Why Stage 4.5.7 was insufficient

### 1. A wrapped term line may be absent from Stage 4

The previous multi-line consolidation only merged two canonical elements. In real PDFs, the layout engine may omit or absorb the first line while Stage 3 still contains it:

```text
Stage 3
Virtual Asset Service Providers
(VASP)

Stage 4 vendor output
(VASP)
```

Stage 4.5.8 now completes the surviving term from immutable Stage-3 line/span geometry.

### 2. A phantom box may contain semantic text but have synthetic geometry

Glossary-table normalization can create a valid `definition_text` element whose estimated bbox extends into an empty inter-column area. Because the element is not empty, an empty-box cleanup cannot remove it.

Stage 4.5.8 now snaps recovered definition-term / definition-text geometry back to matching Stage-3 spans when supporting text-layer evidence exists.

## General rules

No legal terms, acronyms, page numbers, or document-specific vocabulary are hard-coded.

### Stage-3 wrapped-term completion

A surviving term candidate may absorb an adjacent Stage-3 left-column line only when there is strong evidence such as:

- same left-column alignment / strong horizontal overlap;
- tight line spacing;
- the combined text still looks like a term;
- a parenthesized continuation (common for acronyms), connector ending, or a same-block near-zero-gap wrap;
- no conflicting canonical definition term already owns the fragment.

The merged term keeps all Stage-3 block provenance.

### Provenance-backed geometry snap

Recovered `definition_term` and `definition_text` elements are checked against Stage-3 spans. Matching uses:

- exact normalized fragment containment first;
- conservative meaningful-token overlap as fallback;
- source block IDs when available;
- local geometry when source IDs are unavailable.

Common stop words are ignored in token-overlap scoring so a neighbouring definition does not get matched just because both contain words such as `the`, `of`, or `definition`.

If matching Stage-3 spans exist, their union becomes the canonical bbox. If no reliable Stage-3 text evidence exists, the existing semantic geometry is left unchanged.

This also works for glossary rows promoted from vendor tables when the PDF still has a usable Stage-3 text layer. Table-derived rows without text-layer evidence are preserved unchanged.

## Pipeline position

```text
Stage 3 extraction
      ↓
Stage 4 vendor layout
      ↓
definition row recovery
      ↓
parallel-column recovery
      ↓
glossary-table normalization
      ↓
canonical multiline consolidation
      ↓
NEW: Stage-3 wrapped-term completion
      ↓
definition grouping
      ↓
NEW: provenance-backed geometry snap
      ↓
integrity / duplicate cleanup
      ↓
canonical document
```

## Regression coverage

The backend suite now includes cases for:

- both wrapped term lines present in Stage 4;
- first wrapped line missing from Stage 4 but present in Stage 3;
- dense adjacent terms that must remain independent;
- glossary-table continuation geometry with a blank synthetic extension;
- table-derived rows with Stage-3 text support;
- empty textual artifacts;
- all previous definition, table, cross-page, clause, appendix and correction behaviour.

Expected result:

```text
39 passed
```

## Migration

Stage 3 does not need to be rerun. Stage 4 must be rerun because canonical elements and bounding boxes are reconstructed there.

If saved Stage 4.5 correction operations matter, export/back them up before regenerating Stage 4 because corrections created against an older automatic structure become stale by design.
