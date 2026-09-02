# Stage 7 / 7.1 — Hybrid Retrieval and Live RAG Playground

## Goal

Stage 7 adds a reproducible hybrid retrieval baseline without changing the frozen Stage 5 chunks or Stage 6 BGE-M3 vectors.

```text
Query
  │
  ├── BGE-M3 dense query embedding ──> pgvector exact cosine Top-N
  │
  └── PostgreSQL full-text search ────> ts_rank_cd lexical Top-N
                    │
                    └──────────────┬───────────────┘
                                   ▼
                      weighted Reciprocal Rank Fusion
                                   │
                                   ▼
                               final Top-K
```

## Why Reciprocal Rank Fusion

Cosine similarity and PostgreSQL full-text ranking scores are produced by different scoring systems. They should not be added directly without calibration. Stage 7 therefore fuses **rank positions**, using weighted Reciprocal Rank Fusion (RRF):

```text
score(chunk) = dense_weight / (rrf_k + dense_rank)
             + lexical_weight / (rrf_k + lexical_rank)
```

Defaults:

```text
Top K          = 5
Candidate K    = 20 per retriever
RRF K          = 60
Dense weight   = 1.0
Lexical weight = 1.0
```

A chunk can be present in only one candidate list; it is not discarded merely because the other retriever did not return it.

## Lexical baseline and Stage 7.1 correction

The original Stage 7 lexical baseline passed the entire natural-language question to `websearch_to_tsquery`. The fixed five-query smoke suite showed that this was too strict for paraphrased questions: correct dense candidates often received no lexical rank at all.

Stage 7.1 keeps PostgreSQL FTS but makes candidate generation deterministic and inspectable:

```text
Natural-language question
        ↓
remove question scaffolding / duplicate terms
        ↓
OR-oriented content terms
        ↓
to_tsquery('english', 'term1 | term2 | ...')
        ↓
to_tsvector('english', chunk.text) @@ query
        ↓
rank by matched query-term count
        ↓
ts_rank_cd(...) as the tie-break ranking signal
```

For example:

```text
What are the requirements for delayed verification?
        ↓
requirements | delayed | verification
```

The lexical trace exposes the retained terms and generated tsquery. Each lexical candidate also reports `matched_term_count` and `term_coverage`. This is still **not labelled BM25**. It remains a PostgreSQL FTS baseline using English stemming and `ts_rank_cd`; Stage 7.1 only corrects natural-language lexical candidate generation.

For the current controlled 284-chunk benchmark, the tsvector is evaluated at query time. A generated/persisted tsvector column and GIN index should be introduced only when corpus scale justifies it.

## API

### Dense baseline

```text
POST /api/retrieval/dense
```

### Lexical diagnostic endpoint

```text
POST /api/retrieval/lexical
```

The lexical endpoint is useful for debugging the sparse side independently. It does not require query embedding generation.

### Hybrid retrieval

```text
POST /api/retrieval/hybrid
```

Example:

```json
{
  "document_id": "<document-id>",
  "query": "What are the requirements for delayed verification?",
  "top_k": 5,
  "candidate_k": 20,
  "rrf_k": 60,
  "dense_weight": 1.0,
  "lexical_weight": 1.0,
  "embedding_model": "BAAI/bge-m3",
  "embedding_device": "auto"
}
```

Each hybrid hit exposes enough trace data to explain why it ranked where it did:

```text
rank
fusion_score
dense_rank
dense_score
dense_distance
dense_rrf_score
lexical_rank
lexical_score
lexical_matched_term_count
lexical_term_coverage
lexical_rrf_score
chunk metadata + provenance
```

## Frontend

The global **RAG Playground** is now live for retrieval rather than a mock preview.

Implemented strategies:

```text
Dense   ✅ live
Hybrid  ✅ live
Hybrid + Reranker  ✅ connected by Stage 8 (see `docs/stages/stage8/STAGE8_CROSS_ENCODER_RERANKING.md`)
```

The Playground provides:

- document selection
- query input
- Top-K control
- Candidate-K control for hybrid retrieval
- top evidence cards
- page / section / semantic-type provenance
- dense similarity scores
- hybrid dense rank + lexical rank + fusion score
- Stage 7.1 lexical query plan (`OR` terms)
- lexical matched-term coverage per candidate
- expandable retrieval trace

Answer generation remains intentionally disconnected. The evidence panel displays retrieved chunk content rather than a fabricated generated answer.

## Verification — same smoke test as dense retrieval

The exact same five questions are used for dense and hybrid retrieval so the benchmark does not move between strategies:

1. PEP definition
2. delayed-verification requirements
3. long non-face-to-face clause
4. paraphrased verification-timeout query
5. Appendix I positive-match reporting form

Dense runner:

```bash
cd backend
python scripts/test_dense_retrieval_behaviors.py
```

Combined output:

```text
retrieval_results/all_dense_retrieval_results.txt
```

Hybrid runner:

```bash
cd backend
python scripts/test_hybrid_retrieval_behaviors.py
```

Stage 7.1 combined output:

```text
hybrid_retrieval_results_stage7_1/all_hybrid_retrieval_results_stage7_1.txt
```

The hybrid report records the same chunk/provenance fields plus the normalized lexical query, retained terms, dense rank, lexical rank, matched-term coverage, component RRF contributions, and final fusion score. Keep the previous Stage 7 report when comparing the query-construction correction.

## Evaluation rule

Stage 7.1 deliberately does **not** change `dense_weight`, `lexical_weight`, `rrf_k`, Stage 5 chunks, or the smoke-test questions. This isolates the effect of lexical query construction.

Do not tune Stage 5 or change the smoke-test questions simply to make hybrid look better. Preserve the dense baseline and compare the exact same evidence targets. Formal Recall@K and MRR should be reported only after the larger golden retrieval dataset is curated.

## Stage boundary

Stage 7 stops at hybrid candidate ranking. It does **not** add a cross-encoder reranker or LLM answer generation. Those remain separate stages so their incremental benefit can be measured.
