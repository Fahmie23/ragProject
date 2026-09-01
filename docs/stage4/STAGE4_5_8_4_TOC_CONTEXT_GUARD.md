# Stage 4.5.8.4 — TOC Context Guard

## Goal

Stage 4.5.8.3 introduced a conservative repair for vendor table rows where a visible TOC heading and the following numbered entry were accidentally merged into one 3-column row.

Stage 4.5.8.4 adds an additional safety gate so that repair cannot run merely because an unrelated table happens to look like a `number | title | page` table.

## New safety rule

TOC row repair is now enabled only when the current layout page has an explicit heading-like box whose text is one of these forms (case-insensitive):

```text
CONTENTS
TABLE OF CONTENTS
CONTENTS (continued)
TABLE OF CONTENTS (continued)
```

The heading must come from a heading-like layout class:

```text
title
section-header
page-header
```

Ordinary text boxes and table cells cannot activate the repair.

## Repair decision flow

```text
Detected table
    |
    v
Does this page have explicit TOC context?
    | no
    +------> preserve vendor rows exactly
    |
   yes
    v
Does the table behave like 3-column number/title/page TOC data?
    | no
    +------> preserve vendor rows exactly
    |
   yes
    v
Does a row match the suspicious heading + following-entry merge signature?
    | no
    +------> preserve row
    |
   yes
    v
Split only that row
```

## Example

On a `CONTENTS` page, this vendor row:

```json
[
  "PART\n7",
  "II: RISK-BASED APPROACH APPLICATION\nRisk-Based Approach Application",
  "25"
]
```

can become:

```json
[
  ["PART", "II: RISK-BASED APPROACH APPLICATION", ""],
  ["7", "Risk-Based Approach Application", "25"]
]
```

The same row on a page headed `Quarterly Risk Register` is intentionally left unchanged, even if the surrounding table otherwise resembles a TOC.

## Scope

This change only affects Stage 4 canonical table normalization. It does not modify Stage 3 extraction, PDF geometry, definitions, clauses, figures, or frontend inspector behavior.

Continuation pages without an explicit recognized TOC heading are intentionally **not** auto-repaired in this version. This is the safer default. If later evidence shows that a continuation page needs repair, cross-page TOC-context inheritance should be implemented as a separate, explicitly tested rule rather than weakening this guard.

## Verification

Backend regression suite:

```text
49 passed
```

The regression coverage now verifies both directions:

- a merged TOC heading/entry is repaired when the page explicitly says `CONTENTS`;
- the identical TOC-shaped table is not repaired on a non-TOC page;
- wrapped titles such as `7.6 ... Third-Party Deposits and Payments` remain one logical row.

## Migration

Stage 3 does not need to be rerun.

Stage 4 must be regenerated for the new context guard to affect canonical table output.
