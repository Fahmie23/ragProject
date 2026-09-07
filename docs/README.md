# Project Documentation

This directory documents the **current frozen system**, not every implementation patch that led to it.

The project was developed incrementally through Stages 3–15. Detailed patch-by-patch notes, UI repair logs, and intermediate benchmark repair documents were intentionally consolidated for the portfolio repository. Git history remains the source for development chronology.

## Start here

| Area | Document | What it explains |
|---|---|---|
| Architecture | [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md) | End-to-end pipeline and trust boundaries |
| Architecture | [`architecture/DATABASE.md`](architecture/DATABASE.md) | PostgreSQL/pgvector persistence and experiment history |
| Document processing | [`document-processing/EXTRACTION_AND_STRUCTURE.md`](document-processing/EXTRACTION_AND_STRUCTURE.md) | Extraction, layout evidence, canonical semantics and golden validation |
| Document processing | [`document-processing/HUMAN_REVIEW.md`](document-processing/HUMAN_REVIEW.md) | Non-destructive correction workflow |
| Document processing | [`document-processing/SEMANTIC_CHUNKING.md`](document-processing/SEMANTIC_CHUNKING.md) | Frozen Stage 5 `semantic-v2.1` retrieval units |
| Retrieval | [`retrieval/RETRIEVAL_ARCHITECTURE.md`](retrieval/RETRIEVAL_ARCHITECTURE.md) | BGE-M3, PostgreSQL FTS, weighted RRF and BGE reranking |
| Retrieval | [`retrieval/STRUCTURE_AWARE_CONTEXT.md`](retrieval/STRUCTURE_AWARE_CONTEXT.md) | Bounded one-hop evidence expansion |
| Generation | [`generation/GROUNDED_GENERATION.md`](generation/GROUNDED_GENERATION.md) | Evidence-bound answers and abstention |
| Generation | [`generation/DETERMINISTIC_CITATIONS.md`](generation/DETERMINISTIC_CITATIONS.md) | Deterministic provenance and citation validation |
| Evaluation | [`evaluation/RETRIEVAL_BENCHMARK.md`](evaluation/RETRIEVAL_BENCHMARK.md) | 40-question retrieval benchmark and final held-out results |
| Evaluation | [`evaluation/ANSWER_CITATION_EVALUATION.md`](evaluation/ANSWER_CITATION_EVALUATION.md) | Independent 18-question answer/citation held-out evaluation |
| Evaluation | [`evaluation/CONTROLLED_EXPERIMENTS.md`](evaluation/CONTROLLED_EXPERIMENTS.md) | Stage 15 experiment policy and `candidate_k` findings |
| Frontend | [`frontend/RAG_WORKBENCH_UI.md`](frontend/RAG_WORKBENCH_UI.md) | Product navigation and inspection surfaces |
| Frontend | [`frontend/RESPONSIVE_AND_ACCESSIBILITY.md`](frontend/RESPONSIVE_AND_ACCESSIBILITY.md) | UI robustness/accessibility contract |
| Deployment | [`deployment/DOCKER_REPRODUCIBILITY.md`](deployment/DOCKER_REPRODUCIBILITY.md) | Reproducible Compose stack and verification |
| Development | [`development/LOCAL_SETUP.md`](development/LOCAL_SETUP.md) | WSL/local setup and daily commands |
| Scope | [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) | Explicit boundaries and known failure modes |

## Documentation policy

Keep a document when it explains an enduring architecture decision, public contract, evaluation method, reproducibility rule, or known limitation. Small bug fixes and migration chronology should normally live in Git history rather than creating another permanent Markdown file.
