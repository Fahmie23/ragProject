# Project Documentation

All detailed project documentation lives under `docs/`. The repository root intentionally keeps only the main `README.md` as the public project entry point.

## Structure

```text
docs/
├── README.md
├── architecture/
│   └── system and storage architecture
├── frontend/
│   └── UI/UX, workbench, responsive, and frontend repair notes
├── development/
│   └── local setup and development environment guides
├── stages/
│   ├── stage3/
│   ├── stage4/
│   ├── stage5/
│   ├── stage6/
│   └── stage7/
└── audits/
    └── stage4/
        └── benchmark audits and post-stage repair reports
```

## Documentation conventions

- Keep only the main `README.md` at repository root.
- Put implementation documentation in the stage that owns it.
- Put UI/UX-specific notes in `docs/frontend/`.
- Put benchmark audits and retrospective repair reports in `docs/audits/`.
- Prefer updating an existing authoritative document over creating a new file for every small change.
- When a new document is necessary, use a descriptive lowercase or existing stage-prefixed filename and place it in the correct folder immediately.

## Main documentation areas

### Architecture

See `docs/architecture/` for system-level decisions such as PostgreSQL + pgvector persistence.

### Frontend

See `docs/frontend/` for the RAG Workbench UI/UX, document inspector, review interactions, and responsive behavior.

### Stage 3

See `docs/stages/stage3/` for extraction migration notes.

### Stage 4

See `docs/stages/stage4/` for canonical structure, semantic taxonomy, correction workflows, hierarchy, and golden specification documentation.

### Stage 4 audits

See `docs/audits/stage4/` for document-wide audits and regression repair reports.

### Stage 5

See `docs/stages/stage5/` for retrieval preparation and semantic chunking documentation.

### Stage 6

See `docs/stages/stage6/` for dense embedding generation, pgvector persistence, and the exact cosine-retrieval baseline.


### Stage 7

See `docs/stages/stage7/` for PostgreSQL full-text lexical retrieval, the Stage 7.1 OR-oriented lexical query correction, weighted Reciprocal Rank Fusion, hybrid retrieval APIs, the live RAG Playground, and dense-vs-hybrid smoke-test procedure.

### Development

See `docs/development/` for WSL, Docker Desktop, PostgreSQL/pgvector, and local development setup procedures.

## Stage 8

- `stages/stage8/STAGE8_CROSS_ENCODER_RERANKING.md` — candidate-union cross-encoder reranking, runtime controls, API trace, and fixed smoke verification.


- `evaluation/RETRIEVAL_EVALUATION_DATASET_V1.md` — formal retrieval evaluation dataset and metric policy.
- `evaluation/RETRIEVAL_EVALUATION_RUNNER_V1.md` — protected dev/held-out Dense vs Hybrid vs Reranker benchmark runner.
- `stages/stage8/STAGE8_2_STRUCTURE_AWARE_EVIDENCE_EXPANSION.md` — bounded post-reranking structural context assembly and context metrics.

- `stages/stage9/STAGE9_GROUNDED_ANSWER_GENERATION.md` — frozen Retrieval-v1 evidence → grounded claim generation + abstention.

- `evaluation/RETRIEVAL_V1_FINAL_BENCHMARK.md` — frozen 15-question held-out Retrieval-v1 results and known limitations.
