# Retrieval Architecture

## Frozen Retrieval v1

Retrieval v1 combines complementary dense and lexical candidate generation, rank-level fusion and a cross-encoder reranker.

```text
Query
 │
 ├─ BGE-M3 query embedding ────────> pgvector exact cosine Top-20
 │
 └─ PostgreSQL FTS content terms ─> lexical Top-20
                 │
                 └──────────────┬──────────────┘
                                ↓
                         weighted RRF union
                                ↓
                    BGE reranker v2-m3
                                ↓
                          ranked evidence
```

## Dense retrieval

- Model: `BAAI/bge-m3`
- Vectors: normalized
- Persistence/search: PostgreSQL + pgvector
- Baseline: exact cosine
- Device: `auto`, `cpu`, `cuda`, or `cuda:N`

Embedding generation and dense query encoding validate the selected model's exact tokenizer limit before inference. Explicit CUDA requests fail clearly if CUDA is unavailable; CUDA OOM is not silently converted to CPU.

## Lexical retrieval

The sparse side is PostgreSQL full-text search using the `english` configuration.

Natural-language questions are converted into deterministic OR-oriented content terms:

```text
question
 ↓
remove question scaffolding / duplicates
 ↓
content terms
 ↓
to_tsquery('english', 'term1 | term2 | ...')
```

Lexical candidates are ordered by matched-term coverage with `ts_rank_cd` as a ranking signal/tie-breaker. Candidate traces expose the retained terms, matched-term count and term coverage.

This system is **not BM25** and should not be described as BM25.

## Reciprocal Rank Fusion

Dense and lexical score scales are not directly comparable. Retrieval v1 therefore fuses rank positions:

```text
RRF(chunk) = dense_weight   / (rrf_k + dense_rank)
           + lexical_weight / (rrf_k + lexical_rank)
```

Frozen defaults:

```text
candidate_k    20 per retriever
rrf_k          60
dense_weight   1.0
lexical_weight 1.0
```

A candidate can survive from only one retriever; the union is deduplicated before reranking.

## Cross-encoder reranking

Model: `BAAI/bge-reranker-v2-m3`.

The reranker scores the full deduplicated candidate union rather than only the already-truncated Hybrid Top-K. This preserves the opportunity for a dense-only or lexical-only relevant candidate to move upward.

RRF scores remain diagnostic metadata. The cross-encoder score determines final ordering. Reranker scores are ranking signals, not calibrated correctness probabilities.

## Production seed budget

The production generation path uses the top **5 reranked seeds**. Stage 8.2 may attach bounded structural evidence after ranking; attached context does not retroactively change the retrieval ordering.

## Same-execution trace

The generation response can include `retrieval_trace_v1` copied from the same production execution:

1. dense candidates;
2. lexical candidates;
3. fused candidates;
4. full reranker order;
5. top-k seed IDs;
6. structure-attached context IDs.

Opening the frontend retrieval inspector does not trigger a second retrieval run.

## APIs

```text
POST /api/retrieval/dense
POST /api/retrieval/lexical
POST /api/retrieval/hybrid
POST /api/retrieval/hybrid-rerank
POST /api/retrieval/hybrid-rerank-context
```

The production cited-answer route owns its retrieval configuration; experimental controls do not mutate it.
