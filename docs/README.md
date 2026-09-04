# Project Documentation

All detailed project documentation lives under `docs/`. The repository root intentionally keeps only the main `README.md` as the public project entry point.

## Structure

```text
docs/
├── README.md
├── architecture/
│   └── system and storage architecture
├── evaluation/
│   └── retrieval benchmark policy, results, and controlled experiment findings
├── frontend/
│   └── UI/UX, workbench, responsive, and frontend repair notes
├── development/
│   └── local setup and development environment guides
├── stages/
│   ├── stage3/
│   ├── stage4/
│   ├── stage5/
│   ├── stage6/
│   ├── stage7/
│   ├── stage8/
│   ├── stage9/
│   ├── stage10/
│   ├── stage11/
│   ├── stage12/
│   ├── stage13/
│   ├── stage14/
│   └── stage15/
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

### Stages 8–10

- `docs/stages/stage8/` — cross-encoder reranking and bounded structure-aware context assembly.
- `docs/stages/stage9/` — grounded answer generation and abstention.
- `docs/stages/stage10/` — deterministic citation/provenance construction.

### Stage 11

See `docs/stages/stage11/` for the frozen answer/citation evaluation methodology,
independent held-out benchmark, human semantic review, and final metrics.

### Stages 12–13

- `docs/stages/stage12/` — automated/system verification of the frozen RAG pipeline.
- `docs/stages/stage13/` — Docker/Compose reproducibility and GPU-runtime verification.

### Stage 14

See `docs/stages/stage14/` for the RAG Playground, retrieval/context inspector,
deterministic citation provenance explorer, benchmark-report implementation, and
cross-app UI audit.

### Stage 15

See `docs/stages/stage15/` for the controlled experiment charter, experiment
isolation rules, storage/config contracts, and portfolio-finalization plan.

### Evaluation

- `evaluation/RETRIEVAL_EVALUATION_DATASET_V1.md` — formal 40-question retrieval dataset and split policy.
- `evaluation/RETRIEVAL_EVALUATION_RUNNER_V1.md` — protected DEV/held-out retrieval runner.
- `evaluation/RETRIEVAL_V1_FINAL_BENCHMARK.md` — frozen 15-question held-out Retrieval-v1 results and limitations.
- `evaluation/STAGE15_RETRIEVAL_EXPERIMENT_FINDINGS.md` — DEV-only `candidate_k` ablation and engineering interpretation.

### Development

See `docs/development/` for WSL, Docker Desktop, PostgreSQL/pgvector, and local
development setup procedures.
