# Portfolio Demo Guide

This guide is for a short recruiter/interviewer walkthrough of **RAG Document Studio**. The goal is to demonstrate the engineering decisions and trust boundaries without spending the demo explaining every internal implementation stage.

## 5-minute demo flow

### 1. Start on Overview — 30 seconds

Explain the project in one sentence:

> RAG Document Studio is a structure-aware RAG system for complex regulatory PDFs that makes document processing, hybrid retrieval, citations, provenance, and related visual evidence inspectable end to end.

Point out the pipeline summary and the four primary product areas:

```text
Overview | Documents | Search & Ask | Evaluation
```

### 2. Open Documents — 60 seconds

Show that ingestion does not immediately jump from PDF text to embeddings.

Highlight:

- original PDF/layout evidence;
- canonical structure;
- human correction workflow;
- semantic chunks;
- search/index state.

Talking point:

> The important design decision is that I reconstruct and review document structure before chunking. That preserves definitions, clauses, tables, figures, hierarchy, and provenance that a plain-text splitter can lose.

### 3. Search & Ask: same-page visual evidence — 60 seconds

Ask:

```text
Explain why Mr W and Ms Y are beneficial owners of Company A.
```

Show:

- cited production answer;
- validated source;
- Illustration 1 visual evidence;
- source PDF/provenance actions.

Talking point:

> Retrieval is still text-based in this version. The figure is linked through canonical document relationships, so I can show the original visual without pretending the LLM interpreted the pixels.

### 4. Search & Ask: cross-page relationship — 60 seconds

Ask:

```text
Explain the BbRA and RbRA process.
```

Show that evidence referring to the RBA process can link to the following-page diagram.

Talking point:

> This is more than “show the nearest image.” The resolver uses explicit references, captions, canonical relationships, page geometry, and bounded cross-page rules. That lets a text chunk on one page resolve to the visual it introduces on the next page.

### 5. Open the Answer Inspector — 45 seconds

Show the retrieval tab and explain:

```text
Dense retrieval
      +
PostgreSQL FTS
      ↓
weighted RRF
      ↓
cross-encoder reranker
      ↓
bounded structural context
```

Talking point:

> Dense and lexical scores are not directly mixed because they are different score spaces. I combine their ranks using reciprocal-rank fusion, then rerank the candidate union with a cross-encoder.

### 6. Open citation provenance — 30 seconds

Click an inline citation or **Inspect provenance**.

Talking point:

> The LLM emits evidence references, but it does not invent human-facing page numbers or clause labels. The backend resolves citations deterministically through the evidence, chunk, canonical element, and PDF provenance chain.

### 7. Evaluation — 15 seconds

Show the frozen benchmark view.

Talking point:

> Evaluation is kept separate from live Search & Ask. These scores belong to the frozen benchmark document and are not presented as universal quality scores for arbitrary uploads.

---

## Optional extended demo cases

### Table evidence

```text
What are examples of risk factors and formulated parameters used in the business-based risk assessment?
```

Use this to show structured table evidence plus the original PDF crop.

### Negative visual test

```text
How long must transaction records be retained?
```

Use this to demonstrate that a normal text answer does not receive an unrelated image simply because one exists nearby in the document.

### Retrieval-only experiment

Switch Search & Ask to **Retrieval experiment** and compare:

- Dense;
- Hybrid;
- Hybrid + Reranker.

Explain that this diagnostic mode does not call the generation provider and does not modify the frozen production retrieval profile.

---

## Interview talking points

### Why not use plain recursive text splitting?

The source document contains hierarchy, definitions, tables, figures, and cross-page relations. Chunk boundaries are produced from canonical semantic units so chunks retain document meaning and provenance instead of being arbitrary character windows.

### Why PostgreSQL FTS instead of calling it BM25?

The lexical implementation is PostgreSQL Full-Text Search using its own ranking behavior. Calling it BM25 would misrepresent the implementation.

### Why use RRF?

Dense similarity and lexical ranking scores are not calibrated to the same numerical scale. Weighted Reciprocal Rank Fusion combines rank positions instead of pretending the raw scores are directly comparable.

### Why rerank after hybrid retrieval?

Hybrid retrieval improves candidate coverage. A cross-encoder then evaluates query-document relevance more deeply and improves ordering of the candidate union.

### Why not let the LLM create citation page numbers?

Free-form source locations can be hallucinated. The model references request-local evidence IDs; backend code derives page/clause/source information from frozen provenance.

### Why human-in-the-loop corrections?

Layout interpretation contains genuinely ambiguous cases. Instead of hiding them behind LLM guesses, the project preserves automatic output and applies explicit approved corrections non-destructively.

### Why are visuals Option A rather than multimodal retrieval?

The current goal is truthful provenance. Figures and tables associated with retrieved text are shown from the source PDF, but the generation model does not claim to reason over their pixels. A future VLM layer can make image-only meaning independently searchable.

---

## Claims to avoid in a portfolio interview

Do not describe the project as:

- a universal arbitrary-PDF parser;
- an internet-scale vector-search system;
- a fully multimodal RAG system;
- proof that the benchmark metrics generalize to all regulatory documents;
- a production multi-tenant SaaS platform.

A stronger description is:

> I deliberately scoped the project around one difficult regulatory document so I could deeply engineer and evaluate the entire RAG pipeline instead of hiding uncertainty behind a generic chatbot demo.

---

## Final demo checklist

Before recording a video or presenting live:

- [ ] `docker compose ps` shows backend/frontend/postgres healthy.
- [ ] Search & Ask can generate a cited answer.
- [ ] Same-page Illustration 1 renders correctly.
- [ ] RBA cross-page diagram renders correctly.
- [ ] Table evidence renders correctly.
- [ ] A text-only query does not attach an unrelated visual.
- [ ] `Show source [n]` focuses the corresponding validated source.
- [ ] `View highlighted page` opens the correct PDF region.
- [ ] Citation provenance drawer opens and closes correctly.
- [ ] Evaluation clearly appears as frozen benchmark evidence.
- [ ] Browser console contains no unexpected errors.
