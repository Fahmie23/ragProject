# Stage 5 — Retrieval Preparation & Semantic Chunking

## Purpose

Stage 5 turns the trusted Stage 4.5 **Resolved JSON** into retrieval-ready chunks. It does not delete or rewrite source evidence. The resolved artifact remains the complete trusted document; Stage 5 creates a separate retrieval view.

```text
Resolved Stage 4.5 JSON
        ↓
5.1 Eligibility gate
        ↓
5.2 Retrieval cleaning
        ↓
5.3 Semantic unit building
        ↓
5.4 Dependency / continuation refinement
        ↓
5.5 Semantic packing + context injection
        ↓
5.6 Hard size enforcement
        ↓
5.7 Deterministic quality validation
        ↓
data/chunks/{document_id}.json
```

## Eligibility

Stage 5 requires:

- a saved `ResolvedStructureArtifact`;
- `resolved.integrity.status == "pass"`;
- `resolved.review.stage5_eligible == true`.

Review now supports **Finalize review** with zero corrections. This is necessary when Stage 4 is already correct: the user can validate the automatic structure and create the resolved artifact without manufacturing a fake correction.

## Cleaning policy

Cleaning is retrieval filtering, not source deletion. Every canonical element receives an auditable decision:

- `include` — eligible retrieval content;
- `context` — retained as structural context but not emitted as standalone content;
- `exclude` — omitted from retrieval with an explicit reason.

Implemented deterministic rules include:

- empty content;
- page headers;
- page footers;
- standalone page numbers near page margins;
- repeated text detected in page margins across configurable minimum pages;
- exact same-page text whose bounding boxes overlap by at least 90%;
- optional footnote exclusion;
- optional document-metadata exclusion;
- section headers as context-only;
- textless figures excluded until image semantic extraction exists;
- navigation-only tables/paragraphs under conservative `Contents`, `Table of Contents`, or `Index` section ancestry in Semantic v2.

Whitespace normalization is enabled by default. Line-break dehyphenation is opt-in because genuine compounds such as `anti-money` are ambiguous without lexical knowledge.

## Semantic grouping and deterministic refinement

`semantic_v2` is the default strategy. `semantic_v1` remains available as a legacy comparison baseline. Semantic v2 is deliberately document-structure driven: it contains no AML/CDD/PEP-specific vocabulary and no fixed page or clause numbers.

Semantic v2 adds generic parent/dependent-child grouping, explicit continuation merging, conservative short standalone-clause packing, contextual note attachment, parent-context repetition when oversized hierarchies are split, and row-aware table splitting.

### Definitions

`definition_term` + all associated `definition_text` elements are built as one semantic unit before size enforcement. Cross-page definitions remain one unit unless the hard maximum requires splitting. When split, definition/section context is repeated.

### Clauses and subclauses

A clause/subclause absorbs immediately following non-structural prose/list content until the next semantic boundary or section change.

### Tables

`LogicalTable.cells` is serialized from canonical table structure. Table boundaries do not depend on raw PDF block boundaries.

### Figures

Figure records combine any available figure text, introductions, captions, explanations, and source text. Purely visual figures are not retrieval chunks in this version because image semantic understanding is not yet implemented.

### Remaining content

Remaining paragraphs/list items/etc. are packed only within the same section context until the target size is reached.

## Token sizing

Default configuration:

```json
{
  "strategy": "semantic_v2",
  "soft_min_tokens": 100,
  "target_tokens": 450,
  "max_tokens": 700,
  "overlap_tokens": 60
}
```

Stage 5 v1 intentionally uses `regex_estimate_v1`, a deterministic token estimate with no external tokenizer dependency. The artifact records the method so later indexing can switch to a model-specific tokenizer without pretending the current values are exact.

`soft_min_tokens` is a review/packing signal rather than a hard floor; complete definitions and genuinely independent short statements may remain smaller. `max_tokens` remains a hard invariant.

## Provenance

Every chunk stores:

- document ID;
- chunk ID/index;
- semantic type;
- retrieval text and content/context split;
- estimated token count;
- page numbers;
- section path;
- canonical `source_element_ids`;
- `context_element_ids` when parent/header context is repeated without pretending it is primary evidence;
- `refinement_tags` describing deterministic repairs such as dependency grouping or table-row splitting;
- Stage 3 `source_span_ids`;
- Stage 3 `source_block_ids`;
- Stage 3 `source_table_ids`;
- relationship IDs;
- split part/total when an oversized unit was divided.

Chunk IDs are deterministic for the same source IDs + semantic type + text.

## Artifact invalidation

A Stage 5 artifact is invalidated when:

- Stage 3 is re-run;
- Stage 4 is re-run;
- Stage 4.5 corrections are saved/changed;
- Stage 4.5 is reset.

`GET /chunks` also checks the saved Stage 5 artifact against the current `resolved_at` and source SHA. A stale artifact is rejected rather than silently served.

## API

```text
POST   /api/documents/{document_id}/chunks
GET    /api/documents/{document_id}/chunks
DELETE /api/documents/{document_id}/chunks
```

POST body:

```json
{
  "config": {
    "strategy": "semantic_v1",
    "target_tokens": 450,
    "max_tokens": 700,
    "overlap_tokens": 60,
    "keep_definitions_together": true,
    "preserve_section_context": true,
    "preserve_cross_page_continuations": true,
    "cleaning": {
      "exclude_page_headers": true,
      "exclude_page_footers": true,
      "exclude_margin_page_numbers": true,
      "exclude_repeated_margin_text": true,
      "deduplicate_overlapping_text": true,
      "repeated_margin_min_pages": 3,
      "include_footnotes": true,
      "include_document_metadata": true,
      "include_figures_without_text": false,
      "normalize_whitespace": true,
      "dehyphenate_line_breaks": false
    }
  }
}
```

`semantic_v1` currently requires definition grouping and cross-page preservation. Textless figures are explicitly unavailable until image semantic extraction is implemented; the API rejects configurations that claim otherwise.

## UI

The Chunking tab contains four views:

1. **Overview** — eligibility, artifact metrics, semantic-v1 configuration and processing contract.
2. **Cleaning** — retrieval policy plus auditable excluded/context-only elements and reasons.
3. **Chunk Preview** — searchable/filterable chunk browser + inspector with provenance and an action to open the source page in Review.
4. **Chunk JSON** — inspect/copy/download the exact Stage 5 artifact.

The page is available after Stage 4 so a user can see the eligibility requirement even before Review has been finalized. Generation remains disabled until the backend eligibility gate is satisfied.

## Tests

Stage 5 tests cover:

- cleaning audit and context-only section headers;
- repeated margin noise;
- overlapping duplicate text;
- definition grouping + provenance;
- cross-page definition preservation;
- hard maximum splitting;
- deterministic chunk IDs;
- ineligible resolved structures;
- Stage 5 API generate/fetch/reset;
- zero-correction Review finalization.
