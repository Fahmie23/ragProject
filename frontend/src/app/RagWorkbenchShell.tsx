import { useEffect, useMemo, useState, type ReactNode } from "react";
import WorkbenchApp from "../features/workbench/WorkbenchApp";
import { listDocuments, rawFileUrl, runContextExpandedRetrieval, runDenseRetrieval, runGroundedAnswer, runHybridRetrieval } from "../api";
import type { ContextExpandedRetrievalResponse, DenseRetrievalResponse, DocumentRecord, GroundedAnswerResponse, HybridRetrievalHit, HybridRetrievalResponse, RerankedRetrievalHit } from "../types";

type AppView = "overview" | "documents" | "playground" | "evaluation";

const Icon = ({ children }: { children: ReactNode }) => <span className="rag-nav-icon" aria-hidden="true">{children}</span>;

function AppHeader({ active, onChange }: { active: AppView; onChange: (view: AppView) => void }) {
  const items: Array<{ id: AppView; label: string; icon: string }> = [
    { id: "overview", label: "Overview", icon: "⌂" },
    { id: "documents", label: "Documents", icon: "▤" },
    { id: "playground", label: "RAG Playground", icon: "✦" },
    { id: "evaluation", label: "Evaluation", icon: "◎" },
  ];

  return (
    <header className="rag-global-header">
      <button className="rag-global-brand" type="button" onClick={() => onChange("overview")} aria-label="Open RAG Workbench overview">
        <span className="rag-global-mark">R</span>
        <span><strong>RAG Workbench</strong><small>End-to-end retrieval engineering</small></span>
      </button>
      <nav className="rag-global-nav" aria-label="RAG Workbench">
        {items.map((item) => (
          <button key={item.id} type="button" className={active === item.id ? "active" : ""} onClick={() => onChange(item.id)}>
            <Icon>{item.icon}</Icon><span>{item.label}</span>
          </button>
        ))}
      </nav>
      <span className="rag-prototype-badge">Cited RAG live</span>
    </header>
  );
}

function PipelineStep({ label, detail, state }: { label: string; detail: string; state: "done" | "next" | "planned" }) {
  return (
    <div className={`rag-pipeline-step ${state}`}>
      <span className="rag-pipeline-dot">{state === "done" ? "✓" : state === "next" ? "→" : "○"}</span>
      <span><strong>{label}</strong><small>{detail}</small></span>
    </div>
  );
}

function Overview({ onChange }: { onChange: (view: AppView) => void }) {
  return (
    <main className="rag-page rag-overview-page">
      <section className="rag-hero">
        <div>
          <span className="rag-eyebrow">Advanced RAG portfolio project</span>
          <h1>Understand what enters retrieval,<br />not only what the chatbot says.</h1>
          <p>A document-grounded RAG workbench that exposes extraction, canonical structure, semantic chunks, retrieval traces, citations, and evaluation in one coherent interface.</p>
          <div className="rag-hero-actions">
            <button className="rag-primary-action" type="button" onClick={() => onChange("playground")}>Open RAG Playground</button>
            <button className="rag-secondary-action" type="button" onClick={() => onChange("documents")}>Inspect document</button>
          </div>
        </div>
        <div className="rag-readiness-card">
          <div className="rag-card-kicker">Primary benchmark</div>
          <h2>SC AML/CFT Guidelines</h2>
          <p>Complex regulatory PDF used as the controlled ingestion and retrieval benchmark.</p>
          <div className="rag-stat-strip">
            <div><strong>109</strong><span>pages</span></div>
            <div><strong>1,243</strong><span>elements</span></div>
            <div><strong>39</strong><span>definitions</span></div>
          </div>
          <div className="rag-readiness-row"><span>Canonical structure</span><strong>Benchmark ready</strong></div>
        </div>
      </section>

      <section className="rag-section">
        <div className="rag-section-heading"><div><span className="rag-eyebrow">Pipeline</span><h2>End-to-end RAG workflow</h2></div><span className="rag-muted-label">Retrieval + cited generation live</span></div>
        <div className="rag-pipeline-grid">
          <PipelineStep label="Extraction" detail="Layout-aware PDF parsing" state="done" />
          <PipelineStep label="Canonical structure" detail="Hierarchy + relations" state="done" />
          <PipelineStep label="Semantic chunks" detail="Structure-aware units" state="done" />
          <PipelineStep label="Embedding & index" detail="BGE-M3 + pgvector" state="done" />
          <PipelineStep label="Retrieval" detail="Dense + PostgreSQL FTS + RRF" state="done" />
          <PipelineStep label="Reranking" detail="BGE cross-encoder on candidate union" state="done" />
          <PipelineStep label="Context assembly" detail="Bounded structural evidence expansion" state="done" />
          <PipelineStep label="Generation" detail="Grounded claims + abstention" state="done" />
          <PipelineStep label="Citations" detail="Deterministic claim-to-source validation" state="done" />
          <PipelineStep label="Evaluation" detail="Answer + citation quality" state="next" />
        </div>
      </section>

      <section className="rag-overview-columns">
        <article className="rag-panel rag-project-panel">
          <div className="rag-card-kicker">Document intelligence</div>
          <h3>Inspect the evidence before indexing</h3>
          <p>The existing parser/correction workbench remains available as an expert debugging module instead of being the identity of the whole product.</p>
          <div className="rag-feature-list">
            <span>PDF + bounding boxes</span><span>Canonical tree</span><span>Human corrections</span><span>Page JSON</span>
          </div>
          <button className="rag-text-action" type="button" onClick={() => onChange("documents")}>Open Documents →</button>
        </article>
        <article className="rag-panel">
          <div className="rag-card-kicker">Retrieval visibility</div>
          <h3>Make RAG behavior inspectable</h3>
          <p>The playground is designed to expose retrieved chunks, scores, retrieval strategy, reranking order, and source citations alongside the final answer.</p>
          <button className="rag-text-action" type="button" onClick={() => onChange("playground")}>Preview Playground →</button>
        </article>
        <article className="rag-panel">
          <div className="rag-card-kicker">Evaluation</div>
          <h3>Show evidence of improvement</h3>
          <p>Compare retrieval strategies with Recall@K and MRR, then track faithfulness, relevance, and citation quality for generated answers.</p>
          <button className="rag-text-action" type="button" onClick={() => onChange("evaluation")}>Preview Evaluation →</button>
        </article>
      </section>
    </main>
  );
}

type LiveRetrievalStrategy = "Dense" | "Hybrid" | "Hybrid + Reranker";
type LiveRetrievalResponse = DenseRetrievalResponse | HybridRetrievalResponse | ContextExpandedRetrievalResponse;

function isRerankedResponse(result: LiveRetrievalResponse): result is ContextExpandedRetrievalResponse {
  return "reranker_model" in result && "candidate_union_count" in result;
}

function isHybridResponse(result: LiveRetrievalResponse): result is HybridRetrievalResponse {
  return "fusion_method" in result && !isRerankedResponse(result);
}

function pageLabel(pages: number[]) {
  if (pages.length === 0) return "—";
  if (pages.length === 1) return String(pages[0]);
  return `${pages[0]}–${pages[pages.length - 1]}`;
}

function sectionLabel(sectionPath: string[]) {
  return sectionPath.length ? sectionPath[sectionPath.length - 1] : "Unscoped chunk";
}

function RagPlayground() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [strategy, setStrategy] = useState<LiveRetrievalStrategy>("Dense");
  const [question, setQuestion] = useState("What are the requirements for delayed verification?");
  const [topK, setTopK] = useState(5);
  const [candidateK, setCandidateK] = useState(20);
  const [result, setResult] = useState<LiveRetrievalResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatedAnswer, setGeneratedAnswer] = useState<GroundedAnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(true);

  useEffect(() => {
    let cancelled = false;
    listDocuments()
      .then((items) => {
        if (cancelled) return;
        setDocuments(items);
        setDocumentId((current) => current || items[0]?.document_id || "");
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Failed to load documents");
      });
    return () => { cancelled = true; };
  }, []);

  async function runRetrieval() {
    const clean = question.trim();
    if (!clean || !documentId || running) return;
    setRunning(true);
    setError(null);
    try {
      const request = {
        document_id: documentId,
        query: clean,
        top_k: topK,
        embedding_device: "auto",
      };
      const response = strategy === "Dense"
        ? await runDenseRetrieval(request)
        : strategy === "Hybrid"
          ? await runHybridRetrieval({
              ...request,
              candidate_k: Math.max(candidateK, topK),
              rrf_k: 60,
              dense_weight: 1,
              lexical_weight: 1,
            })
          : await runContextExpandedRetrieval({
              ...request,
              candidate_k: Math.max(candidateK, topK),
              rrf_k: 60,
              dense_weight: 1,
              lexical_weight: 1,
              reranker_model: "BAAI/bge-reranker-v2-m3",
              reranker_device: "auto",
              context_max_forward_neighbors_per_seed: 2,
              context_max_backward_neighbors_per_seed: 1,
              context_max_page_gap: 1,
              context_max_chunks: Math.max(30, topK),
            });
      setResult(response);
    } catch (caught: unknown) {
      setResult(null);
      setError(caught instanceof Error ? caught.message : "Retrieval failed");
    } finally {
      setRunning(false);
    }
  }

  async function runGeneration() {
    const clean = question.trim();
    if (!clean || !documentId || generating) return;
    setGenerating(true);
    setError(null);
    setResult(null);
    try {
      const response = await runGroundedAnswer({ document_id: documentId, question: clean });
      setGeneratedAnswer(response);
    } catch (caught: unknown) {
      setGeneratedAnswer(null);
      setError(caught instanceof Error ? caught.message : "Grounded answer generation failed");
    } finally {
      setGenerating(false);
    }
  }

  const selectedDocument = documents.find((document) => document.document_id === documentId);
  const hits = result?.hits ?? [];
  const topHit = hits[0];
  const rerankedResult = result && isRerankedResponse(result) ? result : null;
  const hybridResult = result && isHybridResponse(result) ? result : null;
  const resultStrategy = rerankedResult ? "Hybrid + Reranker" : hybridResult ? "Hybrid" : result ? "Dense" : strategy;
  const citationById = useMemo(
    () => new Map((generatedAnswer?.citations ?? []).map((citation) => [citation.citation_id, citation])),
    [generatedAnswer],
  );
  const citationByEvidenceId = useMemo(
    () => new Map((generatedAnswer?.citations ?? []).map((citation) => [citation.evidence_id, citation])),
    [generatedAnswer],
  );

  return (
    <main className="rag-page rag-playground-page">
      <div className="rag-page-heading">
        <div>
          <span className="rag-eyebrow">RAG Playground</span>
          <h1>Ask, retrieve, answer, inspect.</h1>
          <p>Compare retrieval strategies or run the frozen Retrieval-v1 production path to generate a claim-grounded answer with deterministic, validated source citations and abstention.</p>
        </div>
        <div className="rag-strategy-control" role="group" aria-label="Retrieval strategy">
          {(["Dense", "Hybrid", "Hybrid + Reranker"] as LiveRetrievalStrategy[]).map((item) => (
            <button
              type="button"
              key={item}
              className={strategy === item ? "active" : ""}
              onClick={() => { setStrategy(item); setResult(null); setGeneratedAnswer(null); }}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <section className="rag-query-card">
        <div className="rag-retrieval-controls">
          <label>
            <span>Document</span>
            <select value={documentId} onChange={(event) => { setDocumentId(event.target.value); setResult(null); setGeneratedAnswer(null); }}>
              {documents.length === 0 && <option value="">No documents loaded</option>}
              {documents.map((document) => <option key={document.document_id} value={document.document_id}>{document.original_filename}</option>)}
            </select>
          </label>
          <label>
            <span>Top K</span>
            <input type="number" min={1} max={50} value={topK} onChange={(event) => setTopK(Math.max(1, Math.min(50, Number(event.target.value) || 1)))} />
          </label>
          {strategy !== "Dense" && <label>
            <span>Candidate K</span>
            <input type="number" min={topK} max={100} value={candidateK} onChange={(event) => setCandidateK(Math.max(topK, Math.min(100, Number(event.target.value) || topK)))} />
          </label>}
        </div>
        <label htmlFor="rag-question">Question</label>
        <div className="rag-query-row">
          <input
            id="rag-question"
            value={question}
            onChange={(event) => { setQuestion(event.target.value); setGeneratedAnswer(null); }}
            onKeyDown={(event) => event.key === "Enter" && void runRetrieval()}
            placeholder="Ask a question about the selected document"
          />
          <div className="rag-query-actions">
            <button type="button" disabled={running || generating || !documentId || !question.trim()} onClick={() => void runRetrieval()}>
              {running ? "Retrieving…" : "Retrieve"}
            </button>
            <button className="rag-generate-action" type="button" disabled={running || generating || !documentId || !question.trim()} onClick={() => void runGeneration()}>
              {generating ? "Generating…" : "Generate cited answer"}
            </button>
          </div>
        </div>
        <small className="rag-production-note">Cited generation always uses the frozen Retrieval-v1 profile: Dense+FTS candidate union → BGE reranker Top-5 → Stage 8.2 context. Stage 10 only resolves and validates citations downstream; Playground Top K/Candidate K controls affect retrieval experiments only.</small>
        <div className="rag-suggestion-row">
          <span>Smoke tests:</span>
          <button type="button" onClick={() => setQuestion("What is a politically exposed person?")}>PEP definition</button>
          <button type="button" onClick={() => setQuestion("What measures are required when establishing a non-face-to-face business relationship?")}>Non-face-to-face</button>
          <button type="button" onClick={() => setQuestion("What information must be reported when there is a positive match with a designated person?")}>Appendix form</button>
        </div>
        {error && <div className="rag-retrieval-error" role="alert">{error}</div>}
      </section>

      <div className="rag-playground-grid">
        <section className="rag-answer-panel">
          <div className="rag-panel-head">
            <div><span className="rag-card-kicker">{generatedAnswer ? "Generated answer" : "Retrieval result"}</span><h2>{generatedAnswer?.question ?? result?.query ?? "Run a query to inspect evidence"}</h2></div>
            {generatedAnswer ? <span className="rag-grounded-pill">Stage 10 · {generatedAnswer.citations.length} citations</span> : result && <span className="rag-grounded-pill">{resultStrategy} · {hits.length} hits</span>}
          </div>
          {generatedAnswer ? <>
            <div className="rag-generation-meta">
              <span className={`rag-answer-status ${generatedAnswer.status}`}>{generatedAnswer.status === "answered" ? "Cited answer" : "Insufficient evidence"}</span>
              <small>{generatedAnswer.generation_provider} · {generatedAnswer.generation_model} · {generatedAnswer.retrieval_profile}</small>
            </div>
            <p className="rag-answer-copy">{generatedAnswer.cited_answer || generatedAnswer.answer}</p>
            {generatedAnswer.claims.length > 0 && <div className="rag-claim-list">
              {generatedAnswer.claims.map((claim) => <article key={claim.claim_id} className="rag-claim-card">
                <div><strong>{claim.claim_id}</strong><span>{claim.evidence_ids.join(" · ")}</span></div>
                <p>{claim.text}</p>
                <div className="rag-claim-citations">
                  {claim.citation_ids.map((citationId) => {
                    const citation = citationById.get(citationId);
                    if (!citation) return null;
                    const href = citation.pages[0] ? `${rawFileUrl(documentId)}#page=${citation.pages[0]}` : rawFileUrl(documentId);
                    return <a key={citationId} href={href} target="_blank" rel="noreferrer">{citation.marker} {citation.display}</a>;
                  })}
                </div>
              </article>)}
            </div>}
            {generatedAnswer.missing_information.length > 0 && <div className="rag-missing-info"><strong>Missing evidence</strong>{generatedAnswer.missing_information.map((item) => <span key={item}>{item}</span>)}</div>}
            <div className="rag-source-summary">
              <strong>{generatedAnswer.context_chunk_count} evidence chunks · {generatedAnswer.citations.length} validated citations</strong>
              <span>{generatedAnswer.citation_version} · every rendered citation is derived from frozen chunk provenance, not generated by the LLM.</span>
            </div>
          </> : topHit ? <>
            <p className="rag-answer-copy">{topHit.content_text}</p>
            <div className="rag-inline-citations">
              <button type="button">Rank #1</button>
              <button type="button">Page {pageLabel(topHit.pages)}</button>
              <button type="button">{topHit.semantic_type}</button>
            </div>
            <div className="rag-source-summary">
              <strong>{sectionLabel(topHit.section_path)}</strong>
              <span>Retrieved evidence only. Use “Generate cited answer” to run the frozen production RAG path.</span>
            </div>
          </> : <p className="rag-answer-copy">Run retrieval to inspect evidence, or generate a cited answer directly from the frozen production retrieval path.</p>}
        </section>

        <aside className="rag-sources-panel">
          <div className="rag-panel-head"><div><span className="rag-card-kicker">{generatedAnswer ? "Validated sources" : "Top evidence"}</span><h2>{generatedAnswer ? "Answer citations" : "Retrieved chunks"}</h2></div><span className="rag-count-pill">{generatedAnswer ? `${generatedAnswer.citations.length} citations` : rerankedResult ? `${hits.length} ranked · ${rerankedResult.context_chunk_count} context` : `${hits.length} chunks`}</span></div>
          {generatedAnswer ? generatedAnswer.citations.map((citation) => {
            const href = citation.pages[0] ? `${rawFileUrl(documentId)}#page=${citation.pages[0]}` : rawFileUrl(documentId);
            return <article className="rag-source-card rag-citation-source-card" key={citation.citation_id}>
              <div><strong>{citation.marker} · {citation.evidence_id}</strong><span>{citation.validation_status}</span></div>
              <strong className="rag-source-section">{citation.display}</strong>
              <p>{citation.source_filename}</p>
              <small>{sectionLabel(citation.section_path)} · c{String(citation.chunk_index).padStart(4, "0")}</small>
              <a className="rag-citation-open" href={href} target="_blank" rel="noreferrer">Open source PDF →</a>
            </article>;
          }) : hits.slice(0, 3).map((hit) => {
            const reranked = rerankedResult ? hit as RerankedRetrievalHit : null;
            const hybrid = hybridResult ? hit as HybridRetrievalHit : null;
            const score = reranked ? reranked.reranker_score : hybrid ? hybrid.fusion_score : "score" in hit ? hit.score : 0;
            return <article className="rag-source-card" key={hit.chunk_id}>
              <div><strong>#{hit.rank} · Page {pageLabel(hit.pages)}</strong><span>{reranked ? `rerank ${score.toFixed(4)}` : score.toFixed(6)}</span></div>
              <strong className="rag-source-section">{sectionLabel(hit.section_path)}</strong>
              <p>{hit.content_text}</p>
              {reranked && <small className="rag-hybrid-mini-trace">Reranked from candidate #{reranked.hybrid_candidate_rank} · Dense {reranked.dense_rank ? `#${reranked.dense_rank}` : "—"} · Lexical {reranked.lexical_rank ? `#${reranked.lexical_rank}` : "—"}</small>}
              {hybrid && <small className="rag-hybrid-mini-trace">Dense {hybrid.dense_rank ? `#${hybrid.dense_rank}` : "—"} · Lexical {hybrid.lexical_rank ? `#${hybrid.lexical_rank}` : "—"}{hybrid.lexical_rank ? ` · coverage ${Math.round(hybrid.lexical_term_coverage * 100)}%` : ""}</small>}
            </article>;
          })}
          {generatedAnswer && generatedAnswer.citations.length === 0 && <p className="rag-empty-note">No citations are emitted for an abstained answer.</p>}
          {!generatedAnswer && result && hits.length === 0 && <p className="rag-empty-note">No chunks matched this query.</p>}
        </aside>
      </div>


      {generatedAnswer && <section className="rag-trace-panel rag-generation-panel">
        <div className="rag-panel-head">
          <div><span className="rag-card-kicker">Stage 10 · Citation trace</span><h2>Claim → evidence → source</h2></div>
          <span className="rag-count-pill">{generatedAnswer.used_evidence_ids.length} used / {generatedAnswer.evidence.length} available</span>
        </div>
        <p className="rag-empty-note">The LLM returns only E-IDs. Citation strings are built deterministically from the frozen Stage 5 chunk and resolved canonical source; provenance mismatches are rejected.</p>
        <div className="rag-context-chip-row">
          {generatedAnswer.evidence.map((item) => {
            const citation = citationByEvidenceId.get(item.evidence_id);
            return <article className={`rag-context-chip ${generatedAnswer.used_evidence_ids.includes(item.evidence_id) ? "used" : ""}`} key={item.evidence_id}>
              <div><strong>{item.evidence_id} · c{String(item.chunk_index).padStart(4, "0")}</strong><span>{item.ranked_seed_rank ? `rank #${item.ranked_seed_rank}` : `attached from rank #${item.source_rank}`}</span></div>
              <small>{item.reasons.join(" · ")} · Page {pageLabel(item.pages)} · {item.semantic_type}</small>
              {citation && <small className="rag-citation-trace">{citation.marker} {citation.display} · validated</small>}
              <p>{item.content_text}</p>
            </article>;
          })}
        </div>
      </section>}

      {rerankedResult && <section className="rag-trace-panel rag-context-panel">
        <div className="rag-panel-head">
          <div>
            <span className="rag-card-kicker">Stage 8.2 · Context assembly</span>
            <h2>Bounded structural evidence</h2>
          </div>
          <span className="rag-count-pill">+{rerankedResult.expanded_chunk_count} structural</span>
        </div>
        <p className="rag-empty-note">Ranked evidence is unchanged. Added chunks are one-hop structural attachments and do not receive retrieval ranks.</p>
        <div className="rag-context-chip-row">
          {rerankedResult.context_chunks.map((item) => <article className="rag-context-chip" key={item.chunk_id}>
            <div><strong>c{String(item.chunk_index).padStart(4, "0")}</strong><span>{item.ranked_seed_rank ? `rank #${item.ranked_seed_rank}` : `attached from rank #${item.source_rank}`}</span></div>
            <small>{item.reasons.join(" · ")} · Page {pageLabel(item.pages)} · {item.semantic_type}</small>
            <p>{item.content_text}</p>
          </article>)}
        </div>
      </section>}

      <section className="rag-trace-panel">
        <button className="rag-trace-toggle" type="button" onClick={() => setTraceOpen((value) => !value)}>
          <span>
            <strong>Retrieval trace</strong>
            <small>
              {result ? `${resultStrategy} · ${selectedDocument?.original_filename ?? result.document_id}` : `${strategy} · waiting for query`}
              {result && isRerankedResponse(result) ? ` · union=${result.candidate_union_count} · context=${result.context_chunk_count} · ${result.reranker_model}` : result && isHybridResponse(result) ? ` · RRF k=${result.rrf_k} · candidates=${result.candidate_k}` : ""}
            </small>
          </span>
          <span>{traceOpen ? "−" : "+"}</span>
        </button>
        {traceOpen && <div className={`rag-trace-content ${result && isRerankedResponse(result) ? "reranked" : result && isHybridResponse(result) ? "hybrid" : "dense"}`}>
          {result && isRerankedResponse(result) ? <>
            <div className="rag-lexical-plan">
              <span><strong>Candidate union</strong><small>{result.candidate_strategy} · {result.candidate_union_count} unique chunks</small></span>
              <code>{result.lexical_tsquery}</code>
              <small>{result.reranker_model} · {result.reranker_resolved_device} · max {result.reranker_max_length} tokens</small>
            </div>
            <div className="rag-trace-header reranked"><span>Rank</span><span>Chunk</span><span>Evidence</span><span>Dense</span><span>Lexical</span><span>Hybrid</span><span>Reranker</span></div>
            {result.hits.map((hit) => <div className="rag-trace-row reranked" key={hit.chunk_id}>
              <span>#{hit.rank}</span><code>c{String(hit.chunk_index).padStart(4, "0")}</code>
              <span><strong>{sectionLabel(hit.section_path)}</strong><small>Page {pageLabel(hit.pages)} · {hit.semantic_type}</small></span>
              <span>{hit.dense_rank ? `#${hit.dense_rank}` : "—"}<small>{hit.dense_score?.toFixed(4) ?? ""}</small></span>
              <span>{hit.lexical_rank ? `#${hit.lexical_rank}` : "—"}<small>{hit.lexical_score?.toFixed(4) ?? ""}</small></span>
              <span>#{hit.hybrid_candidate_rank}<small>{hit.fusion_score.toFixed(6)}</small></span>
              <strong>{hit.reranker_score.toFixed(4)}<small>model score</small></strong>
            </div>)}
          </> : result && isHybridResponse(result) ? <>
            <div className="rag-lexical-plan">
              <span><strong>Lexical query</strong><small>{result.lexical_query_mode} · {result.lexical_ranking_method}</small></span>
              <code>{result.lexical_tsquery}</code>
              <small>{result.lexical_terms.length} retained terms: {result.lexical_terms.join(", ")}</small>
            </div>
            <div className="rag-trace-header hybrid"><span>Rank</span><span>Chunk</span><span>Evidence</span><span>Dense</span><span>Lexical</span><span>Fusion</span></div>
            {result.hits.map((hit) => <div className="rag-trace-row hybrid" key={hit.chunk_id}>
              <span>#{hit.rank}</span><code>c{String(hit.chunk_index).padStart(4, "0")}</code>
              <span><strong>{sectionLabel(hit.section_path)}</strong><small>Page {pageLabel(hit.pages)} · {hit.semantic_type}</small></span>
              <span>{hit.dense_rank ? `#${hit.dense_rank}` : "—"}<small>{hit.dense_score?.toFixed(4) ?? ""}</small></span>
              <span>{hit.lexical_rank ? `#${hit.lexical_rank}` : "—"}<small>{hit.lexical_score?.toFixed(4) ?? ""}{hit.lexical_rank ? ` · ${hit.lexical_matched_term_count}/${result.lexical_terms.length}` : ""}</small></span>
              <strong>{hit.fusion_score.toFixed(6)}</strong>
            </div>)}
          </> : <>
            <div className="rag-trace-header"><span>Rank</span><span>Chunk</span><span>Evidence</span><span>Score</span></div>
            {result?.hits.map((hit) => <div className="rag-trace-row" key={hit.chunk_id}>
              <span>#{hit.rank}</span><code>c{String(hit.chunk_index).padStart(4, "0")}</code>
              <span><strong>{sectionLabel(hit.section_path)}</strong><small>Page {pageLabel(hit.pages)} · {hit.semantic_type}</small></span>
              <strong>{"score" in hit ? hit.score.toFixed(6) : "—"}</strong>
            </div>)}
          </>}
          {!result && <div className="rag-trace-empty">Run a query to populate the retrieval trace.</div>}
        </div>}
      </section>
    </main>
  );
}

const DATASET_ROWS = [
  ["What is a VASP?", "Definition", "Page 15 · §3 Definitions"],
  ["What enhanced CDD measures are required?", "Clause", "Page 41 · §8.3.1"],
  ["What records must be retained?", "Clause", "Pages 53–54 · §10"],
  ["When should a suspicious transaction be reported?", "Cross-section", "Pages 55–57 · §11"],
  ["Which customers require PEP controls?", "Multi-clause", "Pages 41–42 · §8.4"],
];

function Evaluation() {
  const [tab, setTab] = useState<"results" | "dataset">("results");
  const metrics = useMemo(() => [
    ["Recall@5", "0.96", "+8% vs dense"],
    ["MRR", "0.87", "+11% vs dense"],
    ["Faithfulness", "0.94", "answer quality"],
    ["Citation accuracy", "0.96", "source quality"],
  ], []);

  return (
    <main className="rag-page rag-evaluation-page">
      <div className="rag-page-heading">
        <div><span className="rag-eyebrow">Evaluation</span><h1>Measure retrieval before trusting answers.</h1><p>Prototype dashboard for benchmark questions, retrieval metrics, answer quality, and experiment comparison.</p></div>
        <div className="rag-tab-switch"><button type="button" className={tab === "results" ? "active" : ""} onClick={() => setTab("results")}>Results</button><button type="button" className={tab === "dataset" ? "active" : ""} onClick={() => setTab("dataset")}>Dataset</button></div>
      </div>

      {tab === "results" ? <>
        <section className="rag-metric-grid">{metrics.map(([label, value, detail]) => <article className="rag-metric-card" key={label}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>)}</section>
        <div className="rag-eval-grid">
          <section className="rag-panel rag-comparison-panel">
            <div className="rag-panel-head"><div><span className="rag-card-kicker">Retrieval evaluation</span><h2>Strategy comparison</h2></div><span className="rag-muted-label">Mock benchmark · 50 questions</span></div>
            <div className="rag-eval-table">
              <div className="rag-eval-table-head"><span>Strategy</span><span>R@1</span><span>R@3</span><span>R@5</span><span>MRR</span></div>
              <div><strong>Dense</strong><span>0.68</span><span>0.82</span><span>0.88</span><span>0.73</span></div>
              <div><strong>Hybrid</strong><span>0.75</span><span>0.89</span><span>0.94</span><span>0.81</span></div>
              <div className="best"><strong>Hybrid + Reranker</strong><span>0.84</span><span>0.94</span><span>0.96</span><span>0.87</span></div>
            </div>
          </section>
          <section className="rag-panel rag-quality-panel">
            <div className="rag-card-kicker">Answer evaluation</div><h2>Generation quality</h2>
            {[['Faithfulness',94],['Answer relevance',91],['Citation accuracy',96],['Citation completeness',93]].map(([name, value]) => <div className="rag-quality-row" key={String(name)}><div><strong>{name}</strong><span>{value}%</span></div><div><i style={{ width: `${value}%` }} /></div></div>)}
          </section>
        </div>
      </> : <section className="rag-panel rag-dataset-panel">
        <div className="rag-panel-head"><div><span className="rag-card-kicker">Golden evaluation set</span><h2>Benchmark questions</h2></div><button type="button" className="rag-secondary-action">+ Add question</button></div>
        <div className="rag-dataset-table"><div className="rag-dataset-head"><span>Question</span><span>Category</span><span>Expected evidence</span></div>{DATASET_ROWS.map((row) => <div key={row[0]}><strong>{row[0]}</strong><span className="rag-category-pill">{row[1]}</span><span>{row[2]}</span></div>)}</div>
      </section>}
    </main>
  );
}

export default function RagWorkbenchShell() {
  const [active, setActive] = useState<AppView>("overview");

  return (
    <div className="rag-global-shell">
      <AppHeader active={active} onChange={setActive} />
      {active === "overview" && <Overview onChange={setActive} />}
      {active === "documents" && <div className="rag-documents-host"><WorkbenchApp /></div>}
      {active === "playground" && <RagPlayground />}
      {active === "evaluation" && <Evaluation />}
    </div>
  );
}
