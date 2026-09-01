# Stage 4.5.8.1 — General Cross-Page Hierarchy Reconciliation

## Baseline

This patch is built directly from **Stage 4.5.8**. It does **not** include or depend on Stage 4.5.9.

## Problem

The previous cross-page detector handled plain prose/definition continuation reasonably well, but missed a broader class of structures:

- a definition item `(a)` continuing with `(b)` / `(c)` on the next page;
- a bullet list continuing on the next page;
- a nested list such as `(b)` continuing into `(i)`, `(ii)`, `(iii)`;
- numbered siblings such as `(20)` -> `(21)` across a page boundary;
- the same parent section remaining active across a page break;
- repeated page headers appearing before the real continuation content.

These are all instances of the same problem: **an open document hierarchy crosses a physical page boundary**.

## Design

Stage 4 now uses one general hierarchy reconciliation model instead of PDF-specific rules.

### 1. Running decoration is ignored

Before choosing the first next-page candidate, the reconciler skips:

- `page_header`
- `page_footer`
- footnotes
- captions / document metadata where appropriate

A genuine new `section_header` before the candidate is a hard boundary.

### 2. Marker families are normalized

The parser recognizes generic marker forms including:

- bullets (`•`, `▪`, `◦`, etc.)
- `(1)`, `(2)`, ...
- `(1A)`, `(2B)`, ...
- `(a)`, `(b)`, ...
- `(i)`, `(ii)`, ...
- `1.`, `2.`
- `A.`, `B.`

No term names, section titles, page numbers, or PDF-specific vocabulary are hard-coded.

### 3. Sibling vs child continuation

The detector combines:

- marker sequence continuity;
- indentation changes;
- page-edge geometry;
- same active section;
- font compatibility;
- textual incompleteness.

Examples:

```text
(20) ...
------ page break ------
(21) ...
```

is treated as a sibling continuation.

```text
(b) ... are—
------ page break ------
    (i) ...
```

is treated as a nested child continuation when the next marker begins a new family at a deeper indentation.

### 4. Definitions use the same marker intelligence

The existing definition continuation pass is strengthened with the same marker-sequence logic. Therefore a glossary definition such as:

```text
controller
  ...
  (a) ...
------ page break ------
  (b) ...
  (c) ...
```

can remain one `DefinitionEntry` even when the next page starts with a repeated running header.

### 5. Parent section continuity remains intact

The canonical section builder already carries an active section across page boundaries until a genuine new section header appears. The new reconciler now adds an explicit cross-page `continues` relation between the boundary elements, making that continuity visible and usable downstream.

### 6. Structured Document UI is now generic

Previously the cross-page strip displayed only definitions.

It now renders **all cross-page `continues` relations** and labels them as:

- Definition
- Hierarchy
- Table
- Text

The buttons remain clickable so the user can jump to the source/target page.

## Examples covered

The regression suite includes generic synthetic cases for:

1. definition `(a)` -> `(b)` / `(c)` with a running page header;
2. bullet sibling continuation;
3. nested `(b)` -> `(i)` continuation;
4. numbered sibling `(20)` -> `(21)` under the same section;
5. a genuine new section on the next page blocking a false continuation.

## Regression result

```text
44 passed
```

## Migration

Stage 3 does not need to be rerun.

Stage 4 must be rerun because cross-page structural relationships and definition membership are recomputed there.

No schema migration is required. Canonical schema stays at `1.4`.

## Stage 5 implication

Stage 5 should consume the resolved Stage 4.5 structure when corrections exist. The new `continues` relations can be used later to keep logically connected list/clause/definition content together during structure-aware chunking.
