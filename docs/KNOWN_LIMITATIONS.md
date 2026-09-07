# Known Limitations and Scope Boundaries

## Portfolio scope

The project is deeply engineered around one 109-page Securities Commission Malaysia AML/CFT/CPF guideline. The structure benchmark, retrieval benchmark and final answer/citation metrics are therefore **document/domain-specific evidence**.

They do not demonstrate universal robustness on arbitrary PDFs.

## Document processing

- OCR is not part of the frozen portfolio path; scanned/poor-text PDFs need a separate OCR/generalized ingestion strategy.
- Canonical reconstruction still depends on usable text/geometry/reading order from the extraction/layout layers.
- The golden structure specification is anchor-based regression coverage, not complete manual annotation of every document element.
- Human review exists because ambiguous layout/semantic cases cannot always be resolved safely by deterministic rules.

## Retrieval scale

- The frozen corpus has 284 chunks. Exact pgvector cosine is sufficient for this controlled scale; the project does not claim large-corpus ANN performance.
- PostgreSQL FTS is evaluated at the project's current corpus scale. A persisted tsvector/GIN design would become relevant at larger scale.
- The lexical system uses PostgreSQL FTS and `ts_rank_cd`; it is not BM25.

## Retrieval completeness

- Reranking optimizes ordering but can move a required secondary evidence item outside the selected range.
- `structural_one_hop_v1` is deliberately bounded/non-recursive and cannot recover arbitrary distant dependencies.
- The frozen retrieval held-out set contains preserved failures (`RET-010`, `RET-031`) rather than benchmark-specific patches.

## Answer completeness

Stage 11 shows strong grounding/provenance but lower completeness (`83.65%` held-out). Some omissions are caused by missing context; others occur when the model receives relevant evidence but omits part of the required answer.

A valid citation is not the same as semantic entailment, and a grounded answer is not necessarily complete.

## External generation provider

Grounded generation depends on a configured external model provider/API. Deterministic extraction, retrieval benchmarking and frozen evaluation reproduction can run without making generation-provider calls, but fresh live answers need valid provider configuration.

## Experiment interpretation

Stage 15 `candidate_k` results are DEV-only retrospective evidence. They are not independent validation and do not prove that `candidate_k=10` is universally optimal. Reported request timing is endpoint duration, not a controlled reranker-only microbenchmark.

## UI/evaluation boundary

The benchmark report is intentionally hidden from primary product navigation because document-specific frozen metrics should not appear to be live quality scores for arbitrary uploads.

## Deployment

CI/CD and internet-scale serving are out of scope. The Docker stack targets reproducible local/portfolio deployment rather than production multi-tenant operations.
