# Stage 8.2 — Structure-Aware Evidence Expansion

## Decision

Stage 8.1 ranking is frozen. Stage 8.2 does **not** modify Dense, PostgreSQL FTS, RRF, candidate K, BGE-M3 embeddings, or BGE reranker ordering.

The development benchmark exposed a different failure mode: a highly relevant seed chunk was ranked correctly, while structurally dependent evidence (a continuation list item, an attached table, or explicitly introduced child units) did not independently appear in Top-10.

Therefore Stage 8.2 adds a separate **context assembly** layer after reranking.

## Pipeline

```text
Query
  ↓
Dense Top-20 + Lexical Top-20
  ↓
BGE reranker
  ↓
Raw ranked hits                ← Hit@K / Recall@K / MRR remain here
  ↓
structural_one_hop_v1
  ↓
Assembled context              ← ContextRecall@K / ContextCompleteEvidence@K
```

## Bounded deterministic rules

Expansion is query-agnostic and never reads evaluation gold labels.

A ranked seed may attach only:

1. **following_table** — an immediately following table in the same section;
2. **continuation_list_item** — an immediately following list item when the seed visibly ends with `and` or `or`;
3. **introduced_child** — up to two immediate non-clause children after an explicit introducing statement such as `... entails two assessments:`;
4. **preceding_intro** — the immediately preceding introducing clause when the ranked seed itself is a table/list/mixed/subclause.

Guards:

- same `section_path` required;
- maximum page gap = 1;
- maximum forward neighbors per seed = 2;
- maximum backward neighbors per seed = 1;
- non-recursive / one-hop only;
- maximum assembled context chunks = 30;
- expanded chunks never receive a retrieval rank.

## Metrics

Raw ranking metrics are unchanged:

- Hit@K
- Recall@K
- MRR@10
- CompleteEvidence@K

Stage 8.2 adds:

- ContextRecall@K
- ContextCompleteEvidence@K
- average context chunk count at K

A context chunk is considered available at K only when its `source_rank <= K`. For example, if rank-1 chunk 242 structurally attaches chunk 243, both are available to `ContextRecall@1`, but chunk 243 is **not** treated as retrieval rank 2.

## Evaluation status

`retrieval_config_v1.json` is intentionally `status: draft` for Stage 8.2 development evaluation, while `ranking_config_status` remains `frozen` for Stage 8.1. The held-out split stays blocked until Stage 8.2 DEV context metrics are reviewed and accepted.

## Live API

`POST /api/retrieval/hybrid-rerank-context`

The response contains the unchanged `hits` list plus `context_chunks`, each with:

- `source_rank`
- `ranked_seed_rank` (when it was also a raw ranked hit)
- structural `reasons`
- `attached_from_chunk_ids`
- full chunk provenance

## Frontend

The RAG Playground's **Hybrid + Reranker** path now uses the context endpoint. Ranked evidence and Stage 8.2 assembled context are displayed separately so the UI does not imply that attached chunks were independently ranked.
