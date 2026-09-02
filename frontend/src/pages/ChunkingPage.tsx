import { useEffect, useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import type {
  ChunkingArtifact,
  ChunkingConfig,
  CleaningDecision,
  DocumentRecord,
  ResolvedStructureArtifact,
  RetrievalChunk,
} from "../types";

type Stage5Tab = "overview" | "cleaning" | "preview" | "quality" | "json";
type CleaningView = "exclude" | "context";

export const DEFAULT_CHUNKING_CONFIG: ChunkingConfig = {
  strategy: "semantic_v2",
  soft_min_tokens: 100,
  target_tokens: 450,
  max_tokens: 700,
  overlap_tokens: 60,
  keep_definitions_together: true,
  preserve_section_context: true,
  preserve_cross_page_continuations: true,
  group_dependent_children: true,
  attach_parent_context_on_split: true,
  pack_short_sibling_clauses: true,
  attach_contextual_notes: true,
  attach_group_headers_as_context: true,
  suppress_intro_only_figure_chunks: true,
  suppress_non_explanatory_figure_shells: true,
  exclude_navigation_sections: true,
  row_aware_table_splitting: true,
  cleaning: {
    exclude_page_headers: true,
    exclude_page_footers: true,
    exclude_margin_page_numbers: true,
    exclude_repeated_margin_text: true,
    deduplicate_overlapping_text: true,
    repeated_margin_min_pages: 3,
    include_footnotes: true,
    include_document_metadata: true,
    include_figures_without_text: false,
    normalize_whitespace: true,
    dehyphenate_line_breaks: false,
  },
};

function reasonLabel(reason: string) {
  const labels: Record<string, string> = {
    retrieval_content: "Retrieval content",
    section_context: "Section context",
    empty_content: "Empty content",
    page_header: "Page header",
    page_footer: "Page footer",
    margin_page_number: "Margin page number",
    repeated_margin_text: "Repeated margin text",
    duplicate_overlapping_text: "Overlapping duplicate text",
    footnote_disabled: "Footnote excluded by policy",
    document_metadata_disabled: "Document metadata excluded by policy",
    figure_without_text: "Figure without retrievable text",
    figure_intro_context_only: "Figure intro kept as context only",
    figure_non_explanatory_context_only: "Non-explanatory figure shell kept as context only",
    navigation_only: "Navigation-only content",
  };
  return labels[reason] ?? reason.replace(/_/g, " ");
}


function semanticTypeLabel(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatPages(pages: number[]) {
  if (!pages.length) return "—";
  if (pages.length === 1) return `p${pages[0]}`;
  const consecutive = pages.every((page, index) => index === 0 || page === pages[index - 1] + 1);
  return consecutive ? `p${pages[0]}–${pages[pages.length - 1]}` : pages.map((page) => `p${page}`).join(", ");
}

function Metric({ label, value, detail }: { label: string; value: string | number; detail?: string }) {
  return (
    <div className="stage5-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

function ToggleRow({
  label,
  detail,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  detail: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className={`stage5-policy-row ${disabled ? "disabled" : ""}`}>
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.checked)} />
      <i aria-hidden="true" />
    </label>
  );
}

function CleaningDecisionCard({ decision }: { decision: CleaningDecision }) {
  return (
    <article className={`stage5-cleaning-item ${decision.action}`}>
      <div className="stage5-cleaning-item-head">
        <span className="stage5-type-badge">{decision.type.replace(/_/g, " ")}</span>
        <span>Page {decision.page_number}</span>
      </div>
      <p>{decision.text_preview || "No text preview available."}</p>
      <small>{reasonLabel(decision.reason)}</small>
    </article>
  );
}

function ChunkListItem({ chunk, selected, onClick }: { chunk: RetrievalChunk; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`stage5-chunk-item ${selected ? "selected" : ""}`} onClick={onClick}>
      <span className="stage5-chunk-item-top">
        <strong>Chunk {chunk.chunk_index + 1}</strong>
        <em>{chunk.token_count} est. tokens</em>
      </span>
      <span className="stage5-chunk-item-meta">
        <span className="stage5-chunk-type-pill">{semanticTypeLabel(chunk.semantic_type)}</span>
        <span>{formatPages(chunk.pages)}</span>
      </span>
      <span className="stage5-chunk-preview">{chunk.content_text}</span>
    </button>
  );
}

export function ChunkingPage({
  document,
  resolved,
  artifact,
  generating,
  onGenerate,
  onReset,
  onOpenReview,
}: {
  document: DocumentRecord;
  resolved: ResolvedStructureArtifact | null;
  artifact: ChunkingArtifact | null;
  generating: boolean;
  onGenerate: (config: ChunkingConfig) => Promise<void>;
  onReset: () => Promise<void>;
  onOpenReview: (pageNumber: number) => void;
}) {
  const [activeTab, setActiveTab] = useState<Stage5Tab>("overview");
  const [config, setConfig] = useState<ChunkingConfig>(artifact?.config ?? DEFAULT_CHUNKING_CONFIG);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(artifact?.chunks[0]?.chunk_id ?? null);
  const [chunkSearch, setChunkSearch] = useState("");
  const [chunkType, setChunkType] = useState("all");
  const [cleaningView, setCleaningView] = useState<CleaningView>("exclude");
  const [cleaningReason, setCleaningReason] = useState("all");
  const [copyState, setCopyState] = useState("Copy JSON");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    setActiveTab("overview");
    setConfig(artifact?.config ?? DEFAULT_CHUNKING_CONFIG);
    setSelectedChunkId(artifact?.chunks[0]?.chunk_id ?? null);
    setChunkSearch("");
    setChunkType("all");
    setCleaningReason("all");
    setLocalError("");
  }, [document.document_id]);

  useEffect(() => {
    if (artifact) {
      setConfig(artifact.config);
      setSelectedChunkId((current) => current && artifact.chunks.some((chunk) => chunk.chunk_id === current) ? current : artifact.chunks[0]?.chunk_id ?? null);
    }
  }, [artifact?.generated_at]);

  const stage5Ready = Boolean(resolved && resolved.integrity.status === "pass" && resolved.review.stage5_eligible);
  const blockedReason = !resolved
    ? "Stage 5 needs a saved Resolved Stage 4.5 artifact. Review the document and save corrections first — an empty correction set is valid if the automatic structure is already correct."
    : resolved.integrity.status !== "pass"
      ? "Resolve the blocking structural-integrity errors in Review before generating retrieval chunks."
      : !resolved.review.stage5_eligible
        ? "This resolved artifact is not marked Stage-5 eligible. Re-validate the Review stage."
        : "";

  const configValid = config.soft_min_tokens <= config.target_tokens && config.target_tokens <= config.max_tokens && config.overlap_tokens < config.max_tokens;
  const configChanged = Boolean(artifact && JSON.stringify(config) !== JSON.stringify(artifact.config));

  const semanticTypes = useMemo(() => {
    return Array.from(new Set((artifact?.chunks ?? []).map((chunk) => chunk.semantic_type))).sort();
  }, [artifact]);

  const filteredChunks = useMemo(() => {
    const query = chunkSearch.trim().toLowerCase();
    return (artifact?.chunks ?? []).filter((chunk) => {
      if (chunkType !== "all" && chunk.semantic_type !== chunkType) return false;
      if (!query) return true;
      return [chunk.content_text, chunk.context_text, chunk.chunk_id, chunk.section_path.join(" ")]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [artifact, chunkSearch, chunkType]);

  const selectedChunk = useMemo(() => {
    return artifact?.chunks.find((chunk) => chunk.chunk_id === selectedChunkId) ?? filteredChunks[0] ?? null;
  }, [artifact, filteredChunks, selectedChunkId]);

  const cleaningReasons = useMemo(() => {
    const action = cleaningView === "exclude" ? "exclude" : "context";
    return Array.from(new Set((artifact?.cleaning.decisions ?? []).filter((item) => item.action === action).map((item) => item.reason))).sort();
  }, [artifact, cleaningView]);

  const filteredCleaning = useMemo(() => {
    const action = cleaningView === "exclude" ? "exclude" : "context";
    return (artifact?.cleaning.decisions ?? []).filter((item) => item.action === action && (cleaningReason === "all" || item.reason === cleaningReason));
  }, [artifact, cleaningReason, cleaningView]);

  function updateConfig<K extends keyof ChunkingConfig>(key: K, value: ChunkingConfig[K]) {
    setConfig((current) => ({ ...current, [key]: value }));
  }

  function updateCleaning<K extends keyof ChunkingConfig["cleaning"]>(key: K, value: ChunkingConfig["cleaning"][K]) {
    setConfig((current) => ({ ...current, cleaning: { ...current.cleaning, [key]: value } }));
  }

  async function generate() {
    setLocalError("");
    if (!configValid) {
      setLocalError("Target tokens must be ≤ max tokens, and overlap must be smaller than max tokens.");
      return;
    }
    try {
      await onGenerate(config);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "Stage 5 generation failed.");
    }
  }

  async function copyJson() {
    if (!artifact) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(artifact, null, 2));
      setCopyState("Copied ✓");
      window.setTimeout(() => setCopyState("Copy JSON"), 1600);
    } catch {
      setCopyState("Copy failed");
      window.setTimeout(() => setCopyState("Copy JSON"), 1600);
    }
  }

  function downloadJson() {
    if (!artifact) return;
    const blob = new Blob([JSON.stringify(artifact, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = `${document.original_filename.replace(/\.pdf$/i, "")}.stage5.chunks.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }


  return (
    <div className="stage5-page">
      <header className="stage5-heading">
        <div>
          <span className="eyebrow">Stage 5 · Retrieval preparation & chunking</span>
          <h2>Prepare trusted structure for retrieval</h2>
          <p>Filter retrieval noise, build semantic chunks, and preserve provenance back to the resolved document.</p>
        </div>
        <div className="stage5-heading-actions">
          <span className={`stage5-readiness ${stage5Ready ? "ready" : "blocked"}`}>{stage5Ready ? "Ready to chunk" : "Blocked"}</span>
          {artifact && <button type="button" className="secondary-button" disabled={generating} onClick={onReset}>Clear chunks</button>}
          <button type="button" className="primary-button compact" disabled={!stage5Ready || !configValid || generating} onClick={generate}>
            {generating ? "Generating…" : artifact ? "Regenerate chunks" : "Generate chunks"}
          </button>
        </div>
      </header>

      {!stage5Ready && <div className="stage5-gate blocked"><strong>Stage 5 eligibility gate</strong><span>{blockedReason}</span></div>}
      {stage5Ready && !artifact && <div className="stage5-gate ready"><strong>Resolved structure is eligible.</strong><span>Review the default retrieval policy and generate the first deterministic Stage 5 artifact.</span></div>}
      {configChanged && <div className="stage5-config-dirty"><strong>Configuration changed.</strong><span>Regenerate chunks to apply these settings to the saved Stage 5 artifact.</span></div>}
      {localError && <div className="stage5-local-error">{localError}</div>}

      <nav className="stage5-subnav" aria-label="Stage 5 views">
        {([
          ["overview", "Overview"],
          ["cleaning", "Cleaning"],
          ["preview", "Chunk Preview"],
          ["quality", "Quality Gate"],
          ["json", "Chunk JSON"],
        ] as Array<[Stage5Tab, string]>).map(([id, label]) => (
          <button type="button" key={id} className={activeTab === id ? "active" : ""} onClick={() => setActiveTab(id)}>{label}</button>
        ))}
      </nav>

      {activeTab === "overview" && (
        <div className="stage5-section-stack">
          <section className="stage5-card">
            <div className="stage5-card-head">
              <div><span className="eyebrow">Current artifact</span><h3>Stage 5 summary</h3></div>
              {artifact && <small>Generated {new Date(artifact.generated_at).toLocaleString()}</small>}
            </div>
            <div className="stage5-metrics-grid">
              <Metric label="Resolved elements" value={artifact?.cleaning.input_element_count ?? resolved?.structure.summary.element_count ?? "—"} />
              <Metric label="Retrieval elements" value={artifact?.cleaning.included_element_count ?? "—"} />
              <Metric label="Excluded" value={artifact?.cleaning.excluded_element_count ?? "—"} />
              <Metric label="Chunks" value={artifact?.summary.chunk_count ?? "—"} />
              <Metric label="Avg. chunk" value={artifact ? `${artifact.summary.average_chunk_tokens} est.` : "—"} detail="regex token estimate" />
              <Metric label="Largest chunk" value={artifact ? `${artifact.summary.max_chunk_tokens} est.` : "—"} detail={`max configured ${config.max_tokens}`} />
            </div>
          </section>

          {artifact && artifact.config.strategy === "semantic_v2" && (
            <section className="stage5-card">
              <div className="stage5-card-head horizontal"><div><span className="eyebrow">Deterministic quality</span><h3>{artifact.quality.status === "pass" ? "Retrieval structure passes hard quality checks" : "Review remaining structural risks"}</h3></div><span className={`stage5-readiness ${artifact.quality.status === "pass" ? "ready" : "blocked"}`}>{artifact.quality.status === "pass" ? "PASS" : "REVIEW"}</span></div>
              <div className="stage5-metrics-grid">
                <Metric label="Tiny signal" value={artifact.quality.tiny_chunk_count} detail={`below soft min ${artifact.quality.soft_min_tokens}`} />
                <Metric label="Orphan children" value={artifact.quality.orphan_child_count} />
                <Metric label="Dangling intros" value={artifact.quality.dangling_intro_count} />
                <Metric label="Parent context" value={artifact.quality.context_attached_chunk_count} />
                <Metric label="Dependency groups" value={artifact.quality.dependency_group_chunk_count} />
                <Metric label="Sibling packs" value={artifact.quality.sibling_pack_chunk_count} />
              </div>
              <p className="stage5-muted-copy">Tiny chunks are a review signal, not an automatic failure. Definitions and complete short units may legitimately remain below the soft minimum.</p>
            </section>
          )}

          <div className="stage5-config-grid">
            <section className="stage5-card">
              <div className="stage5-card-head"><div><span className="eyebrow">Chunking strategy</span><h3>{config.strategy === "semantic_v2" ? "Semantic v2 · deterministic refinement" : "Semantic v1 · legacy baseline"}</h3></div></div>
              <div className="stage5-form-grid">
                <label><span>Strategy</span><select value={config.strategy} onChange={(event: ChangeEvent<HTMLSelectElement>) => updateConfig("strategy", event.target.value as ChunkingConfig["strategy"])}><option value="semantic_v2">Semantic v2</option><option value="semantic_v1">Semantic v1 (legacy)</option></select></label>
                <label><span>Soft minimum</span><input type="number" min={20} max={2000} value={config.soft_min_tokens} onChange={(event: ChangeEvent<HTMLInputElement>) => updateConfig("soft_min_tokens", Number(event.target.value))} /></label>
                <label><span>Target tokens</span><input type="number" min={100} max={4000} value={config.target_tokens} onChange={(event: ChangeEvent<HTMLInputElement>) => updateConfig("target_tokens", Number(event.target.value))} /></label>
                <label><span>Maximum tokens</span><input type="number" min={150} max={8000} value={config.max_tokens} onChange={(event: ChangeEvent<HTMLInputElement>) => updateConfig("max_tokens", Number(event.target.value))} /></label>
                <label><span>Split overlap</span><input type="number" min={0} max={1000} value={config.overlap_tokens} onChange={(event: ChangeEvent<HTMLInputElement>) => updateConfig("overlap_tokens", Number(event.target.value))} /></label>
              </div>
              {!configValid && <p className="stage5-field-error">Soft minimum ≤ target ≤ maximum, and overlap must be smaller than maximum.</p>}
              <div className="stage5-preservation-list">
                <ToggleRow label="Keep definitions together" detail="Term + definition are grouped before size enforcement." checked={config.keep_definitions_together} onChange={() => {}} disabled />
                <ToggleRow label="Preserve section context" detail="Repeat the section path as retrieval context when useful." checked={config.preserve_section_context} onChange={(value) => updateConfig("preserve_section_context", value)} />
                <ToggleRow label="Preserve cross-page structure" detail="Page boundaries do not automatically split a semantic unit." checked={config.preserve_cross_page_continuations} onChange={() => {}} disabled />
                {config.strategy === "semantic_v2" && <>
                  <ToggleRow label="Group dependent children" detail="Use canonical parent/child relations instead of treating every subclause as a chunk boundary." checked={config.group_dependent_children} onChange={(value) => updateConfig("group_dependent_children", value)} />
                  <ToggleRow label="Repeat parent context after split" detail="If a hierarchy exceeds the hard maximum, later child groups retain the parent as retrieval context." checked={config.attach_parent_context_on_split} onChange={(value) => updateConfig("attach_parent_context_on_split", value)} />
                  <ToggleRow label="Pack short sibling clauses" detail="Conservatively combine adjacent short standalone clauses in the same section toward the target size." checked={config.pack_short_sibling_clauses} onChange={(value) => updateConfig("pack_short_sibling_clauses", value)} />
                  <ToggleRow label="Attach contextual notes" detail="Attach typed footnotes and confidently matched numbered notes to their nearby source unit." checked={config.attach_contextual_notes} onChange={(value) => updateConfig("attach_contextual_notes", value)} />
                  <ToggleRow label="Exclude navigation sections" detail="Suppress table-of-contents/index retrieval noise while leaving Resolved JSON unchanged." checked={config.exclude_navigation_sections} onChange={(value) => updateConfig("exclude_navigation_sections", value)} />
                  <ToggleRow label="Row-aware table splitting" detail="Split large tables between rows and repeat the table header as retrieval context." checked={config.row_aware_table_splitting} onChange={(value) => updateConfig("row_aware_table_splitting", value)} />
                </>}
              </div>
            </section>

            <section className="stage5-card stage5-explanation-card">
              <div className="stage5-card-head"><div><span className="eyebrow">Processing contract</span><h3>What Stage 5 does</h3></div></div>
              <ol>
                <li><strong>Eligibility</strong><span>Consumes only the saved resolved structure with passing integrity.</span></li>
                <li><strong>Cleaning</strong><span>Excludes retrieval noise without deleting evidence from Resolved JSON.</span></li>
                <li><strong>Semantic refinement</strong><span>Definitions, dependencies, continuations, notes, short siblings and tables are reconstructed before final chunk boundaries.</span></li>
                <li><strong>Size enforcement</strong><span>Oversized units split deterministically under the configured hard maximum.</span></li>
                <li><strong>Provenance</strong><span>Every chunk retains page, element, span, block, table and relationship references.</span></li>
              </ol>
              <div className="stage5-token-note"><strong>Token-count method</strong><span>{artifact?.token_count_method ?? "regex_estimate_v1"} — deterministic estimate, not a model-specific tokenizer.</span></div>
            </section>
          </div>
        </div>
      )}

      {activeTab === "cleaning" && (
        <div className="stage5-cleaning-layout">
          <section className="stage5-card stage5-policy-card">
            <div className="stage5-card-head"><div><span className="eyebrow">Retrieval policy</span><h3>Cleaning rules</h3></div></div>
            <p className="stage5-muted-copy">These rules affect retrieval output only. Resolved JSON remains unchanged.</p>
            <ToggleRow label="Exclude page headers" detail="Remove repeated running headers from retrieval." checked={config.cleaning.exclude_page_headers} onChange={(value) => updateCleaning("exclude_page_headers", value)} />
            <ToggleRow label="Exclude page footers" detail="Remove running footers from retrieval." checked={config.cleaning.exclude_page_footers} onChange={(value) => updateCleaning("exclude_page_footers", value)} />
            <ToggleRow label="Exclude margin page numbers" detail="Suppress standalone numbering detected near page margins." checked={config.cleaning.exclude_margin_page_numbers} onChange={(value) => updateCleaning("exclude_margin_page_numbers", value)} />
            <ToggleRow label="Detect repeated margin text" detail="Catch headers/footers that Stage 4 may have misclassified." checked={config.cleaning.exclude_repeated_margin_text} onChange={(value) => updateCleaning("exclude_repeated_margin_text", value)} />
            <ToggleRow label="Deduplicate overlapping text" detail="Exclude exact same-page text only when bounding boxes overlap by at least 90%." checked={config.cleaning.deduplicate_overlapping_text} onChange={(value) => updateCleaning("deduplicate_overlapping_text", value)} />
            {config.cleaning.exclude_repeated_margin_text && (
              <label className="stage5-inline-number"><span>Minimum repeated pages</span><input type="number" min={2} max={50} value={config.cleaning.repeated_margin_min_pages} onChange={(event: ChangeEvent<HTMLInputElement>) => updateCleaning("repeated_margin_min_pages", Number(event.target.value))} /></label>
            )}
            <ToggleRow label="Include footnotes" detail="Keep potentially meaningful referenced notes." checked={config.cleaning.include_footnotes} onChange={(value) => updateCleaning("include_footnotes", value)} />
            <ToggleRow label="Include document metadata" detail="Keep dates, identifiers and other semantic metadata." checked={config.cleaning.include_document_metadata} onChange={(value) => updateCleaning("include_document_metadata", value)} />
            <ToggleRow label="Include textless figures" detail="Unavailable until image semantic understanding is implemented." checked={false} onChange={() => {}} disabled />
            <ToggleRow label="Normalize whitespace" detail="Normalize layout whitespace for retrieval text." checked={config.cleaning.normalize_whitespace} onChange={(value) => updateCleaning("normalize_whitespace", value)} />
            <ToggleRow label="Dehyphenate line breaks" detail="Conservative opt-in because lexical hyphens can be ambiguous." checked={config.cleaning.dehyphenate_line_breaks} onChange={(value) => updateCleaning("dehyphenate_line_breaks", value)} />
          </section>

          <section className="stage5-card stage5-cleaning-results">
            <div className="stage5-card-head horizontal">
              <div><span className="eyebrow">Cleaning audit</span><h3>What is kept out of retrieval?</h3></div>
              {artifact && <span className="stage5-audit-count">{artifact.cleaning.excluded_element_count} excluded · {artifact.cleaning.context_element_count} context-only</span>}
            </div>
            {!artifact ? (
              <div className="stage5-empty-panel"><strong>No cleaning audit yet</strong><span>Generate chunks to inspect every exclusion/context decision and its reason.</span></div>
            ) : (
              <>
                <div className="stage5-cleaning-toolbar">
                  <div className="stage5-segmented">
                    <button type="button" className={cleaningView === "exclude" ? "active" : ""} onClick={() => { setCleaningView("exclude"); setCleaningReason("all"); }}>Excluded</button>
                    <button type="button" className={cleaningView === "context" ? "active" : ""} onClick={() => { setCleaningView("context"); setCleaningReason("all"); }}>Context only</button>
                  </div>
                  <select value={cleaningReason} onChange={(event: ChangeEvent<HTMLSelectElement>) => setCleaningReason(event.target.value)}>
                    <option value="all">All reasons</option>
                    {cleaningReasons.map((reason) => <option key={reason} value={reason}>{reasonLabel(reason)}</option>)}
                  </select>
                </div>
                <div className="stage5-reason-summary">
                  {Object.entries(artifact.cleaning.reason_counts).filter(([reason]) => reason !== "retrieval_content").map(([reason, count]) => (
                    <span key={reason}><strong>{count}</strong>{reasonLabel(reason)}</span>
                  ))}
                </div>
                <div className="stage5-cleaning-list">
                  {filteredCleaning.length ? filteredCleaning.map((decision) => <CleaningDecisionCard key={decision.element_id} decision={decision} />) : <div className="stage5-empty-panel compact"><span>No decisions match this filter.</span></div>}
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {activeTab === "preview" && (
        <section className="stage5-card stage5-preview-card">
          {!artifact ? (
            <div className="stage5-empty-panel large"><strong>No chunks generated yet</strong><span>Generate Stage 5 to inspect retrieval units before embedding/indexing.</span></div>
          ) : (
            <div className="stage5-preview-layout">
              <aside className="stage5-chunk-browser">
                <div className="stage5-browser-head">
                  <div><span className="eyebrow">Chunks</span><h3>{artifact.summary.chunk_count} retrieval units</h3></div>
                </div>
                <div className="stage5-browser-filters">
                  <input type="search" placeholder="Search chunk text…" value={chunkSearch} onChange={(event: ChangeEvent<HTMLInputElement>) => setChunkSearch(event.target.value)} />
                  <select value={chunkType} onChange={(event: ChangeEvent<HTMLSelectElement>) => setChunkType(event.target.value)}>
                    <option value="all">All semantic types</option>
                    {semanticTypes.map((type) => <option key={type} value={type}>{semanticTypeLabel(type)}</option>)}
                  </select>
                </div>
                <div className="stage5-chunk-list">
                  {filteredChunks.map((chunk) => <ChunkListItem key={chunk.chunk_id} chunk={chunk} selected={selectedChunk?.chunk_id === chunk.chunk_id} onClick={() => setSelectedChunkId(chunk.chunk_id)} />)}
                  {!filteredChunks.length && <div className="stage5-empty-panel compact"><span>No chunks match this filter.</span></div>}
                </div>
              </aside>

              <div className="stage5-chunk-inspector">
                {selectedChunk ? (
                  <>
                    <div className="stage5-inspector-head">
                      <div>
                        <span className="stage5-type-badge">{semanticTypeLabel(selectedChunk.semantic_type)}</span>
                        <h3>Chunk {selectedChunk.chunk_index + 1}</h3>
                        <code>{selectedChunk.chunk_id}</code>
                      </div>
                      <div className="stage5-inspector-actions">
                        <span>{selectedChunk.token_count} estimated tokens</span>
                        <button type="button" className="secondary-button" disabled={!selectedChunk.pages.length} onClick={() => selectedChunk.pages[0] && onOpenReview(selectedChunk.pages[0])}>Open source page in Review</button>
                      </div>
                    </div>
                    <div className="stage5-inspector-meta">
                      <Metric label="Pages" value={formatPages(selectedChunk.pages)} />
                      <Metric label="Source elements" value={selectedChunk.source_element_ids.length} />
                      <Metric label="Context elements" value={selectedChunk.context_element_ids?.length ?? 0} />
                      <Metric label="Source spans" value={selectedChunk.source_span_ids.length} />
                      <Metric label="Relationships" value={selectedChunk.relationship_ids.length} />
                    </div>
                    {selectedChunk.section_path.length > 0 && <div className="stage5-section-path"><span>Section path</span><strong>{selectedChunk.section_path.join(" › ")}</strong></div>}
                    {selectedChunk.split_total && <div className="stage5-split-note">Oversized semantic unit · part {selectedChunk.split_part} of {selectedChunk.split_total}</div>}
                    {selectedChunk.refinement_tags?.length > 0 && <div className="stage5-split-note">Refinement · {selectedChunk.refinement_tags.join(" · ").replace(/_/g, " ")}</div>}
                    <div className="stage5-text-block">
                      <span>Retrieval text</span>
                      <pre>{selectedChunk.text}</pre>
                    </div>
                    <details className="stage5-provenance">
                      <summary>Advanced provenance</summary>
                      <div><span>Source element IDs</span><code>{selectedChunk.source_element_ids.join("\n") || "—"}</code></div>
                      <div><span>Context element IDs</span><code>{selectedChunk.context_element_ids?.join("\n") || "—"}</code></div>
                      <div><span>Refinement tags</span><code>{selectedChunk.refinement_tags?.join("\n") || "—"}</code></div>
                      <div><span>Stage 3 span IDs</span><code>{selectedChunk.source_span_ids.join("\n") || "—"}</code></div>
                      <div><span>Stage 3 block IDs</span><code>{selectedChunk.source_block_ids.join("\n") || "—"}</code></div>
                      <div><span>Stage 3 table IDs</span><code>{selectedChunk.source_table_ids.join("\n") || "—"}</code></div>
                    </details>
                  </>
                ) : <div className="stage5-empty-panel"><span>Select a chunk to inspect its content and provenance.</span></div>}
              </div>
            </div>
          )}
        </section>
      )}

      {activeTab === "quality" && (
        <div className="stage5-section-stack">
          <section className="stage5-card">
            <div className="stage5-card-head horizontal">
              <div>
                <span className="eyebrow">Stage 5 · deterministic refinement quality</span>
                <h3>Validate chunk self-containedness before indexing</h3>
              </div>
              {artifact && <span className={`stage5-readiness ${artifact.quality.status === "pass" ? "ready" : "blocked"}`}>{artifact.quality.status === "pass" ? "PASS" : "REVIEW"}</span>}
            </div>
            {!artifact ? (
              <div className="stage5-empty-panel"><strong>Generate Stage 5 first</strong><span>Semantic v2 repairs generic structural risks during chunk generation and then validates the result.</span></div>
            ) : (
              <>
                <div className="stage5-metrics-grid">
                  <Metric label="Final chunks" value={artifact.summary.chunk_count} />
                  <Metric label={`Tiny (<${artifact.quality.soft_min_tokens})`} value={artifact.quality.tiny_chunk_count} detail="Signal only — complete short units are allowed" />
                  <Metric label="Orphan children" value={artifact.quality.orphan_child_count} detail="Hard structural risk" />
                  <Metric label="Dangling intros" value={artifact.quality.dangling_intro_count} detail="Hard structural risk" />
                  <Metric label="Navigation noise" value={artifact.quality.navigation_chunk_count} detail="Should be zero in Semantic v2" />
                  <Metric label="Standalone group headers" value={artifact.quality.standalone_group_header_chunk_count} detail="Should normally be zero" />
                  <Metric label="Figure shells" value={artifact.quality.non_explanatory_figure_chunk_count + artifact.quality.intro_only_figure_chunk_count} detail="Hard text-retrieval risk" />
                  <Metric label="Parent/context attached" value={artifact.quality.context_attached_chunk_count} />
                </div>
                <div className={`stage5-quality-status ${artifact.quality.status}`}>
                  <strong>{artifact.quality.status === "pass" ? "No blocking deterministic chunk-quality risks detected" : "Some chunks still require review"}</strong>
                  <span>Semantic v2 uses document structure rather than document-specific vocabulary: hierarchy, continuation relations, section boundaries, semantic types, adjacency, punctuation and token budgets.</span>
                </div>
              </>
            )}
          </section>

          {artifact && (
            <div className="stage5-quality-grid">
              <section className="stage5-card">
                <div className="stage5-card-head"><div><span className="eyebrow">Automatic repairs</span><h3>What Semantic v2 changed</h3></div></div>
                <div className="stage5-quality-list">
                  <div><strong>Dependency groups</strong><span>{artifact.quality.dependency_group_chunk_count} chunk(s) preserve parent + dependent-child meaning.</span></div>
                  <div><strong>Continuation merges</strong><span>{artifact.quality.continuation_merge_chunk_count} chunk(s) use explicit cross-page/continuation relations.</span></div>
                  <div><strong>Short sibling packs</strong><span>{artifact.quality.sibling_pack_chunk_count} chunk(s) combine adjacent short standalone clauses in one section.</span></div>
                  <div><strong>Contextual notes</strong><span>{artifact.quality.note_attachment_chunk_count} chunk(s) attach confidently matched notes/footnotes.</span></div>
                  <div><strong>Table captions</strong><span>{artifact.quality.caption_attachment_chunk_count} chunk(s) preserve caption ownership.</span></div>
                  <div><strong>Group-header context</strong><span>{artifact.quality.group_header_context_chunk_count} chunk(s) carry local heading context without spending a Top-K slot on the heading alone.</span></div>
                  <div><strong>Row-aware table splits</strong><span>{artifact.quality.table_split_chunk_count} chunk(s) repeat table headers as context rather than cutting arbitrary rows.</span></div>
                </div>
              </section>

              <section className="stage5-card">
                <div className="stage5-card-head"><div><span className="eyebrow">Remaining signals</span><h3>Manual review only when rules cannot guarantee structure</h3></div></div>
                {artifact.quality.signals.length ? (
                  <div className="stage5-quality-list">
                    {artifact.quality.signals.map((signal) => <div key={`${signal.code}-${signal.chunk_id}`}><strong>{signal.code.replace(/_/g, " ")}</strong><span>{signal.message}</span><code>{signal.chunk_id}</code></div>)}
                  </div>
                ) : <div className="stage5-empty-panel compact"><strong>No hard structural signals</strong><span>Tiny chunks may still exist by design, especially definitions and genuinely self-contained short statements.</span></div>}
              </section>
            </div>
          )}
        </div>
      )}

      {activeTab === "json" && (
        <section className="stage5-card stage5-json-card">
          <div className="stage5-card-head horizontal">
            <div><span className="eyebrow">Stage 5 artifact</span><h3>Chunk JSON</h3></div>
            <div className="stage5-json-actions">
              <button type="button" className="secondary-button" disabled={!artifact} onClick={copyJson}>{copyState}</button>
              <button type="button" className="secondary-button" disabled={!artifact} onClick={downloadJson}>Download JSON</button>
            </div>
          </div>
          <pre className="stage5-json-viewer">{artifact ? JSON.stringify(artifact, null, 2) : "No Stage 5 JSON artifact exists yet."}</pre>
        </section>
      )}
    </div>
  );
}
