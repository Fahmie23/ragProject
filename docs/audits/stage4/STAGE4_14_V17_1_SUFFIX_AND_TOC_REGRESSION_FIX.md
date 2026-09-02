# Stage 4.14 — v1.7.1 Clause-Suffix and TOC Regression Fix

## Why this repair exists

The v1.7 independent-audit repair correctly fixed the targeted `11.6A` clause,
definition ordering/boundaries, repeated cover title, and embedded captions. A
fresh regenerated Stage 4 JSON exposed two remaining issues:

1. **Clause suffix overreach.** Layout text such as `11.8A reporting institution...`
   (source: `11.8 A reporting institution...`) was being interpreted as clause
   `11.8A`. The same error affected many ordinary clauses whose prose begins with
   the article `A`.
2. **TOC trailing major headings.** Rows such as `9.5\nPART` with
   `IV: RETENTION OF RECORDS` appended to the title cell were not split, even
   though the inverse pattern `PART\n14.` was already repaired.

## Repairs

### 1. Ambiguous article `A` is no longer treated as a suffix

The structural normalizer now distinguishes:

- true suffix: `11.6 A  A reporting...` -> `11.6A A reporting...`
- true suffix already attached: `11.6A A reporting...` -> unchanged
- glued prose article: `11.8A reporting...` -> `11.8 A reporting...`
- glued prose article: `7.1.1A reporting...` -> `7.1.1 A reporting...`

The same guard is applied by the semantic feature extractor so classification,
prefix stripping, and canonical numbering remain consistent.

### 2. TOC major headings merged after a numbered entry are split

The TOC repair now handles both directions:

- `PART\n14.` + `VII: ...\nIdentification ...`
- `9.5\nPART` + `Identification ...\nIV: RETENTION OF RECORDS`

This repairs the remaining page-4 Part IV / Part V rows without weakening the
existing conservative TOC gate.

## Regression coverage

Added tests verify:

- ordinary `A reporting...` prose is not consumed as an alphabetic suffix;
- `11.6A` remains a real suffix;
- trailing `PART` merges are split while preserving the numbered entry and page
  reference.

## Validation

Full backend test suite after repair:

```text
224 passed
```

The regenerated `(8).json` was also replayed through the patched numbering
normalizer. Before this patch it contained 74 clause numbers ending in an
alphabetic `A`; after reparsing, only the intended `11.6A` remains.
