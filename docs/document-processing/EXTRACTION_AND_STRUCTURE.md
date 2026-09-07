# Extraction and Canonical Structure

## Stage boundary

Stage 3 extracts evidence; Stage 4 interprets structure. Keeping those responsibilities separate prevents semantic assumptions from contaminating raw PDF extraction.

```text
PDF
 ↓
Stage 3: blocks / lines / spans / tables / geometry
 ↓
layout-provider evidence
 ↓
Stage 4 deterministic semantic reconstruction
 ↓
canonical document JSON
```

## Stage 3 — deterministic extraction

Stage 3 uses PyMuPDF-derived page evidence including blocks, lines, spans, tables and bounding boxes. Stable line/span provenance is retained so later human corrections can reconstruct text from immutable extraction evidence.

Scanned documents are not silently treated as successfully extracted digital text. OCR is outside the frozen portfolio path; unsupported/insufficient extraction should be visible rather than invented.

## Layout evidence

PyMuPDF4LLM layout output is persisted separately from the canonical structure. Every canonical element can retain its vendor `layout_role`, but that role is only evidence.

## Canonical semantic taxonomy

```text
title
subtitle
document_metadata
section_header
group_header
clause
subclause
definition_term
definition_text
paragraph
list_item
table
figure
caption
page_header
page_footer
footnote
formula
unknown
```

Important distinctions:

- `section_header` owns document-outline scope and may create a `SectionRecord`.
- `group_header` is a local label and never creates a document-outline section.
- `clause` is a numbered substantive unit.
- `subclause` is an enumerated child proposition with independent proposition semantics.
- `list_item` materially depends on an introducing clause/group/list context.
- numbering alone never decides `subclause` vs `list_item`.

## Semantic reconstruction

The deterministic resolver uses reusable signals rather than document-specific AML vocabulary:

- vendor layout role;
- clause/list marker sequence;
- PDF TOC/numbering evidence;
- typography and geometry;
- punctuation and text shape;
- finite/modal predicate signals;
- neighboring element context;
- local introduction/ownership relations.

Specialized reconstruction handles definitions, tables, figures, footnotes, appendices, TOC behavior and cross-page continuation. Later specialized passes may supersede an early tentative label.

Each final element records auditable classification metadata such as selected type, confidence, evidence and alternatives. These values support review; they are not calibrated correctness probabilities.

## Relationships

Canonical clause hierarchy uses ClauseRecords plus `parent_of` where that relationship is backed by a canonical clause record.

Local semantic dependencies use relationships such as `introduces`, for example:

```text
clause → group_header → list_item
clause → directly introduced list_item
```

This separation avoids treating every local label/list relationship as legal/document outline hierarchy.

## Cross-page and continuity rules

The final Stage 4 system includes conservative handling for:

- multi-page TOC continuation with context guards;
- definition rows split by layout extraction;
- continuation fragments of the same semantic unit;
- dependent list ownership;
- parent-clause tails;
- appendix boundary/reset behavior;
- spaced alphanumeric numbering;
- figure-interleaved content.

The rules are structural and avoid hard-coded benchmark page numbers or AML-specific keywords.

## Golden structure benchmark

The primary 109-page PDF has an anchor-based golden structure specification. It validates stable source anchors and selected semantic/relationship expectations rather than manually labelling every element in the document.

The benchmark distinguishes required checks from advisory/open decisions. A source-validation failure means the benchmark fixture is stale or incorrect; it is not automatically a parser defect.

The benchmark is intentionally **source-specific**. It gives strong regression coverage for the portfolio document, not proof that all PDF families are solved.

## Output

Automatic canonical structure is stored separately from manual correction state. The resolved structure is the input to Stage 5 semantic chunking.
