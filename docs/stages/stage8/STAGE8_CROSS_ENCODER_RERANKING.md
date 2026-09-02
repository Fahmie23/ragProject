# Stage 8 — Cross-Encoder Reranking

## Goal

Stage 8 adds a learned relevance model after candidate retrieval without changing the frozen Stage 5 chunks, Stage 6 BGE-M3 embeddings, or Stage 7.1 lexical formulation.

```text
Query
  │
  ├── BGE-M3 exact cosine Top-20 ───────────┐
  │                                         │
  └── PostgreSQL FTS Top-20 ────────────────┤
                                            ▼
                                  deduplicated candidate union
                                     (at most 40 chunks)
                                            │
                                            ▼
                              BAAI/bge-reranker-v2-m3
                                  query + chunk cross-encoder
                                            │
                                            ▼
                                          Top-5
```

The reranker is intentionally applied to the **full union**, not Hybrid Top-5. The Stage 7.1 Appendix smoke case demonstrated why: an answer-bearing table can remain in Dense Top-20 while falling outside the final RRF Top-5.

## Model and lifecycle

Defaults:

```text
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_DEVICE=auto
RERANKER_BATCH_SIZE=2
RERANKER_MAX_LENGTH=1024
```

The `CrossEncoder` is lazy-loaded on the first Stage 8 request and cached per `(model, resolved_device, max_length)` for reuse in the same Python process. `auto` prefers CUDA and falls back to CPU; explicit `cuda`/`cuda:N` fails clearly if unavailable.

Stage 8 checks the exact reranker tokenizer count for every query+passage pair before scoring. If any pair exceeds the configured 1024-token limit, the endpoint returns HTTP 409 with `reranker_input_too_long`; it does not silently truncate.

## Candidate trace

RRF is no longer the final ranking signal, but it remains useful for traceability and deterministic tie-breaking. Every reranked hit includes:

```text
reranker_score             cross-encoder relevance score returned by `CrossEncoder.predict()` and used for ordering
hybrid_candidate_rank      candidate's RRF rank before reranking
fusion_score               RRF score
dense_rank / dense_score
lexical_rank / lexical_score
lexical_matched_term_count / lexical_term_coverage
pages / section_path / source_element_ids
```

`reranker_score` is deliberately treated as an opaque, uncalibrated relevance score. `sentence-transformers` may apply the model's configured/default activation inside `CrossEncoder.predict()`, so Stage 8.1 does not apply another sigmoid or expose a second "normalized" value. This cleanup changes score semantics only; it does not change candidate generation or ranking.

## Stage 8.1 score-semantics cleanup

Stage 8.1 removes the redundant `reranker_normalized_score` field. The API, smoke-test report, and frontend now expose only `reranker_score`, exactly as returned by `CrossEncoder.predict()`. This prevents accidental double activation and avoids presenting an uncalibrated ranking score as a probability. No retrieval results need to be regenerated solely because of this cleanup: ordering is still based on the same model score.

## API

```text
POST /api/retrieval/hybrid-rerank
GET  /api/system/reranker
```

Example request:

```json
{
  "document_id": "<document-id>",
  "query": "What information must be reported when there is a positive match with a designated person?",
  "top_k": 5,
  "candidate_k": 20,
  "rrf_k": 60,
  "dense_weight": 1.0,
  "lexical_weight": 1.0,
  "embedding_model": "BAAI/bge-m3",
  "embedding_device": "auto",
  "reranker_model": "BAAI/bge-reranker-v2-m3",
  "reranker_device": "auto"
}
```

## Frontend

The RAG Playground now has three live strategies:

```text
Dense
Hybrid
Hybrid + Reranker
```

For reranked results it shows the final reranker score plus Dense rank, Lexical rank, pre-rerank Hybrid candidate rank, candidate union size, model, device, and lexical query plan.

## Verification

The exact same five smoke questions used by Dense and Hybrid are retained. Do not alter them to make Stage 8 look better.

```bash
cd backend
python scripts/test_reranked_retrieval_behaviors.py
```

Outputs:

```text
reranked_retrieval_results_stage8/
├── 01_definition_pep.txt
├── 02_delayed_verification.txt
├── 03_non_face_to_face.txt
├── 04_verification_timeout.txt
├── 05_positive_designated_person_match.txt
└── all_reranked_retrieval_results_stage8.txt
```

The first local execution downloads the reranker model if it is not already in the Hugging Face cache. Subsequent requests in the same backend process reuse the loaded model.

## Evaluation rule

Stage 8 is accepted or rejected based on the same evidence targets as earlier stages. In particular:

- preserve the strong PEP / delayed-verification / non-face-to-face cases;
- preserve Stage 7.1's improvement on the verification-timeout paraphrase;
- test whether the reranker recovers the Appendix I answer-bearing table from the union.

The five-question smoke suite is diagnostic only. Final portfolio metrics still require the larger curated evaluation set.
