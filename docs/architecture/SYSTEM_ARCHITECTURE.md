# System Architecture

## Scope

This project is a portfolio-oriented RAG workbench engineered around one difficult 109-page Malaysian regulatory PDF. The goal is not to claim arbitrary-PDF generalization; it is to make the full path from PDF evidence to cited answer inspectable and evaluable.

The production retrieval/generation profile is frozen as **Retrieval v1**. Stage 15 experiments are isolated from that path.

## End-to-end pipeline

```text
PDF
 │
 ├─ 1–2 Intake / validation
 │      original file, SHA-256, PDF classification
 │
 ├─ 3 Deterministic extraction
 │      PyMuPDF blocks, lines, spans, tables, geometry
 │
 ├─ 4 Layout + canonical reconstruction
 │      PyMuPDF4LLM layout evidence
 │      deterministic semantic resolver
 │      definitions / clauses / tables / figures / hierarchy
 │
 ├─ 4.5 Human review
 │      non-destructive element + exact-span corrections
 │
 ├─ 5 Semantic chunking (`semantic-v2.1`)
 │      answer-bearing content + structural context + provenance
 │
 ├─ 6 Dense retrieval
 │      BAAI/bge-m3 → normalized vectors → pgvector cosine
 │
 ├─ 7 Hybrid retrieval
 │      PostgreSQL FTS + dense candidates → weighted RRF
 │
 ├─ 8 Cross-encoder reranking
 │      BAAI/bge-reranker-v2-m3
 │
 ├─ 8.2 Bounded structure-aware context
 │      `structural_one_hop_v1`
 │
 ├─ 9 Grounded generation
 │      evidence IDs + explicit abstention
 │
 ├─ 10 Deterministic citations
 │      claims → evidence → chunks → canonical locators → PDF
 │
 ├─ 10A Visual evidence
 │      retrieved evidence → canonical figure/table relation → PDF crop
 │
 ├─ 11 Evaluation
 │      deterministic metrics + frozen human semantic review
 │
 └─ 14 Product UI
        cited answer + retrieval/context/provenance inspection
```

## Persisted trust boundaries

The system intentionally separates deterministic artifacts from queryable runtime persistence:

```text
backend/data/
  raw/          original PDF
  metadata/     intake/classification state
  extracted/    Stage 3 immutable extraction evidence
  layout/       layout-provider evidence
  structured/   automatic canonical Stage 4
  corrections/  manual correction operations
  resolved/     automatic + approved corrections
  chunks/       frozen Stage 5 retrieval units

PostgreSQL / pgvector
  documents
  chunks
  chunk_embeddings
  evaluation_* tables
  retrieval_experiment_* tables
```

Stage 3–5 JSON artifacts remain inspectable sources of truth; the database does not replace them.

## Core design decisions

### Layout evidence is not semantic truth

PyMuPDF4LLM layout classes are preserved as `layout_role` evidence. Canonical `type` is resolved separately from numbering, geometry, typography, punctuation, proposition shape, neighboring elements and structural context. This prevents vendor labels such as `list-item` or `section-header` from silently becoming the document's semantic contract.

### Chunking is deterministic and provenance-preserving

Stage 5 groups canonical units while retaining page, element, block/span/table and relationship provenance. The embedding model is downstream of chunk construction.

### Hybrid scores are not mixed directly

Dense cosine similarity and PostgreSQL FTS ranking use different score spaces. Weighted Reciprocal Rank Fusion combines **ranks**, not raw scores.

### Reranking and context assembly are separate

The cross-encoder determines the final seed ordering. Stage 8.2 then attaches bounded structural evidence without changing raw retrieval ranks.

### The LLM does not invent citation locations

Generation emits claim text plus request-local evidence IDs. Page/clause/definition/appendix citation strings are derived by backend code from frozen provenance.

### Visual evidence does not pretend to be multimodal reasoning

Related figures and tables are resolved from canonical document relationships after text evidence is retrieved. The backend renders the original PDF region and exposes it as source evidence. In this Option-A implementation, the visual pixels are not independently embedded or interpreted by the generation model.

### Evaluation is protected from tuning

The formal retrieval benchmark has DEV and held-out splits. The Stage 11 answer/citation benchmark is separately authored and independently frozen. Stage 15 uses DEV-only controlled experiments and cannot silently alter Retrieval v1.

## Production Retrieval v1

```text
embedding        BAAI/bge-m3
lexical backend  PostgreSQL FTS (`english`)
lexical query    OR content terms v1
lexical ranking  matched-term coverage, then ts_rank_cd
fusion           weighted RRF
candidate_k      20 per dense/lexical retriever
rrf_k            60
dense weight     1.0
lexical weight   1.0
reranker         BAAI/bge-reranker-v2-m3
seed top_k       5
context          structural_one_hop_v1, bounded/non-recursive
```

The PostgreSQL lexical system is intentionally described as **PostgreSQL FTS**, not BM25.

## Product surface

The visible application navigation is intentionally compact:

```text
Overview | Documents | Search & Ask | Evaluation
```

`Search & Ask` keeps the frozen production cited-answer path separate from diagnostic retrieval experiments. The `Evaluation` view is explicitly a frozen benchmark explorer; it is not presented as a live quality score for arbitrary uploaded documents.

Within a selected document, the product workflow is:

```text
Overview | Content | Structure | Review | Knowledge | Search Index
```

## Verification boundary

System correctness is guarded by backend regression tests, frozen-evaluation reproduction, frontend TypeScript/Vite build checks, Docker/Compose verification and live retrieval smoke tests. Stage 15 experiments are diagnostic and do not authorize production changes.
