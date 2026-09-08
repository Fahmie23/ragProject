import type { ChunkingArtifact, CorrectionArtifact, DocumentExtraction, DocumentRecord, EmbeddingStatus, ResolvedStructureArtifact, StructuredDocument } from "../types";

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

function StatusRow({ label, state, detail }: { label: string; state: "complete" | "available" | "pending" | "blocked"; detail?: string }) {
  const icon = state === "complete" ? "✓" : state === "available" ? "●" : state === "blocked" ? "!" : "○";
  return (
    <div className={`v2-status-row ${state}`}>
      <span className="v2-status-icon">{icon}</span>
      <span><strong>{label}</strong>{detail && <small>{detail}</small>}</span>
      <em>{state === "complete" ? "Complete" : state === "available" ? "Available" : state === "blocked" ? "Blocked" : "Not started"}</em>
    </div>
  );
}

function SummaryCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return <div className="v2-summary-card"><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</div>;
}

export function OverviewPage({
  document,
  extraction,
  structure,
  resolved,
  corrections,
  chunking,
  embeddingStatus,
}: {
  document: DocumentRecord;
  extraction: DocumentExtraction | null;
  structure: StructuredDocument | null;
  resolved: ResolvedStructureArtifact | null;
  corrections: CorrectionArtifact | null;
  chunking: ChunkingArtifact | null;
  embeddingStatus: EmbeddingStatus | null;
}) {
  const stage5Ready = Boolean(resolved && resolved.integrity.status === "pass" && resolved.review.stage5_eligible);
  const reviewState = structure ? (resolved ? "complete" : "available") : "pending";
  const chunkingState = chunking ? "complete" : stage5Ready ? "available" : structure ? "blocked" : "pending";
  const indexState = embeddingStatus?.complete ? "complete" : chunking?.quality.status === "pass" ? "available" : chunking ? "blocked" : "pending";

  return (
    <div className="v2-overview-page">
      <div className="v2-page-heading">
        <div><span className="eyebrow">Document overview</span><h2>Processing summary</h2><p>Inspect what has been produced so far before moving into page-level review.</p></div>
      </div>

      <section className="v2-overview-grid">
        <div className="v2-overview-card v2-document-summary">
          <div className="v2-card-title"><span className="eyebrow">Document</span><h3>{document.original_filename}</h3></div>
          <div className="v2-summary-grid">
            <SummaryCard label="PDF type" value={document.classification.pdf_type ?? "unknown"} />
            <SummaryCard label="Pages" value={document.classification.page_count ?? extraction?.summary.page_count ?? "—"} />
            <SummaryCard label="File size" value={formatBytes(document.size_bytes)} />
            <SummaryCard label="Text layer" value={document.classification.has_text_layer === false ? "No" : document.classification.has_text_layer === true ? "Yes" : "Unknown"} />
          </div>
          <div className="v2-source-note"><span>Source SHA-256</span><code>{document.sha256}</code></div>
        </div>

        <div className="v2-overview-card v2-pipeline-summary">
          <div className="v2-card-title"><span className="eyebrow">Pipeline</span><h3>Processing status</h3></div>
          <div className="v2-status-list">
            <StatusRow label="Upload" state="complete" detail="Original file stored immutably" />
            <StatusRow label="Classification" state={document.validation_status === "valid" ? "complete" : "blocked"} detail={document.classification.pdf_type ? `${document.classification.pdf_type} PDF` : undefined} />
            <StatusRow label="Extraction" state={extraction ? "complete" : "pending"} detail={extraction ? `${extraction.summary.text_block_count} text blocks` : "Ready to extract"} />
            <StatusRow label="Structure" state={structure ? "complete" : "pending"} detail={structure ? `${structure.summary.element_count} canonical elements` : extraction ? "Ready to build" : "Waiting for extraction"} />
            <StatusRow label="Manual review" state={reviewState} detail={resolved ? `${resolved.correction_count} saved correction${resolved.correction_count === 1 ? "" : "s"}` : structure ? "Review automatic structure" : undefined} />
            <StatusRow
              label="Knowledge preparation"
              state={chunkingState}
              detail={chunking ? `${chunking.summary.chunk_count} knowledge chunks` : stage5Ready ? "Ready to prepare knowledge" : structure ? "Complete document review first" : "Waiting for structure"}
            />
            <StatusRow
              label="Search index"
              state={indexState}
              detail={embeddingStatus?.complete
                ? `${embeddingStatus.embedded_chunk_count} vectors · ${embeddingStatus.dimension ?? "?"}D`
                : chunking?.quality.status === "pass"
                  ? "Ready to validate and index"
                  : chunking
                    ? "Resolve knowledge-quality signals first"
                    : "Waiting for knowledge chunks"}
            />
          </div>
        </div>
      </section>

      <section className="v2-overview-card">
        <div className="v2-card-title horizontal">
          <div><span className="eyebrow">Extraction & structure</span><h3>Current artifact summary</h3></div>
          <span className={`v2-readiness ${stage5Ready ? "ready" : "pending"}`}>{stage5Ready ? "Ready for knowledge preparation" : structure ? "Review available" : "Processing incomplete"}</span>
        </div>
        <div className="v2-summary-grid six">
          <SummaryCard label="Text blocks" value={extraction?.summary.text_block_count ?? "—"} />
          <SummaryCard label="Tables" value={structure?.summary.logical_table_count ?? extraction?.summary.table_count ?? "—"} />
          <SummaryCard label="Canonical elements" value={structure?.summary.element_count ?? "—"} />
          <SummaryCard label="Sections" value={structure?.summary.section_count ?? "—"} />
          <SummaryCard label="Definitions" value={structure?.summary.definition_count ?? "—"} />
          <SummaryCard label="Corrections" value={corrections?.operations.length ?? 0} />
        </div>
      </section>
      <details className="v2-technical-pipeline">
        <summary>Technical pipeline details</summary>
        <div className="v2-technical-pipeline-grid">
          <span><strong>Stage 3</strong>Layout-aware extraction</span>
          <span><strong>Stage 4</strong>Canonical structure reconstruction</span>
          <span><strong>Stage 4.5</strong>Human review & resolved structure</span>
          <span><strong>Stage 5</strong>Semantic knowledge chunking</span>
          <span><strong>Stage 6</strong>Embedding validation & vector index</span>
        </div>
      </details>
    </div>
  );
}
