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
          <PipelineStep label="Evaluation" detail="Frozen held-out answer + citation benchmark" state="done" />
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
          <p>Inspect frozen retrieval and answer/citation benchmarks with explicit formulas, provenance, and held-out scope instead of unsupported live quality scores.</p>
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

function CitedAnswerText({
  answer,
  citations,
  activeCitationId,
  onCitationSelect,
}: {
  answer: string;
  citations: GroundedAnswerResponse["citations"];
  activeCitationId: string | null;
  onCitationSelect: (citationId: string) => void;
}) {
  const citationByMarker = useMemo(() => new Map(citations.map((citation) => [citation.marker, citation])), [citations]);
  const parts = answer.split(/(\[\d+\])/g);

  return (
    <p className="rag-answer-copy rag-cited-answer-copy">
      {parts.map((part, index) => {
        const citation = citationByMarker.get(part);
        if (!citation) return <span key={`${index}-${part}`}>{part}</span>;
        return <button
          key={`${citation.citation_id}-${index}`}
          type="button"
          className="rag-answer-citation-link"
          data-active={activeCitationId === citation.citation_id ? "true" : "false"}
          onClick={() => onCitationSelect(citation.citation_id)}
          title={citation.display}
          aria-label={`${citation.marker} ${citation.display}. Inspect deterministic provenance.`}
        >
          {citation.marker}
        </button>;
      })}
    </p>
  );
}

type PlaygroundMode = "answer" | "retrieval";
type AnswerInspectorTab = "claims" | "retrieval" | "context" | "technical";

function RagPlayground() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [mode, setMode] = useState<PlaygroundMode>("answer");
  const [strategy, setStrategy] = useState<LiveRetrievalStrategy>("Dense");
  const [question, setQuestion] = useState("What are the requirements for delayed verification?");
  const [topK, setTopK] = useState(5);
  const [candidateK, setCandidateK] = useState(20);
  const [result, setResult] = useState<LiveRetrievalResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatedAnswer, setGeneratedAnswer] = useState<GroundedAnswerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [answerInspectorTab, setAnswerInspectorTab] = useState<AnswerInspectorTab>("claims");
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(null);

  function clearOutputs() {
    setResult(null);
    setGeneratedAnswer(null);
    setError(null);
    setAnswerInspectorTab("claims");
    setSelectedCitationId(null);
  }

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

  useEffect(() => {
    if (!selectedCitationId) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setSelectedCitationId(null);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [selectedCitationId]);

  async function runRetrieval() {
    const clean = question.trim();
    if (!clean || !documentId || running || generating) return;
    setRunning(true);
    setError(null);
    setGeneratedAnswer(null);
    setResult(null);
    setSelectedCitationId(null);
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
    if (!clean || !documentId || generating || running) return;
    setGenerating(true);
    setError(null);
    setGeneratedAnswer(null);
    setResult(null);
    setSelectedCitationId(null);
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

  function submitCurrentMode() {
    if (mode === "answer") return runGeneration();
    return runRetrieval();
  }

  function useSuggestedQuestion(nextQuestion: string) {
    setQuestion(nextQuestion);
    clearOutputs();
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
  const evidenceById = useMemo(
    () => new Map((generatedAnswer?.evidence ?? []).map((evidence) => [evidence.evidence_id, evidence])),
    [generatedAnswer],
  );
  const selectedCitation = selectedCitationId ? citationById.get(selectedCitationId) ?? null : null;
  const selectedCitationEvidence = selectedCitation ? evidenceById.get(selectedCitation.evidence_id) ?? null : null;
  const selectedCitationClaims = selectedCitation
    ? (generatedAnswer?.claims ?? []).filter((claim) => claim.citation_ids.includes(selectedCitation.citation_id))
    : [];
  const selectedCitationHref = selectedCitation && generatedAnswer
    ? (selectedCitation.pages[0] ? `${rawFileUrl(generatedAnswer.document_id)}#page=${selectedCitation.pages[0]}` : rawFileUrl(generatedAnswer.document_id))
    : null;
  const productionTrace = generatedAnswer?.retrieval_trace ?? null;
  const rerankedTraceRows = productionTrace?.reranked_candidates ?? [];
  const selectedTraceRows = rerankedTraceRows.filter((candidate) => candidate.selected_as_context_seed);

  const hasDocuments = documents.length > 0;
  const busy = running || generating;

  return (
    <main className="rag-page rag-playground-page">
      <div className="rag-page-heading rag-playground-heading">
        <div>
          <span className="rag-eyebrow">RAG Playground</span>
          <h1>Ask the document. Inspect the evidence.</h1>
          <p>The cited-answer mode always runs the frozen production RAG profile. Retrieval experiments are isolated so their controls cannot silently change generated answers.</p>
        </div>
        <div className="rag-tab-switch rag-playground-mode-switch" role="group" aria-label="Playground mode">
          <button type="button" className={mode === "answer" ? "active" : ""} onClick={() => { setMode("answer"); clearOutputs(); }}>Cited answer</button>
          <button type="button" className={mode === "retrieval" ? "active" : ""} onClick={() => { setMode("retrieval"); clearOutputs(); }}>Retrieval experiment</button>
        </div>
      </div>

      {mode === "retrieval" && <div className="rag-experiment-banner">
        <div><strong>Retrieval experiment</strong><span>These controls are diagnostic only and do not modify the frozen production profile used by cited answers.</span></div>
        <div className="rag-strategy-control" role="group" aria-label="Retrieval strategy">
          {(["Dense", "Hybrid", "Hybrid + Reranker"] as LiveRetrievalStrategy[]).map((item) => (
            <button
              type="button"
              key={item}
              className={strategy === item ? "active" : ""}
              onClick={() => { setStrategy(item); clearOutputs(); }}
            >
              {item}
            </button>
          ))}
        </div>
      </div>}

      <section className="rag-query-card">
        <div className={`rag-retrieval-controls ${mode === "answer" ? "answer-mode" : ""}`}>
          <label>
            <span>Document</span>
            <select value={documentId} onChange={(event) => { setDocumentId(event.target.value); clearOutputs(); }} disabled={!hasDocuments || busy}>
              {!hasDocuments && <option value="">No documents loaded</option>}
              {documents.map((document) => <option key={document.document_id} value={document.document_id}>{document.original_filename}</option>)}
            </select>
          </label>
          {mode === "retrieval" && <label>
            <span>Top K</span>
            <input type="number" min={1} max={50} value={topK} disabled={busy} onChange={(event) => setTopK(Math.max(1, Math.min(50, Number(event.target.value) || 1)))} />
          </label>}
          {mode === "retrieval" && strategy !== "Dense" && <label>
            <span>Candidate K</span>
            <input type="number" min={topK} max={100} value={candidateK} disabled={busy} onChange={(event) => setCandidateK(Math.max(topK, Math.min(100, Number(event.target.value) || topK)))} />
          </label>}
        </div>
        <label htmlFor="rag-question">Question</label>
        <div className="rag-query-row">
          <input
            id="rag-question"
            value={question}
            disabled={busy}
            onChange={(event) => { setQuestion(event.target.value); clearOutputs(); }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
              event.preventDefault();
              void submitCurrentMode();
            }}
            placeholder="Ask a question about the selected document"
          />
          <div className="rag-query-actions">
            {mode === "answer" ? <button className="rag-generate-action" type="button" disabled={busy || !documentId || !question.trim()} onClick={() => void runGeneration()}>
              {generating ? "Running RAG…" : "Ask with cited RAG"}
            </button> : <button type="button" disabled={busy || !documentId || !question.trim()} onClick={() => void runRetrieval()}>
              {running ? "Retrieving…" : "Retrieve"}
            </button>}
          </div>
        </div>
        {mode === "answer" ? <small className="rag-production-note">Production path: Dense + PostgreSQL FTS candidate union → weighted RRF → BGE reranker Top-5 → bounded Stage 8.2 context → grounded generation → deterministic citations. The user cannot tune this profile from the playground.</small> : <small className="rag-production-note">Experiment output is evidence-only. Top K, Candidate K, and strategy controls affect this diagnostic run only; they are never forwarded to <code>/api/generation/answer</code>.</small>}
        <div className="rag-suggestion-row">
          <span>Try:</span>
          <button type="button" disabled={busy} onClick={() => useSuggestedQuestion("What is a politically exposed person?")}>PEP definition</button>
          <button type="button" disabled={busy} onClick={() => useSuggestedQuestion("What measures are required when establishing a non-face-to-face business relationship?")}>Non-face-to-face</button>
          <button type="button" disabled={busy} onClick={() => useSuggestedQuestion("What information must be reported when there is a positive match with a designated person?")}>Appendix form</button>
        </div>
        {!hasDocuments && <div className="rag-playground-notice">No documents are available. Upload and process a document from the Documents module before asking questions.</div>}
        {error && <div className="rag-retrieval-error" role="alert">{error}</div>}
      </section>

      <div className="rag-playground-grid">
        <section className="rag-answer-panel" aria-live="polite">
          <div className="rag-panel-head">
            <div>
              <span className="rag-card-kicker">{mode === "answer" ? "Production RAG" : "Retrieval experiment"}</span>
              <h2>{mode === "answer" ? generatedAnswer?.question ?? "Ask a question to generate a cited answer" : result?.query ?? "Run a retrieval experiment"}</h2>
            </div>
            {mode === "answer" && generatedAnswer ? <span className="rag-grounded-pill">{generatedAnswer.citations.length} validated citations</span> : mode === "retrieval" && result ? <span className="rag-grounded-pill">{resultStrategy} · {hits.length} hits</span> : null}
          </div>

          {mode === "answer" ? generating ? <div className="rag-playground-loading"><strong>Running the frozen production pipeline</strong><span>Retrieving, reranking, assembling context, generating grounded claims, and validating citations.</span></div> : generatedAnswer ? <>
            <div className="rag-answer-status-row">
              <span className={`rag-answer-status ${generatedAnswer.status}`}>{generatedAnswer.status === "answered" ? "Grounded answer" : "Insufficient evidence"}</span>
              <span className="rag-answer-status-note">{generatedAnswer.status === "answered" ? `${generatedAnswer.citations.length} validated source${generatedAnswer.citations.length === 1 ? "" : "s"}` : "No citations emitted"}</span>
            </div>
            <CitedAnswerText answer={generatedAnswer.cited_answer || generatedAnswer.answer} citations={generatedAnswer.citations} activeCitationId={selectedCitationId} onCitationSelect={setSelectedCitationId} />
            {generatedAnswer.missing_information.length > 0 && <div className="rag-missing-info"><strong>Missing information</strong>{generatedAnswer.missing_information.map((item) => <span key={item}>{item}</span>)}</div>}
            <div className="rag-answer-facts" aria-label="Answer pipeline summary">
              <div><strong>{generatedAnswer.claims.length}</strong><span>claims</span></div>
              <div><strong>{generatedAnswer.context_chunk_count}</strong><span>context chunks</span></div>
              <div><strong>{generatedAnswer.used_evidence_ids.length}</strong><span>used evidence</span></div>
              <div><strong>{generatedAnswer.citations.length}</strong><span>validated sources</span></div>
            </div>
            <details className="rag-answer-tech-disclosure">
              <summary>Production profile details</summary>
              <div>
                <span><strong>Generation</strong>{generatedAnswer.generation_provider} · {generatedAnswer.generation_model}</span>
                <span><strong>Retrieval</strong>{generatedAnswer.retrieval_profile}</span>
                <span><strong>Context</strong>{generatedAnswer.context_strategy}</span>
                <span><strong>Citations</strong>{generatedAnswer.citation_version}</span>
              </div>
            </details>
          </> : <div className="rag-playground-empty"><strong>No answer yet</strong><span>Select a document, enter a question, then choose “Ask with cited RAG”.</span></div> : running ? <div className="rag-playground-loading"><strong>Running retrieval experiment</strong><span>This does not call the generation provider.</span></div> : topHit ? <>
            <p className="rag-answer-copy">{topHit.content_text}</p>
            <div className="rag-inline-citations">
              <button type="button">Rank #1</button>
              <button type="button">Page {pageLabel(topHit.pages)}</button>
              <button type="button">{topHit.semantic_type}</button>
            </div>
            <div className="rag-source-summary">
              <strong>{sectionLabel(topHit.section_path)}</strong>
              <span>Diagnostic retrieval evidence only. Switch to Cited answer to run the frozen production RAG path.</span>
            </div>
          </> : <div className="rag-playground-empty"><strong>No retrieval result yet</strong><span>Choose a strategy and run Retrieve to inspect evidence without calling the LLM.</span></div>}
        </section>

        <aside className="rag-sources-panel">
          <div className="rag-panel-head">
            <div><span className="rag-card-kicker">{mode === "answer" ? "Validated sources" : "Top evidence"}</span><h2>{mode === "answer" ? "Answer citations" : "Retrieved chunks"}</h2></div>
            <span className="rag-count-pill">{mode === "answer" ? `${generatedAnswer?.citations.length ?? 0} citations` : rerankedResult ? `${hits.length} ranked · ${rerankedResult.context_chunk_count} context` : `${hits.length} chunks`}</span>
          </div>
          {mode === "answer" ? generatedAnswer?.citations.map((citation) => {
            const href = citation.pages[0] ? `${rawFileUrl(generatedAnswer.document_id)}#page=${citation.pages[0]}` : rawFileUrl(generatedAnswer.document_id);
            const evidence = evidenceById.get(citation.evidence_id);
            return <article className="rag-source-card rag-citation-source-card" key={citation.citation_id}>
              <div><strong>{citation.marker} · {citation.evidence_id}</strong><span>{citation.validation_status}</span></div>
              <strong className="rag-source-section">{citation.display}</strong>
              {evidence && <>
                <p className="rag-source-preview">{evidence.content_text}</p>
                <details className="rag-source-evidence-disclosure">
                  <summary>Show full evidence</summary>
                  <div className="rag-source-evidence-full">
                    <p>{evidence.content_text}</p>
                  </div>
                </details>
              </>}
              <small className="rag-source-meta">{citation.source_filename} · {sectionLabel(citation.section_path)} · c{String(citation.chunk_index).padStart(4, "0")}</small>
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
          {mode === "answer" && generatedAnswer?.status === "insufficient_evidence" && <p className="rag-empty-note">No citations are emitted when the production pipeline abstains.</p>}
          {mode === "answer" && !generatedAnswer && <p className="rag-empty-note">Validated sources will appear here after a cited answer is generated.</p>}
          {mode === "retrieval" && result && hits.length === 0 && <p className="rag-empty-note">No chunks matched this query.</p>}
          {mode === "retrieval" && !result && <p className="rag-empty-note">Run a retrieval experiment to inspect the top evidence.</p>}
        </aside>
      </div>

      {mode === "answer" && generatedAnswer && <section className="rag-trace-panel rag-answer-inspector">
        <div className="rag-answer-inspector-head">
          <div>
            <span className="rag-card-kicker">Answer inspector</span>
            <h2>Inspect only when you need the technical detail</h2>
          </div>
          <div className="rag-tab-switch rag-answer-inspector-tabs" role="tablist" aria-label="Answer inspector">
            <button type="button" role="tab" aria-selected={answerInspectorTab === "claims"} className={answerInspectorTab === "claims" ? "active" : ""} onClick={() => setAnswerInspectorTab("claims")}>Claims</button>
            <button type="button" role="tab" aria-selected={answerInspectorTab === "retrieval"} className={answerInspectorTab === "retrieval" ? "active" : ""} onClick={() => setAnswerInspectorTab("retrieval")}>Retrieval</button>
            <button type="button" role="tab" aria-selected={answerInspectorTab === "context"} className={answerInspectorTab === "context" ? "active" : ""} onClick={() => setAnswerInspectorTab("context")}>Context</button>
            <button type="button" role="tab" aria-selected={answerInspectorTab === "technical"} className={answerInspectorTab === "technical" ? "active" : ""} onClick={() => setAnswerInspectorTab("technical")}>Technical</button>
          </div>
        </div>

        {answerInspectorTab === "claims" && <div className="rag-inspector-body">
          <p className="rag-inspector-intro">Generated claims retain their request-local evidence IDs and deterministic citation links. The frontend only renders this backend-owned mapping.</p>
          <div className="rag-claim-list rag-claim-list-compact">
            {generatedAnswer.claims.map((claim) => <article key={claim.claim_id} className="rag-claim-card rag-claim-card-compact">
              <div><strong>{claim.claim_id}</strong><span>{claim.evidence_ids.join(" · ")}</span></div>
              <p>{claim.text}</p>
              <div className="rag-claim-citations">
                {claim.citation_ids.map((citationId) => {
                  const citation = citationById.get(citationId);
                  if (!citation) return null;
                  return <button type="button" key={citationId} onClick={() => setSelectedCitationId(citationId)}>{citation.marker} {citation.display}</button>;
                })}
              </div>
            </article>)}
            {generatedAnswer.claims.length === 0 && <p className="rag-empty-note">No claims were emitted for this response.</p>}
          </div>
        </div>}

        {answerInspectorTab === "retrieval" && <div className="rag-inspector-body rag-production-retrieval-inspector">
          {productionTrace ? <>
            <div className="rag-retrieval-stage-grid" aria-label="Production retrieval stages">
              <div><span>Dense</span><strong>{productionTrace.dense_candidates.length}</strong><small>cosine-ranked candidates</small></div>
              <div><span>Lexical</span><strong>{productionTrace.lexical_candidates.length}</strong><small>PostgreSQL FTS candidates</small></div>
              <div><span>RRF union</span><strong>{productionTrace.fused_candidates.length}</strong><small>weighted reciprocal-rank fusion</small></div>
              <div><span>Reranked</span><strong>{selectedTraceRows.length}</strong><small>selected Top-{generatedAnswer.retrieval_top_k} seeds</small></div>
              <div><span>Context</span><strong>{generatedAnswer.context_chunk_count}</strong><small>{generatedAnswer.expanded_chunk_count} structural additions</small></div>
            </div>
            <div className="rag-retrieval-trace-note">
              <strong>Same execution trace</strong>
              <span>These values were captured from the exact retrieval execution that produced this answer. No second retrieval call is made for this inspector.</span>
            </div>
            <div className="rag-lexical-plan rag-production-lexical-plan">
              <span><strong>Lexical formulation</strong><small>{productionTrace.lexical_terms.length} retained content terms</small></span>
              <code>{productionTrace.lexical_tsquery || "—"}</code>
            </div>
            <div className="rag-production-retrieval-table" role="table" aria-label="Production reranker trace">
              <div className="rag-production-retrieval-head" role="row">
                <span>Rerank</span><span>Chunk</span><span>Evidence</span><span>Dense</span><span>Lexical</span><span>RRF</span><span>Reranker</span><span>Seed</span>
              </div>
              {rerankedTraceRows.map((candidate) => <div className={`rag-production-retrieval-row ${candidate.selected_as_context_seed ? "selected" : ""}`} role="row" key={candidate.chunk_id}>
                <strong>#{candidate.reranker_rank}</strong>
                <code>c{String(candidate.chunk_index).padStart(4, "0")}</code>
                <span><strong>{sectionLabel(candidate.section_path)}</strong><small>Page {pageLabel(candidate.pages)} · {candidate.semantic_type}</small></span>
                <span>{candidate.dense_rank ? `#${candidate.dense_rank}` : "—"}<small>{candidate.dense_score?.toFixed(4) ?? ""}</small></span>
                <span>{candidate.lexical_rank ? `#${candidate.lexical_rank}` : "—"}<small>{candidate.lexical_score?.toFixed(4) ?? ""}</small></span>
                <span>#{candidate.rank}<small>{candidate.fusion_score.toFixed(6)}</small></span>
                <strong>{candidate.reranker_score.toFixed(4)}<small>ranking score</small></strong>
                <span className={candidate.selected_as_context_seed ? "rag-used-badge" : "rag-available-badge"}>{candidate.selected_as_context_seed ? "SELECTED" : "DROPPED"}</span>
              </div>)}
            </div>
            <p className="rag-inspector-footnote">Dense cosine, PostgreSQL lexical rank, RRF fusion, and reranker scores are ranking/debugging signals. They are not calibrated probabilities that the answer is correct.</p>
          </> : <div className="rag-playground-empty"><strong>Retrieval trace unavailable</strong><span>This response predates Stage 14.3 or was produced without a retrieval trace.</span></div>}
        </div>}

        {answerInspectorTab === "context" && <div className="rag-inspector-body">
          <p className="rag-inspector-intro">{generatedAnswer.evidence.length} context chunks were available to generation; {generatedAnswer.used_evidence_ids.length} were explicitly referenced by generated claims.</p>
          <div className="rag-context-list">
            {generatedAnswer.evidence.map((item) => {
              const citation = citationByEvidenceId.get(item.evidence_id);
              const used = generatedAnswer.used_evidence_ids.includes(item.evidence_id);
              return <details className={`rag-context-row ${used ? "used" : ""}`} key={item.evidence_id}>
                <summary>
                  <span className="rag-context-row-id">{item.evidence_id}</span>
                  <span><strong>{sectionLabel(item.section_path)}</strong><small>Page {pageLabel(item.pages)} · {item.semantic_type} · {item.reasons.join(" · ")}</small></span>
                  <span className={used ? "rag-used-badge" : "rag-available-badge"}>{used ? "USED" : "AVAILABLE"}</span>
                </summary>
                <div className="rag-context-row-body">
                  {citation && <div className="rag-context-citation">{citation.marker} {citation.display} · validated</div>}
                  <p>{item.content_text}</p>
                  <small>Chunk c{String(item.chunk_index).padStart(4, "0")} · source rank #{item.source_rank}</small>
                </div>
              </details>;
            })}
          </div>
        </div>}

        {answerInspectorTab === "technical" && <div className="rag-inspector-body">
          <p className="rag-inspector-intro">Runtime metadata is shown for reproducibility and debugging. Scores here are configuration/runtime facts, not answer-quality probabilities.</p>
          <dl className="rag-technical-grid">
            <div><dt>Generation model</dt><dd>{generatedAnswer.generation_provider} · {generatedAnswer.generation_model}</dd></div>
            <div><dt>Prompt</dt><dd>{generatedAnswer.prompt_version}</dd></div>
            <div><dt>Retrieval profile</dt><dd>{generatedAnswer.retrieval_profile}</dd></div>
            <div><dt>Context strategy</dt><dd>{generatedAnswer.context_strategy}</dd></div>
            <div><dt>Candidate / top K</dt><dd>{generatedAnswer.retrieval_candidate_k} / {generatedAnswer.retrieval_top_k}</dd></div>
            <div><dt>RRF</dt><dd>k={generatedAnswer.retrieval_rrf_k} · dense {generatedAnswer.retrieval_dense_weight} · lexical {generatedAnswer.retrieval_lexical_weight}</dd></div>
            <div><dt>Citation version</dt><dd>{generatedAnswer.citation_version}</dd></div>
            <div><dt>Citation validation</dt><dd>{generatedAnswer.citation_validation.valid_citation_count}/{generatedAnswer.citation_validation.citation_count} valid</dd></div>
            <div><dt>Generation settings</dt><dd>temperature {generatedAnswer.generation_temperature} · max {generatedAnswer.generation_max_tokens} tokens · JSON {generatedAnswer.generation_json_mode ? "on" : "off"}</dd></div>
            <div><dt>Token usage</dt><dd>{generatedAnswer.usage?.total_tokens ?? "—"} total · {generatedAnswer.usage?.prompt_tokens ?? "—"} prompt · {generatedAnswer.usage?.completion_tokens ?? "—"} completion</dd></div>
          </dl>
        </div>}
      </section>}

      {mode === "answer" && generatedAnswer && selectedCitation && <aside className="rag-provenance-drawer" aria-label={`${selectedCitation.marker} deterministic citation provenance`}>
        <div className="rag-provenance-drawer-head">
          <div>
            <span className="rag-card-kicker">Citation details</span>
            <h2>{selectedCitation.marker} · {selectedCitation.display}</h2>
          </div>
          <button type="button" className="rag-provenance-close" onClick={() => setSelectedCitationId(null)} aria-label="Close citation provenance">×</button>
        </div>

        <div className="rag-provenance-validity">
          <span className="rag-provenance-valid-badge">✓ Deterministic citation valid</span>
          <p>This confirms that the deterministic source chain resolves to the cited PDF evidence. It is not a live semantic-entailment score.</p>
        </div>

        <div className="rag-provenance-summary-grid">
          <div><span>Citation</span><strong>{selectedCitation.marker}</strong><small>{selectedCitation.citation_id}</small></div>
          <div><span>Evidence</span><strong>{selectedCitation.evidence_id}</strong><small>request-local ID</small></div>
          <div><span>Chunk</span><strong>c{String(selectedCitation.chunk_index).padStart(4, "0")}</strong><small>{selectedCitation.chunk_id}</small></div>
          <div><span>PDF</span><strong>Page {pageLabel(selectedCitation.pages)}</strong><small>{selectedCitation.source_filename}</small></div>
        </div>

        <section className="rag-provenance-section">
          <div className="rag-provenance-section-head"><span>Claims using this citation</span><strong>{selectedCitationClaims.length}</strong></div>
          <div className="rag-provenance-claim-list">
            {selectedCitationClaims.map((claim) => <article key={claim.claim_id}>
              <strong>{claim.claim_id}</strong>
              <p>{claim.text}</p>
            </article>)}
            {selectedCitationClaims.length === 0 && <p className="rag-empty-note">No generated claim references this citation.</p>}
          </div>
        </section>

        <section className="rag-provenance-section">
          <details className="rag-provenance-chain-disclosure">
            <summary><span>Show provenance chain</span><small>{generatedAnswer.citation_version}</small></summary>
            <div className="rag-provenance-chain-content">
              <ol className="rag-provenance-chain">
                <li><span>1</span><div><strong>Generated claim</strong><small>{selectedCitationClaims.map((claim) => claim.claim_id).join(" · ") || "—"}</small></div></li>
                <li><span>2</span><div><strong>Request evidence</strong><small>{selectedCitation.evidence_id}{selectedCitationEvidence ? ` · ${selectedCitationEvidence.semantic_type}` : ""}</small></div></li>
                <li><span>3</span><div><strong>Frozen Stage 5 chunk</strong><small>c{String(selectedCitation.chunk_index).padStart(4, "0")} · {selectedCitation.chunk_id}</small></div></li>
                <li><span>4</span><div><strong>Canonical locator</strong><small>{selectedCitation.locators.map((locator) => locator.label).join(" · ") || "Page provenance"}</small></div></li>
                <li><span>5</span><div><strong>Source PDF</strong><small>{selectedCitation.source_filename} · Page {pageLabel(selectedCitation.pages)}</small></div></li>
              </ol>
              <div className="rag-provenance-locator-block">
                <div className="rag-provenance-section-head"><span>Canonical locators</span><strong>{selectedCitation.locators.length}</strong></div>
                <div className="rag-provenance-locator-list">
                  {selectedCitation.locators.map((locator, index) => <article key={`${locator.kind}-${locator.label}-${index}`}>
                    <div><span>{locator.kind}</span><strong>{locator.label}</strong></div>
                    <small>Page {pageLabel(locator.pages)}</small>
                    <details>
                      <summary>{locator.source_element_ids.length} source element{locator.source_element_ids.length === 1 ? "" : "s"}</summary>
                      <div className="rag-provenance-element-list">{locator.source_element_ids.map((elementId) => <code key={elementId}>{elementId}</code>)}</div>
                    </details>
                  </article>)}
                </div>
              </div>
            </div>
          </details>
        </section>

        {selectedCitationEvidence && <section className="rag-provenance-section">
          <div className="rag-provenance-section-head"><span>Evidence text</span><small>{selectedCitationEvidence.semantic_type} · source rank #{selectedCitationEvidence.source_rank}</small></div>
          <details className="rag-provenance-evidence">
            <summary>Show exact evidence supplied to generation</summary>
            <p>{selectedCitationEvidence.content_text}</p>
          </details>
        </section>}

        <div className="rag-provenance-footer">
          <small>Live Playground provenance is deterministic. Human semantic-entailment labels are shown only in the frozen Stage 11 Evaluation view.</small>
          {selectedCitationHref && <a href={selectedCitationHref} target="_blank" rel="noreferrer">Open PDF at page {selectedCitation.pages[0] ?? "source"} →</a>}
        </div>
      </aside>}

      {mode === "retrieval" && rerankedResult && <section className="rag-trace-panel rag-context-panel">
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

      {mode === "retrieval" && <section className="rag-trace-panel">
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
      </section>}
    </main>
  );
}

function Evaluation() {
  return (
    <main className="rag-page rag-evaluation-page">
      <div className="rag-page-heading">
        <div>
          <span className="rag-eyebrow">Evaluation</span>
          <h1>Frozen benchmark results, not live playground scores.</h1>
          <p>The Stage 11 evaluation APIs are read-only and reproducible. The detailed Evaluation Explorer UI is intentionally deferred to Stage 14.5 so the frontend never presents prototype or invented metrics.</p>
        </div>
      </div>
      <section className="rag-panel rag-evaluation-placeholder">
        <div className="rag-card-kicker">Stage 14.1 contract ready</div>
        <h2>Evaluation Explorer arrives in Stage 14.5</h2>
        <p>Until then, evaluation values remain available through the backend read APIs with benchmark scope, formulas, numerators/denominators, source artifacts, and question-level provenance.</p>
        <div className="rag-feature-list">
          <span>Frozen held-out benchmark</span>
          <span>Read only</span>
          <span>Human semantic labels</span>
          <span>0 API calls for reproduction</span>
        </div>
        <code>/api/evaluation/answer-citation/summary</code>
      </section>
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
