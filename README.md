# RAG Document Intelligence Workbench

A portfolio-oriented RAG workbench for a complex Malaysian regulatory PDF. The project makes document extraction, canonical structure, human review, semantic chunking, hybrid retrieval, reranking, structure-aware context assembly, grounded generation, deterministic citations, evaluation, and controlled retrieval experiments inspectable end to end.

## Benchmark scope

The portfolio benchmark is intentionally document-specific:

- source: Securities Commission Malaysia AML/CFT/CPF Guidelines;
- PDF pages: 109;
- frozen Stage 5 corpus: `semantic-v2.1`, 284 chunks;
- formal retrieval benchmark: 40 questions (`25` DEV + `15` held-out);
- independent answer/citation held-out benchmark: 18 questions.

The project demonstrates a deeply engineered RAG pipeline for this document and benchmark. It does **not** claim universal robustness across arbitrary PDFs.


## Documentation

Detailed implementation notes, stage documentation, frontend UX notes, and audit reports are organized under [`docs/`](docs/README.md). The repository root intentionally keeps only this main `README.md`.

```text
docs/
├── architecture/
├── development/
├── evaluation/
├── frontend/
├── stages/
│   ├── stage3/
│   ├── stage4/
│   ├── stage5/
│   ├── stage6/
│   ├── stage7/
│   ├── stage8/
│   ├── ...
│   └── stage15/
└── audits/
    └── stage4/
```

## Current pipeline

```text
Document
   │
   ▼
1. Intake
   │  original file + SHA-256
   ▼
2. Validation & Classification
   │  format / PDF type / safety checks
   ▼
3. Deterministic Extraction
   │  PyMuPDF blocks / lines / spans / images / tables / coordinates
   ▼
4. Layout & Structure Reconstruction
   │  PyMuPDF4LLM Layout + canonical normalization
   ▼
4.5 Human Review & Layout Correction
   │  non-destructive bbox / semantic overrides
   ▼
Resolved Canonical Document JSON
   │
   ▼
5. Retrieval Preparation & Semantic Chunking
   │  deterministic cleaning + semantic refinement + quality validation
   ▼
Chunk JSON
   │
   ▼
6. Dense Embeddings + pgvector Retrieval
   │  normalized vectors + exact cosine Top-K baseline
   ▼
7. Hybrid Retrieval
   │  PostgreSQL FTS + weighted Reciprocal Rank Fusion
   ▼
8. Cross-Encoder Reranking
   │  Dense Top-20 + Lexical Top-20 union → BGE reranker
   ▼
8.2 Bounded Structure-Aware Context Assembly
   │  non-recursive one-hop structural evidence expansion
   ▼
9. Grounded Answer Generation
   │  evidence-bound claims + explicit abstention
   ▼
10. Deterministic Citations
    │  claim → evidence → frozen chunk → canonical structure → PDF locator
    ▼
11. Answer & Citation Evaluation
    │  deterministic metrics + frozen human semantic review
    ▼
12–13. System Verification & Reproducibility
    │  automated regression gates + Docker/pgvector/GPU runtime
    ▼
14. Portfolio RAG Playground
    │  cited answers + retrieval/context/provenance inspectors
    ▼
15. Controlled Retrieval Experiments
    │  isolated DEV-only experiments; production Retrieval v1 remains frozen
    ▼
Portfolio-ready RAG workbench
```

## Evaluation evidence

The project separates development data from held-out evaluation and does not retune
the frozen production profile from held-out results.

### Retrieval v1 held-out

| Strategy | Hit@1 | Hit@5 | Recall@5 | MRR@10 |
|---|---:|---:|---:|---:|
| Dense | 66.7% | 73.3% | 70.0% | 0.7225 |
| Hybrid | 60.0% | 93.3% | 90.0% | 0.7189 |
| Hybrid + Reranker | **86.7%** | **93.3%** | **86.7%** | **0.8800** |

Stage 8.2 bounded context assembly reached `ContextRecall@5 = 90.0%` and
`ContextCompleteEvidence@5 = 86.7%`.

### Answer & citation held-out

- Answer status accuracy: **94.4%**
- Claim citation coverage: **100%**
- Deterministic citation validity: **100%**
- Required source coverage: **93.3%**
- Fully supported generated claims: **95.8%**
- Citation entailment: **93.9%**
- Answer completeness: **83.7%**

These metrics are specific to the frozen benchmark for this document/domain; they
are not universal performance claims.

## Stage 4 design

Stage 4 now separates layout evidence from semantic meaning. PyMuPDF4LLM remains the layout provider, while the canonical semantic-v2 resolver owns ambiguous structural classification:

```text
PDF
  │
  ├─ Stage 3 raw extraction ----------------------┐
  │                                               │
  └─ PyMuPDF4LLM Layout                          │
       │                                          │
       ▼                                          │
  data/layout/{document_id}.json                 │
       │                                          │
       └──────────────┬───────────────────────────┘
                      ▼
             Initial canonical layout roles
                      │
                      ▼
             Semantic feature extraction
                      │
                      ▼
           Sequence/context resolver
                      │
                      ▼
             Heading scope resolver
                      │
                      ▼
          Specialized reconstruction
                      │
                      ▼
        data/structured/{document_id}.json
```

The vendor Layout output is intentionally persisted separately from our canonical schema. This gives us a stable internal contract for later RAG stages and a way to debug layout-model errors independently from our normalization logic.

## Canonical element types

```text
title
subtitle
document_metadata
section_header
group_header
clause
subclause
definition_term
definition_text
paragraph
list_item
table
figure
caption
page_header
page_footer
footnote
formula
unknown
```

Stage 4.4 also creates document-level logical records for definitions, clauses, appendices, cross-page tables, figures, and structural relationships. The canonical Stage 4 schema is `1.8`. Schema 1.8 preserves each vendor `layout_role`, adds `group_header`, and adds auditable semantic classification metadata (`confidence`, `evidence`, and alternatives).

PyMuPDF4LLM Layout currently exposes corresponding page box classes such as `text`, `picture`, `table`, `caption`, `title`, `section-header`, `page-header`, `page-footer`, `list-item`, `footnote`, and `formula`. These values are now retained as **layout evidence**, not treated as final semantic truth. Ambiguous structural text is resolved from numbering, geometry, typography, punctuation, proposition shape, neighboring elements, and marker sequences. See `docs/stages/stage4/STAGE4_6_SEMANTIC_V2_ARCHITECTURE.md` and `docs/stages/stage4/STAGE4_6_1_SEMANTIC_TAXONOMY.md`.

## Hierarchy evidence

For initial `section_header` candidates, heading level evidence is determined in this order:

1. PDF bookmark / TOC match
2. Explicit heading numbering such as `2.3.1`
3. Dominant font-size rank from Stage 3 spans
4. Unknown when no evidence exists

Semantic v2.1 then resolves local heading scope. TOC/numbering evidence is stronger than typography-only evidence, but no single source is treated as universal semantic truth. A weak heading immediately before a stronger outline heading can become `group_header` rather than an empty sibling section.

Semantic v2.2 is golden-benchmark driven. It adds local-scope repair for TOC-backed labels, appendix-boundary recovery when `APPENDIX X` is misread as a running page header, numbered-step clause recovery, explicit-item continuation guards, stronger list-family consistency, definition-item recovery with missing marker whitespace, and visible cover-title promotion. See `docs/stages/stage4/STAGE4_8_SEMANTIC_V2_2_GOLDEN_REPAIR.md`.

Semantic v2.3 completes semantic continuity and local hierarchy. It reconstructs same-unit layout splits, attaches dependent list items to clause/subclause/paragraph owners, represents parent-clause tails with `belongs_to`, preserves inherited-obligation and cascading-step subclause semantics, recognizes spaced alphanumeric clause numbers such as `6 A.1`, and demotes duplicate appendix descriptive-title sections to local `group_header` scope. See `docs/stages/stage4/STAGE4_9_SEMANTIC_V2_3_CONTINUITY_AND_HIERARCHY.md`.

The selected source is persisted as:

```json
{
  "heading_level": 2,
  "heading_level_source": "pdf_toc"
}
```

Semantic classification also persists deterministic support metadata. When alternatives exist, their scores are normalized into the remaining confidence mass, and unresolved hierarchy can lower confidence without changing the selected type. These values are review aids, not statistically calibrated probabilities.

## Canonical body text

The canonical body retains semantic content but deliberately excludes repetitive or non-body regions such as:

```text
page_header
page_footer
figure
```

Those elements remain present in the page element list for provenance and frontend inspection.

Tables use their structured cells and Markdown representation when available.

## Traceability

Every canonical element records both:

- the PyMuPDF4LLM Layout box that classified it
- overlapping Stage 3 raw block/table IDs

Example:

```json
{
  "source": {
    "layout_box_index": 3,
    "layout_box_class": "section-header",
    "stage3_block_ids": ["p1-b4"],
    "stage3_table_ids": []
  }
}
```

## Stage 4.5 human review

Stage 4.5 adds a non-destructive human correction layer before chunking. In the simplified 4.5.8.16 workflow, the active UI focuses on element correction and exact Stage 3 text-span reconstruction. When a semantic type needs a parent relation, the relevant selector appears contextually. For example, one or more `definition_text` elements can be assigned to an existing DefinitionEntry in one operation; the backend derives section and bidirectional membership fields automatically. Corrections are persisted independently of automatic Stage 4:

```text
data/structured/{document_id}.json   automatic Stage 4
data/corrections/{document_id}.json  manual operation log
data/resolved/{document_id}.json     automatic + manual corrections
```

For geometry-changing operations, corrected text is rebuilt from immutable Stage 3 spans inside the edited bounding box. If Stage 3 or Stage 4 is rerun, Stage 4.5 artifacts are invalidated rather than silently applied to stale element IDs.

The page navigator also accepts direct numeric input (`Page [85] / 118`) in addition to previous/next arrows.

Stage 4.5.1 adds a frontend-only **JSON Preview Sandbox**. It can load page-level Stage 3, automatic Stage 4, or resolved Stage 4.5 JSON into an editable JSON panel, validate it, render the supplied bounding boxes over the original PDF page, and compare the edited JSON against the loaded baseline. The sandbox never writes to the ingestion pipeline.

The Structured Document → Corrections inspector now has both **Operations** and **Correction JSON** views, while the full persisted correction artifact remains available under **JSON artifacts → Corrections**.

Stage 4.5.8.3 adds conservative repair for TOC rows where an uppercase heading and the following numbered entry were merged into one vendor table row. Stage 3 and Stage 4 viewers also expose optional overlay labels, and selecting a table opens a full row-level inspector with a suspicious-row warning. See `docs/stages/stage4/STAGE4_5_8_3_TOC_TABLE_ROW_REPAIR_AND_INSPECTOR.md`.

Stage 4.5.8.4 adds a safety guard around that repair: automatic TOC row splitting is allowed only on pages with an explicit heading-like `CONTENTS` / `TABLE OF CONTENTS` context. TOC-shaped tables elsewhere are preserved unchanged. See `docs/stages/stage4/STAGE4_5_8_4_TOC_CONTEXT_GUARD.md`.

Stage 4.5.8.5 adds carefully gated cross-page TOC-context inheritance. A continuation page without a repeated `CONTENTS` heading is eligible only when the previous and next table fragments satisfy the same geometry, boundary, column-compatibility, section-context, and TOC-shape checks used by logical-table reconciliation. Inheritance can propagate across multiple adjacent TOC pages and stops as soon as any continuation signal fails. See `docs/stages/stage4/STAGE4_5_8_5_CROSS_PAGE_TOC_CONTEXT_INHERITANCE.md`.

Stage 4.5.8.6 reorganizes the frontend into a document workbench and adds a dedicated **Layout** workspace. The Layout view can reconstruct a page directly from Stage 3/Stage 4 JSON, compare that reconstruction with the original PDF, inspect bounding boxes/reading order/table content, and locally render pasted page JSON without changing saved pipeline data. See `docs/stages/stage4/STAGE4_5_8_6_WORKBENCH_FRONTEND.md`.

See `docs/stages/stage4/STAGE4_5_HUMAN_REVIEW.md` for the correction model and `docs/stages/stage4/STAGE4_5_1_JSON_SANDBOX.md` for the JSON preview workflow.

Stage 4.5.8.16 simplifies the correction workflow: dedicated structured-semantics, definition-link, and free-form cross-page relationship editors are removed from the active UI. `definition_text` membership is now explicit through a contextual **Belongs to definition** selector and one bulk `assign_definition` operation. Stage 4.5 no longer guesses definition membership or repairs clause hierarchy automatically; legacy operations remain replayable for backward compatibility. See `docs/stages/stage4/STAGE4_5_8_16_SIMPLIFIED_CORRECTION.md`.


## Stage 13 reproducible Docker stack

Stage 13 adds a lockfile-driven Docker/Compose workflow for PostgreSQL + pgvector, Alembic migrations, FastAPI, and the existing Vite frontend. It is infrastructure-only: the frozen RAG and Stage 11 evaluation behavior are unchanged. CI/CD is intentionally out of scope for this stage.

After applying the Stage 13 candidate, generate dependency locks on the target WSL/Linux environment:

```bash
cd backend
python -m pip install -r requirements-dev.txt
python scripts/prepare_stage13_dependency_locks.py
```

Then verify the host and locked-container environments:

```bash
python scripts/run_stage13_verification.py
python scripts/run_stage13_verification.py --include-docker-smoke
```

For normal local startup from the repository root:

```bash
docker compose up -d --build
```

See `docs/stages/stage13/STAGE13_DOCKER_REPRODUCIBILITY.md`.

## Persistence

PostgreSQL + pgvector is the persistence layer for application metadata, semantic chunks, future embeddings, and evaluation data. Deterministic Stage 3–5 JSON artifacts remain on the filesystem as inspectable sources of truth. See [`docs/architecture/database.md`](docs/architecture/database.md).

Quick start:

```bash
docker compose up -d postgres
cd backend
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head
```

The database readiness endpoint is `GET /api/system/database`.

## Stage 7 hybrid retrieval

Stage 7 preserves the Stage 6 dense baseline and adds PostgreSQL full-text lexical retrieval plus weighted Reciprocal Rank Fusion. Stage 7.1 corrects lexical candidate generation by converting natural-language questions into deterministic OR-oriented content terms, then ranking lexical candidates by matched-term coverage followed by `ts_rank_cd`. The global RAG Playground exposes the lexical query plan plus Dense and Hybrid ranking traces. Stage 8 adds a live Hybrid + Reranker strategy over the full candidate union.

Use the exact same five-query smoke suite for both strategies:

```bash
cd backend
python scripts/test_dense_retrieval_behaviors.py
python scripts/test_hybrid_retrieval_behaviors.py
```

The Stage 7.1 hybrid runner writes:

```text
hybrid_retrieval_results_stage7_1/all_hybrid_retrieval_results_stage7_1.txt
```

See `docs/stages/stage7/STAGE7_HYBRID_RETRIEVAL_AND_PLAYGROUND.md`.

## Stage 8 reranking

Stage 8 uses `BAAI/bge-reranker-v2-m3` as a cross-encoder over the deduplicated union of Dense Top-N and Lexical Top-N candidates. It deliberately does **not** rerank only Hybrid Top-K, because a relevant dense-only candidate may have been pushed below the hybrid cutoff. RRF remains visible as candidate-trace metadata; the cross-encoder relevance score returned by `CrossEncoder.predict()` determines final ranking. Stage 8.1 exposes that single score directly and removes the redundant second sigmoid/normalized display field.

```text
POST /api/retrieval/hybrid-rerank
GET  /api/system/reranker
```

The reranker defaults to `auto` device resolution, batch size 2, and `max_length=1024`. Exact query+passage token counts are checked before scoring so the service refuses silent truncation. The same five smoke-test questions are reused:

```bash
cd backend
python scripts/test_reranked_retrieval_behaviors.py
```

Combined output:

```text
reranked_retrieval_results_stage8/all_reranked_retrieval_results_stage8.txt
```

See `docs/stages/stage8/STAGE8_CROSS_ENCODER_RERANKING.md`.

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload
```


API:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

UI:

```text
http://localhost:5173
```

The UI is organized into:

```text
Overview
Raw extraction
Structured document
JSON Preview
JSON artifacts
```

### Structured document view

Provides:

- document section outline
- page image
- semantic bounding-box overlays
- canonical reading order
- element-type filtering
- hierarchy evidence
- Stage 3 source trace
- separate canonical / Layout / Stage 3 JSON inspection
- page-scoped Stage 4 JSON for definitions, clauses, appendices, logical tables, figures, and relationships

## API endpoints

### Stages 1–3

```text
POST /api/documents/upload
GET  /api/documents
GET  /api/documents/{document_id}
GET  /api/documents/{document_id}/file
POST /api/documents/{document_id}/extract
GET  /api/documents/{document_id}/extraction
GET  /api/documents/{document_id}/pages/{page_number}/preview
```

### Stage 4

```text
POST /api/documents/{document_id}/structure
GET  /api/documents/{document_id}/structure
GET  /api/documents/{document_id}/layout
```

### Stage 4.5

```text
GET    /api/documents/{document_id}/corrections
PUT    /api/documents/{document_id}/corrections
DELETE /api/documents/{document_id}/corrections
GET    /api/documents/{document_id}/resolved-structure
POST   /api/documents/{document_id}/corrections/validate
POST   /api/documents/{document_id}/corrections/approve-relationships
```

## Stage boundaries

Stage 4 does **not** do:

- LLM metadata generation
- semantic chunking
- embeddings
- vector indexing
- retrieval
- answer generation

It also runs PyMuPDF4LLM Layout with OCR disabled in this implementation so OCR does not silently alter the established Stage 3 text source.

Stage 5 consumes **only** a saved Resolved Stage 4.5 artifact with passing structural integrity. If the automatic Stage 4 result needs no edits, Review can be finalized with an empty correction set to create the resolved artifact. Stage 5 never consumes raw PyMuPDF or vendor Layout output directly.

## Stage 5 — Retrieval preparation & semantic chunking

Stage 5 is implemented as a deterministic, auditable layer between resolved document structure and future embeddings/indexing. It writes `data/chunks/{document_id}.json` and never mutates `resolved/{document_id}.json`. **Semantic v2 is now the default**, while Semantic v1 remains available as a legacy baseline.

The active Stage 5 implementation is fully deterministic: it has no external model provider, model API key, model SDK, or model-generated chunk plan.

Semantic v2 is generic rather than tuned to the current AML/CFT test PDF. It uses canonical hierarchy/continuation relationships, section identity, semantic type, adjacency, punctuation and token budgets. It adds parent/dependent-child grouping, parent context on oversized hierarchy splits, conservative short-sibling packing, contextual-note attachment, navigation-only section filtering, cross-page continuation merging, row-aware table splitting, relation-aware local-group context, and conservative suppression of answer-poor figure shells. Local-group scoping prefers canonical `introduces` edges and falls back to the preserved parent/child section tree when a resolved Stage 4.5 artifact omits a redundant local edge. Generic packing treats differing retrieval contexts as semantic boundaries. The chunk artifact includes `context_element_ids`, `refinement_tags`, and a deterministic quality report covering orphan/dangling dependencies, navigation leakage, group-context leakage, and figure-shell leakage. The emitted Semantic-v2 artifact version is `semantic-v2.1`.

Key behavior:

- eligibility requires a saved resolved artifact with passing structural integrity;
- page headers, page footers, margin page numbers, repeated margin text, empty content, and overlapping duplicate text can be excluded from retrieval with explicit reasons;
- section headers are retained as context rather than standalone retrieval noise;
- definition term + definition text are grouped as one semantic unit, including cross-page definitions;
- logical tables use canonical cell structure; figure records use available textual caption/explanation context, while referential figure shells with no answer-bearing explanation are kept out of text retrieval;
- local group headers are carried in retrieval context rather than spending Top-K slots as heading-only chunks, with scope derived from canonical `introduces` relations and a conservative descendant-section fallback when a resolved artifact preserves hierarchy but omits that redundant edge;
- generic packing never merges adjacent units that carry different local-group contexts;
- clauses/subclauses absorb immediately following prose/list content until the next semantic boundary;
- oversized units are split deterministically under a hard maximum with bounded overlap;
- every chunk retains page, canonical element, Stage 3 span/block/table, and relationship provenance;
- token counts use `regex_estimate_v1` and are explicitly estimates, not model-specific tokenizer counts;
- any Stage 3, Stage 4, or Stage 4.5 change invalidates the saved Stage 5 artifact.

API:

```text
POST   /api/documents/{document_id}/chunks
GET    /api/documents/{document_id}/chunks
DELETE /api/documents/{document_id}/chunks
```

See `docs/stages/stage5/STAGE5_RETRIEVAL_PREPARATION_AND_CHUNKING.md` for the full contract and UI behavior.

## Stage 4.1 role/hierarchy refinement

This package includes the Stage 4.1 correction for title/subtitle/document-metadata classification, title-root-aware heading levels, and explicit question/answer section grouping. See `docs/stages/stage4/STAGE4_1_FIX.md` before migrating an existing Stage 4 project.

## Stage 4.2 frontend UX

Stage 4.2 adds a collapsible document sidebar plus page-scoped JSON inspection for Stage 3 and Stage 4. See `docs/stages/stage4/STAGE4_2_UX.md`.

## Stage 4.3 — Definitions / glossary reconstruction

Stage 4.3 added the first deterministic definition-list reconstruction baseline. Stage 4.4 supersedes the downstream canonical schema with `1.3` while preserving that logic.


## Stage 4.4 — Complex structure normalization

Stage 4.4 adds robust definition normalization across text/table layouts, conservative cross-page table merging, clause/subclause relationships, appendix containers, figure relations, and footnote repair. See `docs/stages/stage4/STAGE4_4_COMPLEX_STRUCTURE.md`.

## Stage 4.5.2 — Correction Sandbox

Manual Stage 4.5 editing is now centralized in **Correction Sandbox**. Structured Document is read-only and can switch between automatic and resolved structure. The sandbox provides visual editing plus **Before JSON**, **After JSON**, and **Correction Log** views for the currently selected page. See `docs/stages/stage4/STAGE4_5_2_CORRECTION_SANDBOX.md`.

## Stage 4.4.1 — Cross-page reconciliation

The canonicalizer now uses a multi-signal, term-agnostic cross-page definition reconciliation pass. It can repair next-page continuation fragments that a layout engine mislabels as headings, preserve multi-page `DefinitionEntry` objects, and emit explicit `continues` relationships. See `docs/stages/stage4/STAGE4_4_1_CROSS_PAGE_RECONCILIATION.md`.

## Stage 4.5.8.7 — Manual Correction Workbench

The Review workspace now supports a complete auditable correction loop: move/resize, relabel, draw, split, merge, suppress, undo/redo, same-page definition term↔text membership correction, and existing cross-page continuation editing. Automatic Stage 3/4 artifacts remain immutable; only correction operations are saved. See `docs/stages/stage4/STAGE4_5_8_7_MANUAL_CORRECTION_WORKBENCH.md`.

## Stage 4.5.8.8 — Multi-selection reliability fix

The Review workspace now keeps modifier-click selections stable for merge/suppress workflows. Selection happens once on pointer-down; Shift/Ctrl/Cmd-click adds or removes a region without also starting a drag. The toolbar shows a live selected-region count and a modifier-key hint. This fixes the case where the second region appeared selected briefly and was immediately deselected by the subsequent click event. Backend behavior and saved correction schema are unchanged.


## Stage 4.5.8.9 — Correction integrity & safety

Stage 4.5 manual correction has been hardened before chunking. This release adds duplicate-ID enforcement, exclusive split text assignment, safe contiguous merge validation, canonical-record reconciliation, conservative reading-order repair, cross-page definition membership, bbox validation, small-region provenance recovery, table safety restrictions, structural-promotion guards, controlled split positioning, pointer-cancel handling, and a closer frontend/backend After preview. See `docs/stages/stage4/STAGE4_5_8_9_CORRECTION_INTEGRITY_AND_SAFETY.md` for details.

## Stage 4.5.8.10 — Exact text-span correction

The Review workspace now exposes immutable Stage 3 text spans as a lower-level correction surface. Fresh Stage 3 extraction uses schema `1.1` with stable line/span IDs, canonical Stage 4 uses schema `1.5` with line/span provenance, and correction artifacts use schema `1.4` with the new `span_rebuild` operation. Partial span corrections are lossless: unselected source spans are preserved automatically and the backend rejects any operation that would silently drop text. See `docs/stages/stage4/STAGE4_5_8_10_TEXT_SPAN_CORRECTION.md`.


## Stage 4.5.8.12 — Relationship semantic validation & approval

Historical patch. It introduced semantic validation, stable issue IDs, and explicit relationship approval. **4.5.8.16.2 supersedes the approval gate:** warnings remain diagnostic, but Stage 5 readiness now depends only on blocking structural-integrity errors. Relationship provenance validation remains in place.

See `docs/stages/stage4/STAGE4_5_8_12_RELATIONSHIP_SEMANTIC_VALIDATION_AND_APPROVAL.md`.


## Stage 4.5.8.13 — Relation model corrections

Relation validation now avoids false sibling-marker errors for parent-less subclauses, treats normalized definition source-table IDs as provenance rather than live canonical foreign keys, inherits definition section/context across manual links and obvious sequential drawn rows, downgrades page-boundary duplicate clauses to explicit continuation review candidates, and separates automatic Stage 4 baseline issues from correction-introduced issues in the Review UI. Correction artifacts use schema `1.7`; resolved Stage 4.5 uses schema `1.3`. See `docs/stages/stage4/STAGE4_5_8_13_RELATION_MODEL_CORRECTIONS.md`.

## Stage 4.5.8.14 — relation hierarchy compatibility

Historical patch. It added automatic compatibility repair for flattened legal hierarchy. **4.5.8.16 supersedes that correction behavior:** Stage 4.5 no longer guesses missing clause/subclause parents. Existing hierarchy is preserved unless the reviewer explicitly changes it. Legacy definition-provenance normalization remains supported.

See `docs/stages/stage4/STAGE4_5_8_14_RELATION_HIERARCHY_COMPATIBILITY.md`.

## Stage 4.5.8.15 — definition membership completion & precise provenance

Historical patch. It added precise recovered-definition provenance and automatic/manual definition-membership completion. **4.5.8.16 keeps the provenance improvements but removes automatic manual-definition guessing.** Definition text is now assigned explicitly through a contextual DefinitionEntry selector.

See `docs/stages/stage4/STAGE4_5_8_15_DEFINITION_MEMBERSHIP_AND_PROVENANCE.md`.

## Stage 4.5.8.16 — simplified correction workflow

The active Review UI now exposes only **Element correction** and **Exact text spans**. Dedicated structured-semantics, definition-link, and free-form cross-page relationship editors are removed from the primary workflow. When selected elements are `definition_text`, a contextual **Belongs to definition** selector appears; one bulk `assign_definition` operation can assign the entire selection to an existing DefinitionEntry. The backend derives section membership and rebuilds canonical DefinitionEntry/SectionRecord back-references. Stage 4.5 no longer auto-guesses definition membership or legal hierarchy parents. Legacy correction operations remain replayable for compatibility. Correction artifacts use schema `1.9`.

See `docs/stages/stage4/STAGE4_5_8_16_SIMPLIFIED_CORRECTION.md`.

## Stage 4.5.8.16.1 — frontend compile fix

Fixes six `TS2304` errors caused by stale calls to `setCrossPageSource` and `setDefinitionTermSource` after those legacy UI states were removed in the simplified correction workflow. No backend schema or correction semantics changed. See `docs/stages/stage4/STAGE4_5_8_16_1_FRONTEND_COMPILE_FIX.md`.


## Stage 4.5.8.16.2 — simplified structure status & automatic Stage 5 readiness

The large Canonical Relationship Integrity / Stage 5 approval panel has been removed from the active correction workflow. Reviewers now see only a compact **structure status** (`VALID`, `NEEDS FIX`, or `PENDING`) beside the correction controls. Saving still performs the same blocking integrity validation internally. Semantic warnings remain available in the resolved JSON as diagnostics but do not block Stage 5.

Explicit relationship approval is no longer required. `review.stage5_eligible` is automatically `true` whenever the resolved structure has zero blocking integrity errors. The legacy approval endpoint remains backend-only for compatibility with older clients. Resolved Stage 4.5 artifacts use schema `1.5`; frontend package version is `0.4.5-8.16.2`.

See `docs/stages/stage4/STAGE4_5_8_16_2_SIMPLIFIED_STATUS_GATE.md`.

## Stage 4.5.8.16.2.1

Frontend compile cleanup: removed stale `setApprovedIssueIds` calls after relationship approval state removal.

## Stage 4.5.8.16.3 — relation placement

The DefinitionEntry selector now appears as part of the selected corrected-region workflow instead of above it. Single-element relationship correction is integrated into the selected-region card; multi-selection keeps a compact bulk relation control directly below that area. Backend behavior is unchanged.

## Stage 4.5.8.16.4 — selection state reliability

Semantic relabeling and other in-place corrections now preserve the selected corrected region instead of allowing the editor to disappear during a working-element rebuild. Resolved-artifact refreshes no longer wipe an active unsaved correction session, operation accumulation uses an authoritative ref to avoid stale state, and definition membership is cleared on real semantic type changes so the explicit relation selector remains the source of truth. Frontend package version is `0.4.5-8.16.4`.

See `docs/stages/stage4/STAGE4_5_8_16_4_SELECTION_STATE_RELIABILITY.md`.

## Stage 4.5.8.16.5

Fixes the first-interaction selection race in the Correction Sandbox. The selected-region editor is no longer cleared by a late Stage 4 timestamp refresh; document/page changes remain the only hard-reset triggers.


## Latest patch

Stage 4.5.8.16.5.1 prevents the page-number input blur from re-committing the current page and clearing the first selected corrected region. See `docs/stages/stage4/STAGE4_5_8_16_5_1_PAGE_NAV_BLUR_SELECTION_FIX.md`.

## Stage 4.6 — Semantic reconstruction v2

Stage 4.6 introduces a dedicated deterministic semantic layer under `backend/app/services/semantic/`. PyMuPDF4LLM box classes are retained as `layout_role` evidence, while ambiguous structural roles are resolved from reusable element features plus neighboring sequence context. Canonical schema `1.8` adds `group_header` and per-element classification audit metadata (`selected_type`, confidence, evidence, alternatives). The old isolated `(a) => subclause` promotion path is no longer active. Local list/group dependencies use `introduces` so ClauseRecord-backed `parent_of` integrity remains strict. The Review inspector shows the automatic classification and evidence for the selected region. See `docs/stages/stage4/STAGE4_6_SEMANTIC_V2_ARCHITECTURE.md` and `docs/stages/stage4/STAGE4_6_1_SEMANTIC_TAXONOMY.md`.

## Stage 4.6.2 — Semantic v2.1 scope and continuation

Semantic v2.1 adds parallel local-group propagation, conservative heading-scope resolution, semantic vetoes for false cross-page continuation into fresh numbered clauses, normalized classification alternatives, hierarchy-aware confidence calibration, and stronger advisory semantic validation. Stage 5 code is unchanged. See `docs/stages/stage4/STAGE4_6_2_SEMANTIC_V2_1_SCOPE_AND_CONTINUATION.md`.

## Stage 4.7 — Golden structure benchmark

The primary 109-page portfolio PDF now has a machine-readable Stage 4 golden specification at `backend/evaluation/golden/sc_aml_cft_stage4_v1.json`. The benchmark uses stable page/text anchors rather than canonical element IDs and currently contains 118 checks (112 required, 6 advisory) across element semantics, relationships, definitions, appendices, logical tables and figures. `scripts/validate_stage4_golden_spec.py` validates the benchmark against the exact PDF SHA/page count/text anchors, while `scripts/evaluate_stage4_golden.py` scores a generated `StructuredDocument`. See `docs/stages/stage4/STAGE4_7_GOLDEN_STRUCTURE_SPECIFICATION.md`.


## Stage 4.9 — Semantic v2.3 continuity and hierarchy

Semantic v2.3 introduced same-unit continuation repair, dependent-list ownership, parent-clause tails, appendix descriptive-title cleanup, inherited-obligation enumerations, cascading-step nesting, and spaced alphanumeric clause numbers. Semantic v2.3.1 extends the golden contract to 118 checks (112 required, 6 advisory) and tightens validator precision plus residual figure-interleaved list ownership. Stage 5 code is unchanged. See `docs/stages/stage4/STAGE4_9_SEMANTIC_V2_3_CONTINUITY_AND_HIERARCHY.md` and `docs/stages/stage4/STAGE4_9_1_SEMANTIC_V2_3_1_VALIDATOR_PRECISION.md`.


### Stage 4 Semantic v2.3.1 — validator precision and residual ownership

Semantic v2.3.1 removes false semantic-review warnings for appendix descriptive titles, valid cross-page continuations, and form-style heading/field blocks. It also preserves an explicit list-introducing paragraph across intervening figure-layout fragments so figure-embedded A/B/C text lists retain semantic ownership. The golden contract is version 1.3 with 118 checks (112 required, 6 advisory). Stage 5 remains unchanged. See `docs/stages/stage4/STAGE4_9_1_SEMANTIC_V2_3_1_VALIDATOR_PRECISION.md`.

## Stage 6 dense retrieval baseline

Stage 6 uses `BAAI/bge-m3` through sentence-transformers to embed Stage 5 retrieval text and persist normalized vectors in pgvector. The same code path supports `auto`, `cpu`, `cuda`, and `cuda:<index>` device selection; `auto` prefers CUDA and safely falls back to CPU. Dense retrieval uses exact cosine distance first so later hybrid retrieval and reranking can be evaluated against a clean baseline. See [`docs/stages/stage6/STAGE6_DENSE_EMBEDDINGS_AND_PGVECTOR.md`](docs/stages/stage6/STAGE6_DENSE_EMBEDDINGS_AND_PGVECTOR.md).



## Retrieval Evaluation Dataset v1

A formal retrieval benchmark is available at:

- `backend/evaluation/retrieval/retrieval_eval_v1.json` — 40 questions (25 development, 15 held-out).
- `backend/evaluation/retrieval/retrieval_regression_smoke_v1.json` — five prior smoke questions, excluded from formal metrics.
- `docs/evaluation/RETRIEVAL_EVALUATION_DATASET_V1.md` — evaluation policy and metric definitions.

The dataset is locked to document SHA-256 `e1d138edd3c55b3fa3dd36b3236876a1a8dd634c4d972cec74157e6bf816bc15` and Stage 5 `semantic-v2.1`.


## Formal Retrieval Evaluation Runner

The formal retrieval benchmark now has a protected evaluation runner:

```bash
cd backend
python scripts/run_retrieval_evaluation.py --split dev
```

This runs the 25 development questions against Dense, Hybrid and Hybrid+Reranker and writes auditable raw responses plus Hit@K, Recall@K, MRR@10 and CompleteEvidence@K. The 15 held-out questions require the explicit frozen-retrieval confirmation documented in `docs/evaluation/RETRIEVAL_EVALUATION_RUNNER_V1.md`.

## Stage 8.2 — Structure-aware context assembly

Stage 8.1 retrieval ranking remains frozen. Stage 8.2 adds deterministic, one-hop structural evidence expansion after reranking and reports separate `ContextRecall@K` / `ContextCompleteEvidence@K` metrics without changing raw retrieval ranks. The final held-out Retrieval-v1 benchmark was consumed only after the retrieval configuration was frozen; its results remain evaluation evidence rather than tuning input.


## Stage 9 — Grounded answer generation

Stage 9 uses the frozen Retrieval-v1 production path (`Hybrid + BGE reranker -> Top-5 -> Stage 8.2 structural context`) and adds structured claim generation with evidence IDs and explicit abstention.

- `POST /api/generation/answer` — grounded answer endpoint.
- `GET /api/system/generation` — provider/model/key-configuration diagnostics without exposing secrets.
- `docs/stages/stage9/STAGE9_GROUNDED_ANSWER_GENERATION.md` — design and verification.
- `backend/scripts/test_grounded_generation_behaviors.py` — rate-limit-aware answerability + abstention smoke suite (30s default inter-test delay + adaptive provider-429 retry).

## Stage 10 — Deterministic source citations

Stage 10 keeps Retrieval v1 fully frozen and converts Stage 9 request-local evidence IDs into validated human-facing source citations. The LLM still emits only claim text plus `E1/E2/...`; page, clause, definition, appendix, and source strings are derived by backend code from the exact Stage 5 chunk and resolved canonical structure.

- `backend/app/services/citations.py` — deterministic citation resolver + provenance validation.
- `POST /api/generation/answer` — now returns `cited_answer`, claim `citation_ids`, `citations`, and a citation validation summary.
- `backend/scripts/test_cited_generation_behaviors.py` — strict rate-limit-safe Stage 10 live smoke runner.
- `backend/tests/test_stage10_citations.py` — citation/provenance behavior tests.
- `backend/tests/test_stage10_smoke.py` — smoke-result invariant tests.
- `docs/stages/stage10/STAGE10_DETERMINISTIC_CITATIONS.md` — Stage 10 design and evaluation handoff.
- `backend/evaluation/generation/answer_citation_eval_schema_v1.json` — answer/citation evaluation schema scaffold; no held-out retrieval tuning is introduced.

## Stage 11 — Answer & citation evaluation

Stage 11 evaluates the frozen production RAG path without changing retrieval, reranking, context assembly, generation, or citation behavior.

Stage 11.2 adds a new DEV-only answer/citation benchmark (`20` questions: `17` answerable + `3` abstention controls), canonical gold-source validation, retrieval-question overlap auditing, a resumable rate-limit-safe DEV capture runner, and deterministic offline scoring. Stage 11.2C freezes `stage11_semantic_rubric_v1` using a human-confirmed 9-question calibration subset and implements semantic metrics with exact dataset/response hash binding. Stage 11.3 adds an independent **frozen-before-run** held-out benchmark (`18` questions: `15` answerable + `3` abstention controls), a prior-benchmark independence audit, dataset SHA-256 freeze guard, and confirmation-protected non-overwriting capture path.

- `backend/evaluation/generation/answer_citation_eval_dev_v1.json` — Stage 11 DEV benchmark.
- `backend/evaluation/generation/answer_citation_eval_heldout_v1.json` — frozen Stage 11.3 independent held-out benchmark.
- `backend/evaluation/baselines/stage11_heldout_benchmark_manifest_v1.json` — immutable held-out dataset hash guard.
- `backend/scripts/validate_answer_citation_eval_source.py` — validates gold locators against the frozen canonical artifact.
- `backend/scripts/audit_stage11_dev_question_overlap.py` — prevents accidental retrieval-benchmark question reuse.
- `backend/scripts/capture_answer_citation_dev.py` — DEV-only live response capture with frozen-baseline and source guards.
- `backend/scripts/score_answer_citation_results.py` — deterministic DEV metrics plus optional frozen human semantic metrics via `--semantic-calibration`.
- `backend/app/services/evaluation/semantic_metrics.py` — frozen human-label validation and semantic metric aggregation; never calls an LLM.
- `backend/evaluation/generation/stage11_semantic_rubric_v1.json` — frozen semantic-label definitions and aggregation policy.
- `backend/evaluation/baselines/stage11_semantic_evaluation_manifest_v1.json` — hashes the frozen rubric, calibration artifact, and semantic metric implementation.
- `backend/evaluation/generation/answer_citation_eval_dev_calibration_v1_frozen.json` — human-confirmed 9-question calibration bound to exact captured responses.
- `backend/scripts/validate_stage11_semantic_calibration.py` — verifies rubric, dataset hash, labels, and optional response hashes.
- `backend/scripts/prepare_stage11_semantic_calibration.py` — prepares blank human calibration labels from fresh responses.
- `docs/stages/stage11/STAGE11_ANSWER_CITATION_EVALUATION.md` — methodology, rubric, and execution workflow.

Stage 11 is complete and frozen. The independent 18-question Stage 11.3 held-out
benchmark was frozen before execution, consumed once on the unchanged production
pipeline, and retained as immutable response/evaluation evidence. Held-out responses
are not regenerated for tuning.

## Stages 12–15 — verification, product UI, and controlled experiments

Stage 12 verifies the frozen pipeline with automated regression, API, reproduction,
and frontend checks. Stage 13 packages the system into a reproducible Docker/Compose
stack with PostgreSQL + pgvector and verified GPU runtime support.

Stage 14 presents the system as a focused RAG product surface: `Overview`,
`Documents`, and `RAG Playground`. The playground exposes cited answers plus
same-execution retrieval/context/provenance inspection. The document-specific
benchmark UI remains preserved internally but is intentionally hidden from the
primary product workflow.

Stage 15 adds an isolated experiment layer without changing
`POST /api/generation/answer` or the frozen production Retrieval v1 profile. The
first completed controlled experiment varied only `candidate_k` on the existing
25-question DEV split:

| candidate_k | Hit@1 | Hit@5 | Recall@5 | MRR@10 | CompleteEvidence@5 | Avg latency |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 844.1 ms |
| 20 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 1302.3 ms |
| 40 | 96.0% | 100.0% | 93.3% | 0.9800 | 88.0% | 2131.0 ms |

Increasing the candidate pool did not improve Top-5 DEV retrieval quality, while
candidate volume and latency increased. `candidate_k=40` improved only deeper
Top-10 evidence coverage. Production remains frozen at `candidate_k=20`; the DEV
experiment is engineering evidence, not an automatic production promotion.

See `docs/evaluation/STAGE15_RETRIEVAL_EXPERIMENT_FINDINGS.md`.

