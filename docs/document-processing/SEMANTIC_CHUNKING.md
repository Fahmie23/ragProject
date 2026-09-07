# Semantic Chunking and Retrieval Preparation

## Frozen strategy

The accepted Stage 5 artifact uses strategy version:

```text
semantic-v2.1
```

For the portfolio benchmark it produces **284 frozen chunks** used by Retrieval v1.

Stage 5 is deterministic. It does not ask an LLM to decide chunk boundaries.

## Inputs and eligibility

Stage 5 consumes the resolved canonical structure after blocking integrity checks pass. It separates answer-bearing body content from navigation/noise while preserving provenance.

## Retrieval-unit design

The chunker groups content according to canonical semantics rather than applying only a fixed-character window:

- definitions keep term/definition ownership;
- clauses/subclauses retain dependency context;
- list members can stay attached to introducing content;
- tables preserve structured answer-bearing text;
- meaningful figures/captions can be retained;
- local `group_header` labels are normally retrieval **context**, not standalone answer chunks;
- repetitive navigation/header/footer material is excluded from retrieval units.

Each chunk separates:

```text
content_text   answer-bearing content
context_text   local structural label/scope when useful
text           retrieval representation
```

## Provenance

Chunks retain the lineage needed by deterministic citations and later audits, including:

- page numbers;
- canonical `source_element_ids`;
- `context_element_ids`;
- Stage 3 span/block/table IDs;
- relationship IDs;
- semantic type and section path;
- split part/total when a unit must be divided.

## Quality guards

The final Stage 5 repairs focus on retrieval quality rather than cosmetic formatting:

- no navigation leakage;
- no orphan/dangling dependency units;
- no standalone local group-header chunks unless genuinely answer-bearing;
- non-explanatory figure shells are suppressed;
- local group scope stops before unrelated numbered clauses;
- context differences form a packing boundary;
- resolved section hierarchy can supply a conservative group-scope fallback if a redundant local edge was removed by review resolution.

## Token sizing

Stage 5 uses deterministic token estimates for packing, but model-specific compatibility belongs to Stage 6. Before embedding, BGE-M3's real tokenizer and `max_seq_length` validate every final chunk. Overlong inputs fail rather than being knowingly silently truncated.

## Invalidation

The chunk artifact is fingerprinted against its upstream resolved structure. When Stage 4/4.5 changes, stale Stage 5 artifacts and corresponding database rows/embeddings must not remain valid.

## Why this matters

Retrieval quality depends on whether answer-bearing evidence is represented as coherent units. The project therefore treats semantic chunking as its own tested architecture layer rather than a utility call hidden behind the embedding framework.
