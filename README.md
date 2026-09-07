# RAG Document Intelligence Workbench

An end-to-end RAG engineering portfolio project for a complex Malaysian regulatory PDF. The system makes document structure, retrieval, context, grounded generation and citation provenance inspectable rather than treating RAG as a single black-box framework call.

## What this project demonstrates

- deterministic PDF extraction and canonical semantic reconstruction;
- non-destructive human correction before retrieval;
- structure-aware semantic chunking (`semantic-v2.1`);
- BGE-M3 dense retrieval with PostgreSQL/pgvector;
- PostgreSQL full-text lexical retrieval + weighted Reciprocal Rank Fusion;
- BGE cross-encoder reranking;
- bounded structure-aware context expansion;
- evidence-bound answer generation and explicit abstention;
- deterministic source citations back to the PDF;
- protected DEV/held-out evaluation and reproducible offline scoring;
- isolated controlled retrieval experiments without retuning the frozen production profile.

## Benchmark scope

The primary benchmark is the 109-page Securities Commission Malaysia AML/CFT/CPF guideline.

```text
Stage 5 corpus                  284 chunks (`semantic-v2.1`)
Formal retrieval benchmark      40 questions (25 DEV + 15 held-out)
Answer/citation held-out         18 questions (15 answerable + 3 controls)
```

These are document/domain-specific portfolio results, **not** claims of universal performance on arbitrary PDFs.

## Architecture

```text
PDF
 ↓
Deterministic extraction
 ↓
Canonical semantic structure
 ↓
Human review / corrections
 ↓
Semantic chunking
 ↓
BGE-M3 dense retrieval ─────┐
                            ├─ weighted RRF → BGE reranker
PostgreSQL FTS lexical ─────┘
                                    ↓
                         bounded structural context
                                    ↓
                         grounded answer generation
                                    ↓
                         deterministic citations
                                    ↓
                         PDF provenance / inspection
```

Production Retrieval v1 is frozen at:

```text
embedding       BAAI/bge-m3
lexical         PostgreSQL FTS, OR content terms v1
fusion          RRF k=60, dense=1.0, lexical=1.0
candidate_k     20 per retriever
reranker        BAAI/bge-reranker-v2-m3
seed top_k      5
context         structural_one_hop_v1
```

PostgreSQL FTS is intentionally **not** labelled BM25.

## Retrieval held-out results

| Metric | Dense | Hybrid | Hybrid + Reranker |
|---|---:|---:|---:|
| Hit@1 | 66.7% | 60.0% | **86.7%** |
| Hit@5 | 73.3% | **93.3%** | **93.3%** |
| Recall@5 | 70.0% | **90.0%** | 86.7% |
| MRR@10 | 0.7225 | 0.7189 | **0.8800** |
| CompleteEvidence@5 | 66.7% | **86.7%** | 80.0% |

Stage 8.2 context assembly reached **ContextRecall@5 90.0%** and **ContextCompleteEvidence@5 86.7%**.

The result shows different roles for each layer: Hybrid improves candidate/evidence coverage; reranking strongly improves the ordering of the best evidence.

## Answer & citation held-out results

| Metric | Result |
|---|---:|
| Answer status accuracy | **94.44%** |
| Claim citation coverage | **100.00%** |
| Deterministic citation validity | **100.00%** |
| Required source coverage | **93.33%** |
| Fully supported claims | **95.83%** |
| Unsupported claims | **0.00%** |
| Citation entailment | **93.88%** |
| Answer completeness | **83.65%** |

The dominant remaining weakness is **completeness**, not unsupported hallucination. A grounded answer can still omit required information.

## Controlled experiment

Stage 15 varied only `candidate_k` on the existing 25-question DEV split while keeping Retrieval v1 frozen.

| candidate_k | Hit@1 | Recall@5 | MRR@10 | CompleteEvidence@5 | Avg request ms |
|---:|---:|---:|---:|---:|---:|
| 10 | 96.0% | 93.3% | 0.9800 | 88.0% | 844.1 |
| 20 | 96.0% | 93.3% | 0.9800 | 88.0% | 1302.3 |
| 40 | 96.0% | 93.3% | 0.9800 | 88.0% | 2131.0 |

Top-5 quality was unchanged while candidate volume/runtime increased. This is DEV-only engineering evidence; production remains frozen at `candidate_k=20`.

## RAG Workbench UI

The visible product workflow is intentionally compact:

```text
Overview | Documents | RAG Playground
```

The Playground provides cited answers, validated source cards, a same-execution retrieval/context inspector and a deterministic citation provenance drawer. The document-specific benchmark UI remains preserved internally but is not presented as a live quality score for arbitrary uploads.

## Quick start with Docker

```bash
# repository root
cp docker.env.example .env
# add required local secrets/config without committing .env

docker compose up -d --build
```

```text
Frontend  http://localhost:5173
Backend   http://localhost:8000
Health    http://localhost:8000/health
```

For WSL/local development, database migration and GPU setup, see [`docs/development/LOCAL_SETUP.md`](docs/development/LOCAL_SETUP.md).

## Verification

```bash
cd backend
python -m pytest -q

cd ../frontend
npm run build
```

The repository also contains protected Stage 11/12/13 reproduction and system-verification scripts under `backend/scripts/`.

## Documentation

The portfolio documentation is intentionally consolidated around the **current architecture** rather than retaining one Markdown file for every historical patch.

Start with [`docs/README.md`](docs/README.md), especially:

- [`System Architecture`](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [`Extraction and Canonical Structure`](docs/document-processing/EXTRACTION_AND_STRUCTURE.md)
- [`Semantic Chunking`](docs/document-processing/SEMANTIC_CHUNKING.md)
- [`Retrieval Architecture`](docs/retrieval/RETRIEVAL_ARCHITECTURE.md)
- [`Deterministic Citations`](docs/generation/DETERMINISTIC_CITATIONS.md)
- [`Retrieval Benchmark`](docs/evaluation/RETRIEVAL_BENCHMARK.md)
- [`Answer & Citation Evaluation`](docs/evaluation/ANSWER_CITATION_EVALUATION.md)
- [`Controlled Experiments`](docs/evaluation/CONTROLLED_EXPERIMENTS.md)
- [`Known Limitations`](docs/KNOWN_LIMITATIONS.md)

## Repository layout

```text
ragProject/
├── backend/       FastAPI, document pipeline, retrieval, generation, evaluation
├── frontend/      React/Vite RAG Workbench
├── docs/          consolidated current-state engineering documentation
├── evaluation/    compact committed Stage 15 experiment evidence
├── docker-compose.yml
└── docker.env.example
```

## Key limitations

- Benchmarks are specific to the frozen SC AML/CFT PDF/domain.
- OCR/general arbitrary-PDF ingestion is not solved by this portfolio version.
- Exact cosine retrieval is appropriate for the 284-chunk benchmark, not evidence of internet-scale vector search.
- Bounded one-hop context can miss required distant evidence.
- Final answer completeness is lower than grounding/citation validity.
- CI/CD and multi-tenant production serving are outside scope.

See [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) for the full boundary.
