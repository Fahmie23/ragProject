import { useEffect, useMemo, useState } from "react";
import type { ChangeEvent, KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import {
  getCorrections,
  getDocument,
  getExtraction,
  getLayout,
  getResolvedStructure,
  getStructure,
  listDocuments,
  pagePreviewUrl,
  rawFileUrl,
  resetCorrections,
  runExtraction,
  runStructure,
  saveCorrections,
  uploadDocument,
} from "./api";
import type {
  CanonicalElement,
  CanonicalElementType,
  CorrectionArtifact,
  CorrectionOperation,
  CorrectionRelationshipSpec,
  DocumentExtraction,
  DocumentRecord,
  ImageBlock,
  LayoutArtifact,
  PageExtraction,
  ResolvedStructureArtifact,
  SectionRecord,
  StructuralRelation,
  StructuredDocument,
  TableExtraction,
  TextBlock,
} from "./types";
import "./styles.css";


type WorkspaceTab = "overview" | "extraction" | "structure" | "sandbox" | "json";
type JsonMode = "resolved" | "corrections" | "structure" | "layout" | "extraction";
type StageInspectorMode = "elements" | "json" | "corrections";
type RawInspectorItem =
  | { id: string; type: "text"; bbox: number[]; block: TextBlock }
  | { id: string; type: "image"; bbox: number[]; block: ImageBlock }
  | { id: string; type: "table"; bbox: number[]; table: TableExtraction };

const STRUCTURE_FILTERS: ("all" | CanonicalElementType)[] = [
  "all",
  "title",
  "subtitle",
  "document_metadata",
  "section_header",
  "clause",
  "subclause",
  "definition_term",
  "definition_text",
  "paragraph",
  "list_item",
  "table",
  "figure",
  "caption",
  "page_header",
  "page_footer",
  "footnote",
  "formula",
  "unknown",
];

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

function shortHash(hash: string) {
  return `${hash.slice(0, 10)}…${hash.slice(-8)}`;
}

function labelType(value: string) {
  return value.replace(/_/g, " ");
}

function useStoredBoolean(key: string, defaultValue = false) {
  const [value, setValue] = useState<boolean>(() => {
    if (typeof window === "undefined") return defaultValue;
    const stored = window.localStorage.getItem(key);
    return stored == null ? defaultValue : stored === "true";
  });

  useEffect(() => {
    if (typeof window !== "undefined") window.localStorage.setItem(key, String(value));
  }, [key, value]);

  return [value, setValue] as const;
}

function CollapseToggle({
  collapsed,
  onToggle,
  label,
}: {
  collapsed: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      className="collapse-toggle"
      onClick={onToggle}
      aria-expanded={!collapsed}
      title={`${collapsed ? "Expand" : "Collapse"} ${label}`}
      type="button"
    >
      <span aria-hidden="true">{collapsed ? "▸" : "▾"}</span>
      <span className="collapse-toggle-label">{collapsed ? "Show" : "Hide"}</span>
    </button>
  );
}

function StageRail({ document }: { document?: DocumentRecord | null }) {
  const extractionDone = document?.extraction_status === "completed";
  const structureDone = document?.structure_status === "completed";
  const validationDone = document?.validation_status === "valid";

  return (
    <div className="stage-rail" aria-label="RAG ingestion stages">
      <div className="stage-pill done"><span>1</span> Intake</div>
      <div className={`stage-pill ${validationDone ? "done" : "active"}`}><span>2</span> Validate</div>
      <div className={`stage-pill ${extractionDone ? "done" : validationDone ? "active" : "muted"}`}><span>3</span> Extract</div>
      <div className={`stage-pill ${structureDone ? "done" : extractionDone ? "active" : "muted"}`}><span>4</span> Structure</div>
      <div className={`stage-pill ${structureDone ? "active" : "muted"}`}><span>4.5</span> Review</div>
      <div className="stage-pill muted"><span>5</span> Chunk</div>
    </div>
  );
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`status-badge status-${value}`}>{labelType(value)}</span>;
}

function UploadPanel({ onUploaded }: { onUploaded: (record: DocumentRecord) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const record = await uploadDocument(file);
      onUploaded(record);
      setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="upload-panel">
      <label className="upload-dropzone">
        <input
          key={file?.name ?? "empty"}
          type="file"
          accept=".pdf,.docx,.txt,.md,.html,.htm"
          onChange={(e: ChangeEvent<HTMLInputElement>) => setFile(e.target.files?.[0] ?? null)}
        />
        <span className="upload-icon">＋</span>
        <strong>{file ? file.name : "Add document"}</strong>
        <small>PDF, DOCX, TXT, MD, HTML · max 50 MB</small>
      </label>
      <button className="primary-button" disabled={!file || busy} onClick={submit}>
        {busy ? "Uploading…" : "Upload"}
      </button>
      {error && <div className="inline-error">{error}</div>}
    </div>
  );
}

function DocumentSidebar({
  documents,
  selectedId,
  onSelect,
  onUploaded,
  collapsed,
  onToggleCollapsed,
}: {
  documents: DocumentRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onUploaded: (record: DocumentRecord) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <div className="brand-mark">R</div>
        {!collapsed && <div className="brand-copy"><strong>RAG Document Lab</strong><span>Ingestion workspace</span></div>}
        <button
          className="sidebar-toggle"
          onClick={onToggleCollapsed}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? "→" : "←"}
        </button>
      </div>

      {!collapsed ? (
        <UploadPanel onUploaded={onUploaded} />
      ) : (
        <button className="compact-upload-toggle" onClick={onToggleCollapsed} title="Expand sidebar to add a document" aria-label="Add document">＋</button>
      )}

      {!collapsed && <div className="sidebar-heading"><span>Documents</span><span>{documents.length}</span></div>}
      {collapsed && <div className="collapsed-document-count" title={`${documents.length} documents`}>{documents.length}</div>}

      <div className="document-list">
        {documents.map((doc) => (
          <button
            key={doc.document_id}
            className={`document-item ${collapsed ? "collapsed-item" : ""} ${selectedId === doc.document_id ? "selected" : ""}`}
            onClick={() => onSelect(doc.document_id)}
            title={collapsed ? doc.original_filename : undefined}
            aria-label={doc.original_filename}
          >
            <span className="file-kind">{doc.extension.replace(".", "").toUpperCase() || "FILE"}</span>
            {!collapsed && (
              <span className="document-copy">
                <strong title={doc.original_filename}>{doc.original_filename}</strong>
                <small>{doc.structure_status === "completed" ? "structured" : doc.classification.pdf_type ?? doc.classification.document_family}</small>
              </span>
            )}
            <span className={`tiny-dot ${doc.structure_status === "completed" ? "completed" : doc.extraction_status}`} />
          </button>
        ))}
        {documents.length === 0 && !collapsed && <p className="sidebar-empty">Upload your first document to begin.</p>}
      </div>
    </aside>
  );
}

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {sub && <small>{sub}</small>}
    </div>
  );
}

function StageCard({
  step,
  title,
  status,
  children,
}: {
  step: string;
  title: string;
  status: string;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useStoredBoolean(`rag-overview-stage-${step}-collapsed`, false);

  return (
    <section className={`section-card collapsible-stage-card ${collapsed ? "is-collapsed" : ""}`}>
      <div className="section-title collapsible-title-row">
        <div><span>Stage {step}</span><h3>{title}</h3></div>
        <div className="section-title-actions">
          <StatusBadge value={status} />
          <CollapseToggle collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} label={`Stage ${step} ${title}`} />
        </div>
      </div>
      {!collapsed && <div className="collapsible-stage-content">{children}</div>}
    </section>
  );
}

function Overview({
  document,
  extraction,
  structure,
  resolved,
  corrections,
}: {
  document: DocumentRecord;
  extraction: DocumentExtraction | null;
  structure: StructuredDocument | null;
  resolved: ResolvedStructureArtifact | null;
  corrections: CorrectionArtifact | null;
}) {
  return (
    <div className="overview-stack">
      <StageCard step="1" title="Document intake" status="completed">
        <div className="metric-grid four">
          <MetricCard label="Original file" value={document.original_filename} />
          <MetricCard label="Size" value={formatBytes(document.size_bytes)} />
          <MetricCard label="Stored type" value={document.extension || "—"} />
          <MetricCard label="SHA-256" value={shortHash(document.sha256)} />
        </div>
      </StageCard>

      <StageCard step="2" title="Validation & classification" status={document.validation_status}>
        {document.validation_errors.length > 0 && <div className="warning-box">{document.validation_errors.join(" ")}</div>}
        <div className="metric-grid five">
          <MetricCard label="Family" value={document.classification.document_family} />
          <MetricCard label="PDF type" value={document.classification.pdf_type ?? "—"} />
          <MetricCard label="Pages" value={document.classification.page_count ?? "—"} />
          <MetricCard label="Text pages" value={document.classification.text_pages ?? "—"} />
          <MetricCard label="Image pages" value={document.classification.image_pages ?? "—"} />
        </div>
      </StageCard>

      <StageCard step="3" title="Deterministic extraction" status={document.extraction_status}>
        {document.extraction_error && <div className="warning-box">{document.extraction_error}</div>}
        {extraction ? (
          <>
            {extraction.warnings.length > 0 && <div className="info-box">{extraction.warnings.join(" ")}</div>}
            <div className="metric-grid five">
              <MetricCard label="Text chars" value={extraction.summary.text_char_count.toLocaleString()} />
              <MetricCard label="Text blocks" value={extraction.summary.text_block_count} />
              <MetricCard label="Image blocks" value={extraction.summary.image_block_count} />
              <MetricCard label="Tables" value={extraction.summary.table_count} />
              <MetricCard label="Mode" value={extraction.extraction_mode} />
            </div>
            <div className="extractor-note">
              <span>Extractor</span><strong>{extraction.extractor.name} {extraction.extractor.version}</strong><small>Raw blocks, spans, tables and coordinates</small>
            </div>
          </>
        ) : <p className="empty-copy">Run Stage 3 after validation to create raw parser output.</p>}
      </StageCard>

      <StageCard step="4" title="Layout & canonical structure" status={document.structure_status}>
        {document.structure_error && <div className="warning-box">{document.structure_error}</div>}
        {structure ? (
          <>
            {structure.warnings.length > 0 && <div className="info-box">{structure.warnings.join(" ")}</div>}
            <div className="metric-grid five">
              <MetricCard label="Title" value={structure.title} sub={structure.title_source} />
              <MetricCard label="Sections" value={structure.summary.section_count} />
              <MetricCard label="Clauses" value={structure.summary.clause_count} />
              <MetricCard label="Logical tables" value={structure.summary.logical_table_count} />
              <MetricCard label="Figures" value={structure.summary.figure_count} />
            </div>
            <div className="metric-grid five stage4-secondary-metrics">
              <MetricCard label="Definitions" value={structure.summary.definition_count} />
              <MetricCard label="Appendices" value={structure.summary.appendix_count} />
              <MetricCard label="Relations" value={structure.summary.relation_count} />
              <MetricCard label="Elements" value={structure.summary.element_count} />
              <MetricCard label="Body chars" value={structure.summary.body_text_char_count.toLocaleString()} />
            </div>
            <div className="extractor-note">
              <span>Layout engine</span><strong>{structure.layout_engine.name} {structure.layout_engine.version}</strong><small>OCR disabled in Stage 4</small>
            </div>
          </>
        ) : <p className="empty-copy">Stage 4 becomes available after Stage 3. It reconstructs reading order and semantic page regions without chunking yet.</p>}
      </StageCard>

      <StageCard step="4.5" title="Human review & layout corrections" status={structure ? (corrections ? "completed" : "not_started") : "not_started"}>
        {structure ? (
          <div className="metric-grid four">
            <MetricCard label="Saved operations" value={corrections?.operations.length ?? 0} />
            <MetricCard label="Resolved structure" value={resolved ? "available" : "automatic only"} />
            <MetricCard label="Base schema" value={structure.schema_version} />
            <MetricCard label="Stage 5 input" value={resolved ? "resolved" : "automatic"} />
          </div>
        ) : <p className="empty-copy">Stage 4.5 becomes available after the automatic Stage 4 structure exists.</p>}
      </StageCard>
    </div>
  );
}

function TableMini({ table }: { table: TableExtraction | NonNullable<CanonicalElement["table"]> }) {
  const cells = table.cells.slice(0, 8).map((row) => row.slice(0, 6));
  return (
    <div className="table-mini-wrap">
      <table className="table-mini"><tbody>
        {cells.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, colIndex) => <td key={colIndex}>{cell ?? ""}</td>)}</tr>)}
      </tbody></table>
      {(table.row_count > 8 || table.col_count > 6) && <small>Preview truncated · {table.row_count} × {table.col_count}</small>}
    </div>
  );
}

function RawOverlayBox({
  item,
  page,
  selected,
  onClick,
}: {
  item: RawInspectorItem;
  page: PageExtraction;
  selected: boolean;
  onClick: () => void;
}) {
  const [x0, y0, x1, y1] = item.bbox;
  const style = {
    left: `${(x0 / page.width) * 100}%`,
    top: `${(y0 / page.height) * 100}%`,
    width: `${((x1 - x0) / page.width) * 100}%`,
    height: `${((y1 - y0) / page.height) * 100}%`,
  };
  return <button className={`overlay-box ${item.type} ${selected ? "selected" : ""}`} style={style} onClick={onClick} aria-label={item.id} />;
}

function RawInspectorCard({ item, active, onClick }: { item: RawInspectorItem; active: boolean; onClick: () => void }) {
  let body: ReactNode;
  if (item.type === "text") body = <p>{item.block.text || "Empty text block"}</p>;
  else if (item.type === "image") body = <p>{`${item.block.width ?? "?"} × ${item.block.height ?? "?"} px · ${item.block.extension ?? "image"}`}</p>;
  else body = <TableMini table={item.table} />;

  return (
    <button className={`inspector-card ${active ? "active" : ""}`} onClick={onClick}>
      <div className="inspector-card-head"><span className={`element-type ${item.type}`}>{item.type}</span><code>{item.id}</code></div>
      {body}
      <small>bbox [{item.bbox.map((x) => Math.round(x)).join(", ")}]</small>
    </button>
  );
}

function ExtractionWorkspace({
  document,
  extraction,
  pageNumber,
  setPageNumber,
}: {
  document: DocumentRecord;
  extraction: DocumentExtraction;
  pageNumber: number;
  setPageNumber: (value: number) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showOverlays, setShowOverlays] = useState(true);
  const [filter, setFilter] = useState<"all" | "text" | "image" | "table">("all");
  const [inspectorMode, setInspectorMode] = useState<StageInspectorMode>("elements");
  const [inspectorCollapsed, setInspectorCollapsed] = useStoredBoolean("rag-stage3-inspector-collapsed", false);

  useEffect(() => { setSelectedId(null); setFilter("all"); setInspectorMode("elements"); }, [document.document_id]);
  useEffect(() => setSelectedId(null), [pageNumber]);

  const page = extraction.pages[pageNumber - 1];
  const items = useMemo<RawInspectorItem[]>(() => {
    if (!page) return [];
    const blocks: RawInspectorItem[] = page.blocks.map((block) => block.type === "text"
      ? { id: block.block_id, type: "text", bbox: block.bbox, block }
      : { id: block.block_id, type: "image", bbox: block.bbox, block });
    const tables: RawInspectorItem[] = page.tables.map((table) => ({ id: table.table_id, type: "table", bbox: table.bbox, table }));
    return [...blocks, ...tables];
  }, [page]);

  const filteredItems = filter === "all" ? items : items.filter((item) => item.type === filter);
  if (!page) return <div className="empty-state">No extracted pages found.</div>;

  const pageJson = {
    stage: "stage_3_raw_extraction",
    schema_version: extraction.schema_version,
    document_id: extraction.document_id,
    source_filename: extraction.source_filename,
    source_sha256: extraction.source_sha256,
    extractor: extraction.extractor,
    page,
  };

  return (
    <div className={`extraction-workspace ${inspectorCollapsed ? "inspector-collapsed" : ""}`}>
      <div className="page-panel">
        <div className="panel-toolbar">
          <PageNav pageNumber={pageNumber} total={extraction.pages.length} setPageNumber={setPageNumber} />
          <div className="panel-toolbar-actions">
            <OverlayToggle checked={showOverlays} onChange={setShowOverlays} />
            <button className="panel-collapse-button" onClick={() => setInspectorCollapsed((value) => !value)}>{inspectorCollapsed ? "Show inspector" : "Hide inspector"}</button>
          </div>
        </div>
        {page.warnings.length > 0 && <div className="page-warning">{page.warnings.join(" ")}</div>}
        <div className="page-canvas-shell"><div className="page-canvas">
          <img src={pagePreviewUrl(document.document_id, pageNumber)} alt={`Page ${pageNumber}`} />
          {showOverlays && <div className="overlay-layer">{items.map((item) => (
            <RawOverlayBox key={item.id} item={item} page={page} selected={selectedId === item.id} onClick={() => setSelectedId(item.id)} />
          ))}</div>}
        </div></div>
      </div>

      {!inspectorCollapsed && <div className="inspector-panel">
        <div className="inspector-header"><div><span className="eyebrow">Stage 3 · Page {pageNumber}</span><h3>Raw page inspection</h3></div><span className="count-badge">{items.length}</span></div>
        <InspectorModeTabs mode={inspectorMode} onChange={setInspectorMode} />
        {inspectorMode === "elements" ? (
          <>
            <div className="filter-row">{(["all", "text", "image", "table"] as const).map((item) => (
              <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item}</button>
            ))}</div>
            <div className="inspector-list">
              {filteredItems.map((item) => <RawInspectorCard key={item.id} item={item} active={selectedId === item.id} onClick={() => setSelectedId(item.id)} />)}
              {filteredItems.length === 0 && <p className="empty-copy">No matching elements on this page.</p>}
            </div>
          </>
        ) : (
          <PageJsonPanel payload={pageJson} filename={`${document.document_id}-stage3-page-${pageNumber}.json`} />
        )}
      </div>}
    </div>
  );
}

function PageNav({ pageNumber, total, setPageNumber }: { pageNumber: number; total: number; setPageNumber: (value: number) => void }) {
  const [draft, setDraft] = useState(String(pageNumber));

  useEffect(() => setDraft(String(pageNumber)), [pageNumber]);

  function goToDraft() {
    const parsed = Number.parseInt(draft, 10);
    if (!Number.isFinite(parsed)) {
      setDraft(String(pageNumber));
      return;
    }
    const next = Math.min(total, Math.max(1, parsed));
    setDraft(String(next));
    setPageNumber(next);
  }

  return (
    <div className="page-nav">
      <button disabled={pageNumber <= 1} onClick={() => setPageNumber(pageNumber - 1)} title="Previous page">←</button>
      <label className="page-number-control">
        <span>Page</span>
        <input
          type="number"
          min={1}
          max={total}
          value={draft}
          onChange={(event: ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
          onKeyDown={(event: ReactKeyboardEvent<HTMLInputElement>) => { if (event.key === "Enter") goToDraft(); }}
          onBlur={goToDraft}
          aria-label={`Page number, 1 to ${total}`}
        />
        <span>/ {total}</span>
      </label>
      <button disabled={pageNumber >= total} onClick={() => setPageNumber(pageNumber + 1)} title="Next page">→</button>
    </div>
  );
}

function OverlayToggle({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="toggle"><input type="checkbox" checked={checked} onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.checked)} /><span /> Show boxes</label>;
}

function copyText(text: string) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
  return Promise.resolve();
}

function downloadJson(payload: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function PageJsonPanel({ payload, filename }: { payload: unknown; filename: string }) {
  const [copied, setCopied] = useState(false);
  const json = useMemo(() => JSON.stringify(payload, null, 2), [payload]);

  async function handleCopy() {
    await copyText(json);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="page-json-panel">
      <div className="page-json-actions">
        <span>Selected page only</span>
        <div>
          <button onClick={handleCopy}>{copied ? "Copied" : "Copy JSON"}</button>
          <button onClick={() => downloadJson(payload, filename)}>Download JSON</button>
        </div>
      </div>
      <pre className="page-json-viewer">{json}</pre>
    </div>
  );
}

function InspectorModeTabs({ mode, onChange, showCorrections = false }: { mode: StageInspectorMode; onChange: (mode: StageInspectorMode) => void; showCorrections?: boolean }) {
  return (
    <div className={`inspector-mode-tabs ${showCorrections ? "three" : ""}`} role="tablist" aria-label="Inspector mode">
      <button className={mode === "elements" ? "active" : ""} onClick={() => onChange("elements")}>Elements</button>
      <button className={mode === "json" ? "active" : ""} onClick={() => onChange("json")}>Page JSON</button>
      {showCorrections && <button className={mode === "corrections" ? "active" : ""} onClick={() => onChange("corrections")}>Corrections</button>}
    </div>
  );
}

function StructureOverlayBox({
  element,
  width,
  height,
  selected,
  onClick,
}: {
  element: CanonicalElement;
  width: number;
  height: number;
  selected: boolean;
  onClick: () => void;
}) {
  const [x0, y0, x1, y1] = element.bbox;
  const style = {
    left: `${(x0 / width) * 100}%`,
    top: `${(y0 / height) * 100}%`,
    width: `${((x1 - x0) / width) * 100}%`,
    height: `${((y1 - y0) / height) * 100}%`,
  };
  return (
    <button
      className={`structure-overlay semantic-${element.type} ${selected ? "selected" : ""}`}
      style={style}
      onClick={onClick}
      aria-label={`${element.type} ${element.element_id}`}
    />
  );
}

function StructureElementCard({
  element,
  active,
  onClick,
}: {
  element: CanonicalElement;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`structure-card ${active ? "active" : ""}`} onClick={onClick}>
      <div className="structure-card-head">
        <span className={`semantic-chip semantic-${element.type}`}>{labelType(element.type)}</span>
        <code>{element.element_id}</code>
      </div>
      {element.text && <p>{element.text}</p>}
      {element.table && <TableMini table={element.table} />}
      <div className="structure-meta">
        <span>order {element.reading_order + 1}</span>
        {element.section_id && <span>{element.section_id}</span>}
        {element.definition_entry_id && <span>{element.definition_entry_id}</span>}
        {element.clause_number && <span>clause {element.clause_number}</span>}
        {element.subclause_marker && <span>subclause {element.subclause_marker}</span>}
        {element.logical_table_id && <span>{element.logical_table_id}</span>}
        {element.figure_id && <span>{element.figure_id}</span>}
        {element.appendix_id && <span>{element.appendix_id}</span>}
        {element.heading_level && <span>H{element.heading_level} · {labelType(element.heading_level_source ?? "unknown")}</span>}
        {element.dominant_font_size && <span>{element.dominant_font_size}px</span>}
        {element.role_source !== "layout" && <span>role: {labelType(element.role_source)}</span>}
      </div>
      <small>source: {element.source.layout_box_class} · {element.source.stage3_block_ids.length} raw blocks</small>
    </button>
  );
}

function SectionOutline({ structure, onJump }: { structure: StructuredDocument; onJump: (section: SectionRecord) => void }) {
  return (
    <section className="outline-card">
      <div className="outline-head"><span className="eyebrow">Canonical document</span><h3>Section outline</h3></div>
      <div className="outline-list">
        <div className="outline-root-row">
          <span className="outline-level">H1</span>
          <span>
            <strong>{structure.title}</strong>
            <small>Document title · {labelType(structure.title_source)}</small>
          </span>
        </div>
        {structure.subtitle && (
          <div className="outline-support-row">
            <span className="outline-level muted-level">SUB</span>
            <span><strong>{structure.subtitle}</strong><small>Document subtitle</small></span>
          </div>
        )}
        {structure.sections.map((section) => (
          <button key={section.section_id} style={{ paddingLeft: `${12 + Math.max((section.level ?? 1) - 1, 0) * 16}px` }} onClick={() => onJump(section)}>
            <span className="outline-level">{section.level ? `H${section.level}` : "H?"}</span>
            <span>
              <strong>{section.title}</strong>
              <small>{section.kind === "question" ? "Question · " : section.kind === "appendix" ? "Appendix · " : ""}Page {section.page_number} · {labelType(section.level_source)} · {section.content_element_ids.length} content item{section.content_element_ids.length === 1 ? "" : "s"}</small>
            </span>
          </button>
        ))}
        {structure.sections.length === 0 && <p className="empty-copy">No section headers were detected. The reading-order elements are still preserved below.</p>}
      </div>
    </section>
  );
}


function makeManualId(pageNumber: number) {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10);
  return `p${pageNumber}-manual-${random}`;
}

function makeOperationId() {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `op-${random}`;
}

function makeManualRelationId() {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `manual-rel-${random}`;
}

function correctionOperationTouchesPage(operation: CorrectionOperation, pageNumber: number) {
  if (operation.relationships?.some((relation) => relation.source_page_number === pageNumber || relation.target_page_number === pageNumber)) return true;
  return operation.page_number === pageNumber;
}

function localApplyRelationshipCorrections(
  source: StructuralRelation[],
  operations: CorrectionOperation[],
): StructuralRelation[] {
  let relationships = source.map((relation) => ({ ...relation }));
  for (const operation of operations) {
    if (operation.operation === "add_relationship") {
      for (const spec of operation.relationships ?? []) {
        if (relationships.some((relation) => relation.relation_id === spec.relation_id)) continue;
        relationships.push({
          relation_id: spec.relation_id,
          type: spec.type,
          source_element_id: spec.source_element_id,
          target_element_id: spec.target_element_id,
          evidence: spec.evidence || "manual relationship correction",
        });
      }
    } else if (operation.operation === "remove_relationship") {
      const ids = new Set((operation.relationships ?? []).map((relation) => relation.relation_id));
      relationships = relationships.filter((relation) => !ids.has(relation.relation_id));
    }
  }
  return relationships;
}

function cloneCanonicalElement(element: CanonicalElement): CanonicalElement {
  return JSON.parse(JSON.stringify(element)) as CanonicalElement;
}

function clampBbox(bbox: number[], width: number, height: number): number[] {
  let [x0, y0, x1, y1] = bbox.map(Number);
  x0 = Math.max(0, Math.min(width - 1, x0));
  y0 = Math.max(0, Math.min(height - 1, y0));
  x1 = Math.max(x0 + 1, Math.min(width, x1));
  y1 = Math.max(y0 + 1, Math.min(height, y1));
  return [x0, y0, x1, y1].map((value) => Math.round(value * 1000) / 1000);
}

function localApplyCorrection(
  source: CanonicalElement[],
  operation: CorrectionOperation,
  width: number,
  height: number,
): CanonicalElement[] {
  const elements = source.map(cloneCanonicalElement);
  const indexOf = (id: string) => elements.findIndex((element) => element.element_id === id);

  if (operation.operation === "relabel" && operation.source_element_ids.length === 1 && operation.new_type) {
    const index = indexOf(operation.source_element_ids[0]);
    if (index >= 0) {
      elements[index].type = operation.new_type;
      elements[index].role_source = "manual_relabel_preview";
    }
    return elements;
  }

  if (operation.operation === "delete") {
    const ids = new Set(operation.source_element_ids);
    return elements.filter((element) => !ids.has(element.element_id));
  }

  if (operation.operation === "move_resize" && operation.source_element_ids.length === 1 && operation.result_elements.length === 1) {
    const index = indexOf(operation.source_element_ids[0]);
    if (index >= 0) {
      elements[index].bbox = clampBbox(operation.result_elements[0].bbox, width, height);
      elements[index].role_source = "manual_bbox_preview";
    }
    return elements;
  }

  if (operation.operation === "split" && operation.source_element_ids.length === 1) {
    const index = indexOf(operation.source_element_ids[0]);
    if (index < 0) return elements;
    const template = elements[index];
    const replacements = operation.result_elements.map((spec) => ({
      ...cloneCanonicalElement(template),
      element_id: spec.element_id,
      type: spec.type,
      bbox: clampBbox(spec.bbox, width, height),
      text: "",
      role_source: "manual_split_preview",
    }));
    elements.splice(index, 1, ...replacements);
    return elements;
  }

  if (operation.operation === "merge" && operation.result_elements.length === 1) {
    const ids = new Set(operation.source_element_ids);
    const selected = elements.filter((element) => ids.has(element.element_id));
    if (selected.length < 2) return elements;
    const insertAt = Math.min(...selected.map((element) => indexOf(element.element_id)));
    const spec = operation.result_elements[0];
    const merged = {
      ...cloneCanonicalElement(selected[0]),
      element_id: spec.element_id,
      type: spec.type,
      bbox: clampBbox(spec.bbox, width, height),
      text: selected.map((element) => element.text).filter(Boolean).join("\n"),
      role_source: "manual_merge_preview",
    };
    const remainder = elements.filter((element) => !ids.has(element.element_id));
    remainder.splice(Math.min(insertAt, remainder.length), 0, merged);
    return remainder;
  }

  if (operation.operation === "draw" && operation.result_elements.length === 1) {
    const spec = operation.result_elements[0];
    elements.push({
      element_id: spec.element_id,
      type: spec.type,
      page_number: operation.page_number,
      reading_order: elements.length,
      document_order: elements.length,
      bbox: clampBbox(spec.bbox, width, height),
      text: "",
      role_source: "manual_draw_preview",
      source: {
        layout_box_index: -1,
        layout_box_class: "manual_draw_preview",
        stage3_block_ids: [],
        stage3_table_ids: [],
      },
    });
    elements.sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]);
    return elements;
  }

  return elements;
}

function EditableStructureOverlay({
  element,
  width,
  height,
  selected,
  onSelect,
  onCommitBbox,
  editable = true,
}: {
  element: CanonicalElement;
  width: number;
  height: number;
  selected: boolean;
  onSelect: (multi: boolean) => void;
  onCommitBbox: (bbox: number[]) => void;
  editable?: boolean;
}) {
  const [preview, setPreview] = useState(element.bbox);
  const [drag, setDrag] = useState<null | {
    kind: "move" | "nw" | "ne" | "sw" | "se";
    clientX: number;
    clientY: number;
    bbox: number[];
    pageWidthPx: number;
    pageHeightPx: number;
  }>(null);

  useEffect(() => setPreview(element.bbox), [element.bbox.join(",")]);

  function startDrag(event: ReactPointerEvent<HTMLElement>, kind: "move" | "nw" | "ne" | "sw" | "se") {
    event.preventDefault();
    event.stopPropagation();
    onSelect(event.shiftKey);
    if (!editable) return;
    const canvas = event.currentTarget.closest(".page-canvas") as HTMLElement | null;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ kind, clientX: event.clientX, clientY: event.clientY, bbox: [...preview], pageWidthPx: rect.width, pageHeightPx: rect.height });
  }

  function bboxAtPointer(event: ReactPointerEvent<HTMLElement>, activeDrag: NonNullable<typeof drag>) {
    const dx = ((event.clientX - activeDrag.clientX) / Math.max(activeDrag.pageWidthPx, 1)) * width;
    const dy = ((event.clientY - activeDrag.clientY) / Math.max(activeDrag.pageHeightPx, 1)) * height;
    const [x0, y0, x1, y1] = activeDrag.bbox;
    let next = [x0, y0, x1, y1];
    if (activeDrag.kind === "move") next = [x0 + dx, y0 + dy, x1 + dx, y1 + dy];
    if (activeDrag.kind === "nw") next = [x0 + dx, y0 + dy, x1, y1];
    if (activeDrag.kind === "ne") next = [x0, y0 + dy, x1 + dx, y1];
    if (activeDrag.kind === "sw") next = [x0 + dx, y0, x1, y1 + dy];
    if (activeDrag.kind === "se") next = [x0, y0, x1 + dx, y1 + dy];
    return clampBbox(next, width, height);
  }

  function moveDrag(event: ReactPointerEvent<HTMLElement>) {
    if (!drag) return;
    event.preventDefault();
    setPreview(bboxAtPointer(event, drag));
  }

  function endDrag(event: ReactPointerEvent<HTMLElement>) {
    if (!drag) return;
    event.preventDefault();
    event.stopPropagation();
    const finalBbox = bboxAtPointer(event, drag);
    setPreview(finalBbox);
    setDrag(null);
    if (finalBbox.some((value, index) => Math.abs(value - element.bbox[index]) > 0.2)) onCommitBbox(finalBbox);
  }

  const [x0, y0, x1, y1] = preview;
  const style = {
    left: `${(x0 / width) * 100}%`,
    top: `${(y0 / height) * 100}%`,
    width: `${((x1 - x0) / width) * 100}%`,
    height: `${((y1 - y0) / height) * 100}%`,
  };

  return (
    <div
      className={`structure-overlay editable semantic-${element.type} ${editable ? "" : "relationship-select"} ${selected ? "selected" : ""}`}
      style={style}
      onPointerDown={(event: ReactPointerEvent<HTMLDivElement>) => startDrag(event, "move")}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onClick={(event: ReactMouseEvent<HTMLDivElement>) => { event.stopPropagation(); onSelect(event.shiftKey); }}
      title={`${labelType(element.type)} · ${element.element_id}`}
    >
      {editable && selected && (["nw", "ne", "sw", "se"] as const).map((handle) => (
        <span
          key={handle}
          className={`resize-handle ${handle}`}
          onPointerDown={(event: ReactPointerEvent<HTMLSpanElement>) => startDrag(event, handle)}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
        />
      ))}
    </div>
  );
}

function BboxEditor({
  element,
  width,
  height,
  onApply,
}: {
  element: CanonicalElement;
  width: number;
  height: number;
  onApply: (bbox: number[]) => void;
}) {
  const [values, setValues] = useState(element.bbox.map((value) => value.toFixed(1)));
  useEffect(() => setValues(element.bbox.map((value) => value.toFixed(1))), [element.element_id, element.bbox.join(",")]);
  const labels = ["x0", "y0", "x1", "y1"];
  return (
    <div className="bbox-editor">
      {labels.map((label, index) => (
        <label key={label}><span>{label}</span><input value={values[index]} onChange={(event: ChangeEvent<HTMLInputElement>) => {
          const next = [...values]; next[index] = event.target.value; setValues(next);
        }} /></label>
      ))}
      <button onClick={() => onApply(clampBbox(values.map(Number), width, height))}>Apply bbox</button>
    </div>
  );
}

function CorrectionsPanel({
  saved,
  session,
  pageNumber,
  documentId,
}: {
  saved: CorrectionOperation[];
  session: CorrectionOperation[];
  pageNumber: number;
  documentId: string;
}) {
  const [mode, setMode] = useState<"operations" | "json">("operations");
  const savedOnPage = saved.filter((operation) => correctionOperationTouchesPage(operation, pageNumber));
  const sessionOnPage = session.filter((operation) => correctionOperationTouchesPage(operation, pageNumber));
  const rows = [...savedOnPage, ...sessionOnPage];
  const payload = {
    stage: "stage_4_5_page_corrections",
    document_id: documentId,
    page_number: pageNumber,
    saved_operations: savedOnPage,
    unsaved_operations: sessionOnPage,
    operation_count: rows.length,
  };

  return (
    <div className="corrections-panel">
      <div className="correction-view-tabs">
        <button className={mode === "operations" ? "active" : ""} onClick={() => setMode("operations")}>Operations</button>
        <button className={mode === "json" ? "active" : ""} onClick={() => setMode("json")}>Correction JSON</button>
      </div>
      {mode === "operations" ? (
        <>
          <div className="corrections-summary"><strong>{rows.length}</strong><span>correction operation{rows.length === 1 ? "" : "s"} on page {pageNumber}</span></div>
          {rows.map((operation, index) => (
            <div className={`correction-row ${index >= savedOnPage.length ? "unsaved" : ""}`} key={operation.operation_id}>
              <div><strong>{labelType(operation.operation)}</strong><code>{operation.operation_id}</code></div>
              {operation.relationships?.length ? operation.relationships.map((relation) => (
                <small key={`${operation.operation_id}-${relation.relation_id}`}>
                  {relation.type}: page {relation.source_page_number} · {relation.source_element_id} → page {relation.target_page_number} · {relation.target_element_id}
                </small>
              )) : <small>{operation.source_element_ids.length ? `source: ${operation.source_element_ids.join(", ")}` : "new region"}</small>}
              {operation.new_type && <small>new type: {labelType(operation.new_type)}</small>}
            </div>
          ))}
          {rows.length === 0 && <p className="empty-copy">No manual corrections on this page.</p>}
        </>
      ) : (
        <PageJsonPanel payload={payload} filename={`${documentId}-stage45-corrections-page-${pageNumber}.json`} />
      )}
    </div>
  );
}

function StructureWorkspace({
  document,
  automaticStructure,
  resolved,
  pageNumber,
  setPageNumber,
  onOpenCorrectionSandbox,
}: {
  document: DocumentRecord;
  automaticStructure: StructuredDocument;
  resolved: ResolvedStructureArtifact | null;
  pageNumber: number;
  setPageNumber: (value: number) => void;
  onOpenCorrectionSandbox: () => void;
}) {
  const [viewMode, setViewMode] = useState<"automatic" | "resolved">(resolved ? "resolved" : "automatic");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showOverlays, setShowOverlays] = useState(true);
  const [filter, setFilter] = useState<"all" | CanonicalElementType>("all");
  const [inspectorMode, setInspectorMode] = useState<"elements" | "json">("elements");
  const [overviewCollapsed, setOverviewCollapsed] = useStoredBoolean("rag-structure-overview-collapsed", false);
  const [inspectorCollapsed, setInspectorCollapsed] = useStoredBoolean("rag-stage4-inspector-collapsed", false);

  useEffect(() => {
    if (!resolved && viewMode === "resolved") setViewMode("automatic");
  }, [resolved?.resolved_at]);

  useEffect(() => {
    setSelectedId(null);
    setFilter("all");
    setInspectorMode("elements");
  }, [document.document_id, pageNumber, viewMode]);

  const displayStructure = viewMode === "resolved" && resolved ? resolved.structure : automaticStructure;
  const page = displayStructure.pages[pageNumber - 1];
  if (!page) return <div className="empty-state">No structured pages found.</div>;

  const filtered = filter === "all" ? page.elements : page.elements.filter((element) => element.type === filter);
  const elementById = new Map(displayStructure.pages.flatMap((item) => item.elements).map((element) => [element.element_id, element] as const));
  const sectionById = new Map(displayStructure.sections.map((section) => [section.section_id, section] as const));
  const definitionById = new Map(displayStructure.definitions.map((entry) => [entry.definition_id, entry] as const));
  const crossPageRelations = displayStructure.relationships
    .filter((relation) => relation.type === "continues")
    .map((relation) => ({
      relation,
      source: elementById.get(relation.source_element_id),
      target: elementById.get(relation.target_element_id),
    }))
    .filter((item) => item.source && item.target && item.source.page_number !== item.target.page_number)
    .filter((item) => item.source!.page_number === pageNumber || item.target!.page_number === pageNumber);

  function crossPageRelationLabel(source: CanonicalElement, target: CanonicalElement) {
    const definitionId = source.definition_entry_id || target.definition_entry_id;
    if (definitionId) {
      const definition = definitionById.get(definitionId);
      if (definition) return { kind: "Definition", label: definition.term };
    }
    if (source.logical_table_id && source.logical_table_id === target.logical_table_id) {
      return { kind: "Table", label: source.logical_table_id };
    }
    if (source.section_id && source.section_id === target.section_id) {
      const section = sectionById.get(source.section_id);
      if (section) return { kind: "Hierarchy", label: section.title };
    }
    const hierarchyTypes = new Set<CanonicalElementType>(["clause", "subclause", "list_item"]);
    const kind = hierarchyTypes.has(source.type) || hierarchyTypes.has(target.type) ? "Hierarchy" : "Text";
    const compact = source.text.replace(/\s+/g, " ").trim();
    return { kind, label: compact.length > 72 ? `${compact.slice(0, 69)}…` : compact || "Cross-page content" };
  }

  const pageJson = buildStructuredSandboxPayload(
    displayStructure,
    pageNumber,
    viewMode === "resolved" && resolved ? "stage_4_5_resolved_structure" : "stage_4_canonical_structure",
    null,
  );

  function jumpToSection(section: SectionRecord) {
    setPageNumber(section.page_number);
    setSelectedId(section.element_id);
    setFilter("all");
    setInspectorMode("elements");
  }

  return (
    <div className="structure-view read-only-structure">
      <section className={`structure-overview-shell ${overviewCollapsed ? "is-collapsed" : ""}`}>
        <div className="structure-overview-head">
          <div><span className="eyebrow">Document-level context</span><strong>Outline & structure summary</strong></div>
          <CollapseToggle collapsed={overviewCollapsed} onToggle={() => setOverviewCollapsed((value) => !value)} label="document overview" />
        </div>
        {!overviewCollapsed && <div className="structure-top-grid">
          <SectionOutline structure={displayStructure} onJump={jumpToSection} />
          <section className="structure-summary-card">
            <span className="eyebrow">{viewMode === "resolved" && resolved ? "Stage 4.5 resolved output" : "Stage 4 automatic output"}</span>
            <h3>{displayStructure.title}</h3>
            {displayStructure.subtitle && <p className="document-subtitle">{displayStructure.subtitle}</p>}
            <p>{resolved ? `${resolved.correction_count} saved correction operation${resolved.correction_count === 1 ? "" : "s"} are available. This tab stays read-only; use Correction Sandbox for changes.` : "No saved manual corrections yet. This tab is intentionally read-only."}</p>
            <div className="structure-record-summary">
              <span><strong>{displayStructure.definitions.length}</strong> definitions</span>
              <span><strong>{displayStructure.clauses.length}</strong> clauses</span>
              <span><strong>{displayStructure.tables.length}</strong> logical tables</span>
              <span><strong>{displayStructure.figures.length}</strong> figures</span>
              <span><strong>{displayStructure.relationships.length}</strong> relations</span>
            </div>
          </section>
        </div>}
      </section>

      <div className="review-banner read-only-banner">
        <div>
          <span className="eyebrow">Read-only inspection</span>
          <strong>Structured Document</strong>
          <small>Inspect automatic or resolved structure here. All editing, correction JSON, and before/after comparison live in Correction Sandbox.</small>
        </div>
        <div className="read-only-actions">
          <div className="structure-state-toggle">
            <button className={viewMode === "automatic" ? "active" : ""} onClick={() => setViewMode("automatic")}>Automatic</button>
            <button disabled={!resolved} className={viewMode === "resolved" ? "active" : ""} onClick={() => setViewMode("resolved")}>Resolved</button>
          </div>
          <button className="primary-button compact" onClick={onOpenCorrectionSandbox}>Open Correction Sandbox</button>
        </div>
      </div>

      {crossPageRelations.length > 0 && <div className="cross-page-context-strip">
        <div className="cross-page-context-title">
          <span className="eyebrow">Cross-page structure</span>
          <strong>Continuation detected</strong>
        </div>
        <div className="cross-page-context-items">
          {crossPageRelations.map(({ relation, source, target }) => {
            if (!source || !target) return null;
            const meta = crossPageRelationLabel(source, target);
            const incoming = target.page_number === pageNumber;
            const destination = incoming ? source.page_number : target.page_number;
            return <button key={relation.relation_id} onClick={() => setPageNumber(destination)} title={relation.evidence}>
              {incoming && <span aria-hidden="true">←</span>}
              <span className="cross-page-kind">{meta.kind}</span>
              <strong>{meta.label}</strong>
              {incoming ? ` continued from page ${source.page_number}` : ` continues to page ${target.page_number}`}
              {!incoming && <span aria-hidden="true">→</span>}
            </button>;
          })}
        </div>
      </div>}

      <div className={`extraction-workspace ${inspectorCollapsed ? "inspector-collapsed" : ""}`}>
        <div className="page-panel">
          <div className="panel-toolbar">
            <PageNav pageNumber={pageNumber} total={displayStructure.pages.length} setPageNumber={setPageNumber} />
            <div className="panel-toolbar-actions">
              <OverlayToggle checked={showOverlays} onChange={setShowOverlays} />
              <button className="panel-collapse-button" onClick={() => setInspectorCollapsed((value) => !value)}>{inspectorCollapsed ? "Show inspector" : "Hide inspector"}</button>
            </div>
          </div>
          <div className="semantic-legend">
            <span><i className="legend-dot title" />Title/section</span>
            <span><i className="legend-dot metadata" />Metadata</span>
            <span><i className="legend-dot text" />Body</span>
            <span><i className="legend-dot definition" />Definition</span>
            <span><i className="legend-dot table" />Table</span>
            <span><i className="legend-dot excluded" />Header/footer</span>
          </div>
          <div className="page-canvas-shell"><div className="page-canvas">
            <img src={pagePreviewUrl(document.document_id, pageNumber)} alt={`Page ${pageNumber}`} />
            {showOverlays && <div className="overlay-layer">{page.elements.map((element) => (
              <StructureOverlayBox key={element.element_id} element={element} width={page.width} height={page.height} selected={selectedId === element.element_id} onClick={() => setSelectedId(element.element_id)} />
            ))}</div>}
          </div></div>
        </div>

        {!inspectorCollapsed && <div className="inspector-panel">
          <div className="inspector-header"><div><span className="eyebrow">{viewMode === "resolved" ? "Stage 4.5 resolved" : "Stage 4"} · Page {pageNumber}</span><h3>Canonical page inspection</h3></div><span className="count-badge">{page.elements.length}</span></div>
          <div className="inspector-mode-tabs" role="tablist" aria-label="Inspector mode">
            <button className={inspectorMode === "elements" ? "active" : ""} onClick={() => setInspectorMode("elements")}>Elements</button>
            <button className={inspectorMode === "json" ? "active" : ""} onClick={() => setInspectorMode("json")}>Page JSON</button>
          </div>
          {inspectorMode === "elements" ? <>
            <div className="structure-filter-wrap"><select value={filter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setFilter(event.target.value as "all" | CanonicalElementType)}>
              {STRUCTURE_FILTERS.map((type) => <option key={type} value={type}>{labelType(type)}</option>)}
            </select></div>
            <div className="inspector-list">
              {filtered.map((element) => <StructureElementCard key={element.element_id} element={element} active={selectedId === element.element_id} onClick={() => setSelectedId(element.element_id)} />)}
              {filtered.length === 0 && <p className="empty-copy">No matching canonical elements on this page.</p>}
            </div>
          </> : <PageJsonPanel payload={pageJson} filename={`${document.document_id}-${viewMode === "resolved" ? "stage45-resolved" : "stage4"}-page-${pageNumber}.json`} />}
        </div>}
      </div>
    </div>
  );
}

type SandboxSource = "stage3" | "stage4" | "resolved";
type SandboxPayloadKind = "stage3" | "structured";

type SandboxOverlayItem = {
  id: string;
  type: string;
  bbox: number[];
  text: string;
};

type ParsedSandbox = {
  payload: Record<string, unknown>;
  page: Record<string, unknown>;
  kind: SandboxPayloadKind;
  pageNumber: number;
  width: number;
  height: number;
  items: SandboxOverlayItem[];
};

function buildStage3SandboxPayload(extraction: DocumentExtraction, pageNumber: number) {
  const page = extraction.pages[pageNumber - 1];
  if (!page) return null;
  return {
    stage: "stage_3_raw_extraction",
    schema_version: extraction.schema_version,
    document_id: extraction.document_id,
    source_filename: extraction.source_filename,
    source_sha256: extraction.source_sha256,
    extractor: extraction.extractor,
    page,
  };
}

function buildStructuredSandboxPayload(
  structure: StructuredDocument,
  pageNumber: number,
  stage: "stage_4_canonical_structure" | "stage_4_5_resolved_structure",
  corrections?: CorrectionArtifact | null,
) {
  const page = structure.pages[pageNumber - 1];
  if (!page) return null;
  const pageElementIds = new Set(page.elements.map((element) => element.element_id));
  const relatedSectionIds = new Set(page.elements.map((element) => element.section_id).filter((value): value is string => Boolean(value)));
  return {
    stage,
    schema_version: structure.schema_version,
    document_id: structure.document_id,
    source_filename: structure.source_filename,
    source_sha256: structure.source_sha256,
    document_title: structure.title,
    document_subtitle: structure.subtitle ?? null,
    corrections_saved_on_page: corrections?.operations.filter((operation) => correctionOperationTouchesPage(operation, pageNumber)) ?? [],
    sections_referenced_on_page: structure.sections.filter((entry) => entry.page_number === pageNumber || relatedSectionIds.has(entry.section_id)),
    definitions_referenced_on_page: structure.definitions.filter((entry) =>
      (entry.term_element_id ? pageElementIds.has(entry.term_element_id) : false)
      || (entry.source_table_element_id ? pageElementIds.has(entry.source_table_element_id) : false)
      || entry.definition_element_ids.some((elementId) => pageElementIds.has(elementId))
      || (entry.start_page <= pageNumber && entry.end_page >= pageNumber)
    ),
    clauses_referenced_on_page: structure.clauses.filter((entry) => entry.page_number === pageNumber || pageElementIds.has(entry.element_id)),
    appendices_referenced_on_page: structure.appendices.filter((entry) => entry.start_page <= pageNumber && entry.end_page >= pageNumber),
    logical_tables_referenced_on_page: structure.tables.filter((entry) => entry.start_page <= pageNumber && entry.end_page >= pageNumber),
    figures_referenced_on_page: structure.figures.filter((entry) => entry.page_number === pageNumber),
    relationships_referenced_on_page: structure.relationships.filter((entry) => pageElementIds.has(entry.source_element_id) || pageElementIds.has(entry.target_element_id)),
    page,
  };
}

function sandboxSourceLabel(source: SandboxSource) {
  if (source === "stage3") return "Stage 3 raw";
  if (source === "resolved") return "Resolved Stage 4.5";
  return "Automatic Stage 4";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteBbox(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const nums = value.map(Number);
  return nums.every(Number.isFinite) ? nums : null;
}

function parseSandboxPayload(value: unknown): ParsedSandbox {
  if (!isRecord(value)) throw new Error("JSON root must be an object.");
  const pageCandidate = isRecord(value.page) ? value.page : value;
  const pageNumber = Number(pageCandidate.page_number);
  const width = Number(pageCandidate.width);
  const height = Number(pageCandidate.height);
  if (!Number.isInteger(pageNumber) || pageNumber < 1) throw new Error("page_number must be a positive integer.");
  if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) throw new Error("Page width and height must be positive numbers.");

  const items: SandboxOverlayItem[] = [];
  if (Array.isArray(pageCandidate.elements)) {
    for (let index = 0; index < pageCandidate.elements.length; index += 1) {
      const raw = pageCandidate.elements[index];
      if (!isRecord(raw)) continue;
      const bbox = finiteBbox(raw.bbox);
      if (!bbox) throw new Error(`elements[${index}].bbox must contain four finite numbers.`);
      items.push({
        id: typeof raw.element_id === "string" ? raw.element_id : `element-${index + 1}`,
        type: typeof raw.type === "string" ? raw.type : "unknown",
        bbox,
        text: typeof raw.text === "string" ? raw.text : "",
      });
    }
    return { payload: value, page: pageCandidate, kind: "structured", pageNumber, width, height, items };
  }

  if (Array.isArray(pageCandidate.blocks) || Array.isArray(pageCandidate.tables)) {
    const blocks = Array.isArray(pageCandidate.blocks) ? pageCandidate.blocks : [];
    const tables = Array.isArray(pageCandidate.tables) ? pageCandidate.tables : [];
    blocks.forEach((raw, index) => {
      if (!isRecord(raw)) return;
      const bbox = finiteBbox(raw.bbox);
      if (!bbox) throw new Error(`blocks[${index}].bbox must contain four finite numbers.`);
      items.push({
        id: typeof raw.block_id === "string" ? raw.block_id : `block-${index + 1}`,
        type: typeof raw.type === "string" ? raw.type : "text",
        bbox,
        text: typeof raw.text === "string" ? raw.text : "",
      });
    });
    tables.forEach((raw, index) => {
      if (!isRecord(raw)) return;
      const bbox = finiteBbox(raw.bbox);
      if (!bbox) throw new Error(`tables[${index}].bbox must contain four finite numbers.`);
      items.push({
        id: typeof raw.table_id === "string" ? raw.table_id : `table-${index + 1}`,
        type: "table",
        bbox,
        text: "",
      });
    });
    return { payload: value, page: pageCandidate, kind: "stage3", pageNumber, width, height, items };
  }

  throw new Error("Page JSON must contain either page.elements or page.blocks/page.tables.");
}

function sandboxItemFingerprint(item: SandboxOverlayItem) {
  return JSON.stringify({ type: item.type, bbox: item.bbox.map((value) => Math.round(value * 100) / 100), text: item.text });
}

function compareSandboxItems(baseline: SandboxOverlayItem[], candidate: SandboxOverlayItem[]) {
  const baselineMap = new Map(baseline.map((item) => [item.id, item]));
  const candidateMap = new Map(candidate.map((item) => [item.id, item]));
  let changed = 0;
  let unchanged = 0;
  for (const [id, item] of candidateMap) {
    const base = baselineMap.get(id);
    if (!base) continue;
    if (sandboxItemFingerprint(base) === sandboxItemFingerprint(item)) unchanged += 1;
    else changed += 1;
  }
  const added = [...candidateMap.keys()].filter((id) => !baselineMap.has(id)).length;
  const removed = [...baselineMap.keys()].filter((id) => !candidateMap.has(id)).length;
  return { changed, unchanged, added, removed, matches: changed === 0 && added === 0 && removed === 0 };
}

function SandboxOverlayBox({
  item,
  width,
  height,
  variant,
}: {
  item: SandboxOverlayItem;
  width: number;
  height: number;
  variant: "baseline" | "candidate";
}) {
  const [x0, y0, x1, y1] = item.bbox;
  const style = {
    left: `${(x0 / width) * 100}%`,
    top: `${(y0 / height) * 100}%`,
    width: `${((x1 - x0) / width) * 100}%`,
    height: `${((y1 - y0) / height) * 100}%`,
  };
  return <div className={`sandbox-overlay ${variant} semantic-${item.type}`} style={style} title={`${item.type} · ${item.id}${item.text ? `\n${item.text}` : ""}`} />;
}

type CrossPageEndpoint = {
  page_number: number;
  element_id: string;
  type: CanonicalElementType;
  text: string;
};

function CorrectionSandbox({
  document,
  extraction,
  structure,
  resolved,
  corrections,
  pageNumber,
  setPageNumber,
  onSaveCorrections,
  onResetAllCorrections,
  savingCorrections,
}: {
  document: DocumentRecord;
  extraction: DocumentExtraction | null;
  structure: StructuredDocument | null;
  resolved: ResolvedStructureArtifact | null;
  corrections: CorrectionArtifact | null;
  pageNumber: number;
  setPageNumber: (value: number) => void;
  onSaveCorrections: (operations: CorrectionOperation[]) => Promise<void>;
  onResetAllCorrections: () => Promise<void>;
  savingCorrections: boolean;
}) {
  const [mode, setMode] = useState<"preview" | "before" | "after" | "log">("preview");
  const [editScope, setEditScope] = useState<"layout" | "cross_page">("layout");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [workingElements, setWorkingElements] = useState<CanonicalElement[]>([]);
  const [sessionOps, setSessionOps] = useState<CorrectionOperation[]>([]);
  const [redoOps, setRedoOps] = useState<CorrectionOperation[]>([]);
  const [drawMode, setDrawMode] = useState(false);
  const [drawType, setDrawType] = useState<CanonicalElementType>("paragraph");
  const [drawStart, setDrawStart] = useState<[number, number] | null>(null);
  const [drawCurrent, setDrawCurrent] = useState<[number, number] | null>(null);
  const [showBeforeOverlay, setShowBeforeOverlay] = useState(true);
  const [showAfterOverlay, setShowAfterOverlay] = useState(true);
  const [filter, setFilter] = useState<"all" | CanonicalElementType>("all");
  const [elementsPanelCollapsed, setElementsPanelCollapsed] = useStoredBoolean("rag-correction-elements-collapsed", false);
  const [selectedEditorCollapsed, setSelectedEditorCollapsed] = useState(false);
  const [crossPageSource, setCrossPageSource] = useState<CrossPageEndpoint | null>(null);

  useEffect(() => {
    setSelectedIds([]);
    setSessionOps([]);
    setRedoOps([]);
    setDrawMode(false);
    setMode("preview");
    setSelectedEditorCollapsed(false);
    const next = (resolved?.structure ?? structure)?.pages[pageNumber - 1];
    if (next) setWorkingElements(next.elements.map(cloneCanonicalElement));
    else setWorkingElements([]);
  }, [document.document_id, pageNumber, structure?.structured_at, resolved?.resolved_at]);

  useEffect(() => {
    setCrossPageSource(null);
    setEditScope("layout");
  }, [document.document_id, structure?.structured_at]);

  if (!structure) return <div className="empty-state">Run Stage 4 before using Correction Sandbox.</div>;

  const automaticPage = structure.pages[pageNumber - 1];
  const resolvedStructure = resolved?.structure ?? structure;
  const basePage = resolvedStructure.pages[pageNumber - 1];
  const savedOperations = corrections?.operations ?? [];
  const savedPageOperations = savedOperations.filter((operation) => correctionOperationTouchesPage(operation, pageNumber));

  if (!automaticPage || !basePage) return <div className="empty-state">No structured page found.</div>;

  const selectedElement = selectedIds.length === 1 ? workingElements.find((element) => element.element_id === selectedIds[0]) ?? null : null;
  const filteredWorking = filter === "all" ? workingElements : workingElements.filter((element) => element.type === filter);
  const elementPageById = new Map<string, number>();
  const elementById = new Map<string, CanonicalElement>();
  for (const page of resolvedStructure.pages) {
    for (const element of page.elements) {
      elementPageById.set(element.element_id, page.page_number);
      elementById.set(element.element_id, element);
    }
  }
  for (const element of workingElements) {
    elementPageById.set(element.element_id, pageNumber);
    elementById.set(element.element_id, element);
  }
  const previewRelationships = localApplyRelationshipCorrections(resolvedStructure.relationships, sessionOps);
  const crossPageRelationsOnPage = previewRelationships.filter((relation) => {
    if (relation.type !== "continues") return false;
    const sourcePage = elementPageById.get(relation.source_element_id);
    const targetPage = elementPageById.get(relation.target_element_id);
    return Boolean(sourcePage && targetPage && sourcePage !== targetPage && (sourcePage === pageNumber || targetPage === pageNumber));
  });

  function makeOperation(
    partial: Omit<CorrectionOperation, "operation_id" | "created_at" | "relationships"> & { relationships?: CorrectionRelationshipSpec[] },
  ): CorrectionOperation {
    return {
      ...partial,
      relationships: partial.relationships ?? [],
      operation_id: makeOperationId(),
      created_at: new Date().toISOString(),
    };
  }

  function rebuildWorking(nextOps: CorrectionOperation[]) {
    let next = basePage.elements.map(cloneCanonicalElement);
    for (const operation of nextOps) next = localApplyCorrection(next, operation, basePage.width, basePage.height);
    setWorkingElements(next);
  }

  function addSessionOperation(operation: CorrectionOperation) {
    const next = [...sessionOps, operation];
    setSessionOps(next);
    setRedoOps([]);
    rebuildWorking(next);
  }

  function selectElement(elementId: string, multi = false) {
    setSelectedIds((current) => {
      if (!multi) return [elementId];
      return current.includes(elementId) ? current.filter((id) => id !== elementId) : [...current, elementId];
    });
  }

  function commitBbox(element: CanonicalElement, bbox: number[]) {
    addSessionOperation(makeOperation({
      operation: "move_resize",
      page_number: pageNumber,
      source_element_ids: [element.element_id],
      result_elements: [{ element_id: element.element_id, type: element.type, bbox }],
    }));
  }

  function relabelSelected(type: CanonicalElementType) {
    if (!selectedElement) return;
    addSessionOperation(makeOperation({
      operation: "relabel",
      page_number: pageNumber,
      source_element_ids: [selectedElement.element_id],
      result_elements: [],
      new_type: type,
    }));
  }

  function splitSelected() {
    if (!selectedElement) return;
    const [x0, y0, x1, y1] = selectedElement.bbox;
    if (y1 - y0 < 6) return;
    const mid = (y0 + y1) / 2;
    addSessionOperation(makeOperation({
      operation: "split",
      page_number: pageNumber,
      source_element_ids: [selectedElement.element_id],
      result_elements: [
        { element_id: makeManualId(pageNumber), type: selectedElement.type, bbox: [x0, y0, x1, mid] },
        { element_id: makeManualId(pageNumber), type: selectedElement.type, bbox: [x0, mid, x1, y1] },
      ],
    }));
    setSelectedIds([]);
  }

  function mergeSelected() {
    const selected = workingElements.filter((element) => selectedIds.includes(element.element_id));
    if (selected.length < 2) return;
    const bbox = [
      Math.min(...selected.map((element) => element.bbox[0])),
      Math.min(...selected.map((element) => element.bbox[1])),
      Math.max(...selected.map((element) => element.bbox[2])),
      Math.max(...selected.map((element) => element.bbox[3])),
    ];
    addSessionOperation(makeOperation({
      operation: "merge",
      page_number: pageNumber,
      source_element_ids: selected.map((element) => element.element_id),
      result_elements: [{ element_id: makeManualId(pageNumber), type: selected[0].type, bbox }],
    }));
    setSelectedIds([]);
  }

  function deleteSelected() {
    if (!selectedIds.length) return;
    addSessionOperation(makeOperation({
      operation: "delete",
      page_number: pageNumber,
      source_element_ids: selectedIds,
      result_elements: [],
    }));
    setSelectedIds([]);
  }

  function setSelectedAsCrossPageSource() {
    if (!selectedElement) return;
    if (sessionOps.length) {
      window.alert("Save, undo, or discard the current unsaved corrections before starting a cross-page link.");
      return;
    }
    setCrossPageSource({
      page_number: pageNumber,
      element_id: selectedElement.element_id,
      type: selectedElement.type,
      text: selectedElement.text,
    });
    setSelectedIds([]);
  }

  function linkSelectedAsContinuation() {
    if (!crossPageSource || !selectedElement) return;
    if (selectedElement.element_id === crossPageSource.element_id) return;
    if (pageNumber <= crossPageSource.page_number) {
      window.alert(`Choose a target on a later page than page ${crossPageSource.page_number}. A continues relationship always points forward.`);
      return;
    }
    if (previewRelationships.some((relation) => (
      relation.type === "continues"
      && relation.source_element_id === crossPageSource.element_id
      && relation.target_element_id === selectedElement.element_id
    ))) {
      window.alert("This continuation link already exists.");
      return;
    }

    addSessionOperation(makeOperation({
      operation: "add_relationship",
      page_number: crossPageSource.page_number,
      source_element_ids: [],
      result_elements: [],
      relationships: [{
        relation_id: makeManualRelationId(),
        type: "continues",
        source_element_id: crossPageSource.element_id,
        target_element_id: selectedElement.element_id,
        source_page_number: crossPageSource.page_number,
        target_page_number: pageNumber,
        evidence: "manual cross-page hierarchy continuation",
      }],
    }));
    setCrossPageSource(null);
  }

  function removeCrossPageRelation(relation: StructuralRelation) {
    const sourcePage = elementPageById.get(relation.source_element_id);
    const targetPage = elementPageById.get(relation.target_element_id);
    if (!sourcePage || !targetPage) return;
    addSessionOperation(makeOperation({
      operation: "remove_relationship",
      page_number: sourcePage,
      source_element_ids: [],
      result_elements: [],
      relationships: [{
        relation_id: relation.relation_id,
        type: relation.type,
        source_element_id: relation.source_element_id,
        target_element_id: relation.target_element_id,
        source_page_number: sourcePage,
        target_page_number: targetPage,
        evidence: relation.evidence,
      }],
    }));
  }

  function undo() {
    if (!sessionOps.length) return;
    const removed = sessionOps[sessionOps.length - 1];
    const next = sessionOps.slice(0, -1);
    setSessionOps(next);
    setRedoOps((items) => [removed, ...items]);
    rebuildWorking(next);
    setSelectedIds([]);
  }

  function redo() {
    if (!redoOps.length) return;
    const [nextOperation, ...rest] = redoOps;
    const next = [...sessionOps, nextOperation];
    setSessionOps(next);
    setRedoOps(rest);
    rebuildWorking(next);
    setSelectedIds([]);
  }

  async function savePage() {
    if (!sessionOps.length) return;
    await onSaveCorrections([...savedOperations, ...sessionOps]);
    setSessionOps([]);
    setRedoOps([]);
    setSelectedIds([]);
    setCrossPageSource(null);
  }

  async function resetPage() {
    if (!savedPageOperations.length && !sessionOps.length) return;
    if (!window.confirm(`Reset all manual corrections on page ${pageNumber}?`)) return;
    const remaining = savedOperations.filter((operation) => !correctionOperationTouchesPage(operation, pageNumber));
    if (remaining.length === 0) await onResetAllCorrections();
    else await onSaveCorrections(remaining);
    setSessionOps([]);
    setRedoOps([]);
    setSelectedIds([]);
    setCrossPageSource(null);
  }

  async function resetAll() {
    if (!savedOperations.length) return;
    if (!window.confirm("Reset every Stage 4.5 correction for this document?")) return;
    await onResetAllCorrections();
    setSessionOps([]);
    setRedoOps([]);
    setSelectedIds([]);
    setCrossPageSource(null);
  }

  function safeSetPage(next: number) {
    if (sessionOps.length && !window.confirm("This page has unsaved corrections. Discard them and change page?")) return;
    setSessionOps([]);
    setRedoOps([]);
    setSelectedIds([]);
    setDrawMode(false);
    setPageNumber(next);
  }

  function pointerPosition(event: ReactPointerEvent<HTMLDivElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(basePage.width, ((event.clientX - rect.left) / Math.max(rect.width, 1)) * basePage.width)),
      Math.max(0, Math.min(basePage.height, ((event.clientY - rect.top) / Math.max(rect.height, 1)) * basePage.height)),
    ];
  }

  function startDraw(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drawMode || event.target !== event.currentTarget) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = pointerPosition(event);
    setDrawStart(point);
    setDrawCurrent(point);
  }

  function moveDraw(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drawStart) return;
    setDrawCurrent(pointerPosition(event));
  }

  function endDraw(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drawStart || !drawCurrent) return;
    const end = pointerPosition(event);
    const bbox = clampBbox([
      Math.min(drawStart[0], end[0]), Math.min(drawStart[1], end[1]),
      Math.max(drawStart[0], end[0]), Math.max(drawStart[1], end[1]),
    ], basePage.width, basePage.height);
    setDrawStart(null);
    setDrawCurrent(null);
    setDrawMode(false);
    if (bbox[2] - bbox[0] < 3 || bbox[3] - bbox[1] < 3) return;
    addSessionOperation(makeOperation({
      operation: "draw",
      page_number: pageNumber,
      source_element_ids: [],
      result_elements: [{ element_id: makeManualId(pageNumber), type: drawType, bbox }],
    }));
  }

  const drawPreview = drawStart && drawCurrent ? clampBbox([
    Math.min(drawStart[0], drawCurrent[0]), Math.min(drawStart[1], drawCurrent[1]),
    Math.max(drawStart[0], drawCurrent[0]), Math.max(drawStart[1], drawCurrent[1]),
  ], basePage.width, basePage.height) : null;

  const beforePayload = buildStructuredSandboxPayload(structure, pageNumber, "stage_4_canonical_structure", null) as Record<string, unknown> | null;
  const previewStructure: StructuredDocument = { ...resolvedStructure, relationships: previewRelationships };
  const afterBase = buildStructuredSandboxPayload(previewStructure, pageNumber, "stage_4_5_resolved_structure", corrections) as Record<string, unknown> | null;
  const afterPayload = afterBase ? {
    ...afterBase,
    stage: "stage_4_5_correction_preview",
    corrections_saved_on_page: savedPageOperations,
    corrections_unsaved_on_page: sessionOps,
    page: { ...basePage, elements: workingElements },
  } : null;
  const beforeParsed = beforePayload ? parseSandboxPayload(beforePayload) : null;
  const afterParsed = afterPayload ? parseSandboxPayload(afterPayload) : null;
  const comparison = beforeParsed && afterParsed ? compareSandboxItems(beforeParsed.items, afterParsed.items) : null;
  const correctionLogPayload = {
    stage: "stage_4_5_page_corrections",
    document_id: document.document_id,
    page_number: pageNumber,
    saved_operations: savedPageOperations,
    unsaved_operations: sessionOps,
    operation_count: savedPageOperations.length + sessionOps.length,
  };

  return (
    <div className="correction-sandbox">
      <div className="sandbox-header-card correction-sandbox-header">
        <div>
          <span className="eyebrow">Stage 4.5 · Human review</span>
          <h3>Correction Sandbox</h3>
          <p>Manual layout and cross-page hierarchy correction happen here. Automatic Stage 4 stays immutable; saved operations produce the resolved Stage 4.5 structure.</p>
        </div>
        <PageNav pageNumber={pageNumber} total={structure.pages.length} setPageNumber={safeSetPage} />
      </div>

      <div className="sandbox-status-row">
        <div><strong>{savedPageOperations.length}</strong><span>saved on page</span></div>
        <div><strong>{sessionOps.length}</strong><span>unsaved</span></div>
        {editScope === "layout" && comparison && <div className={comparison.matches ? "match" : "changed"}><strong>{comparison.changed + comparison.added + comparison.removed}</strong><span>before/after changes</span></div>}
        {editScope === "cross_page" && <div className={sessionOps.some((operation) => operation.operation === "add_relationship" || operation.operation === "remove_relationship") ? "changed" : "match"}><strong>{sessionOps.filter((operation) => operation.operation === "add_relationship" || operation.operation === "remove_relationship").length}</strong><span>relationship changes</span></div>}
        <div className="sandbox-status-actions">
          <button disabled={!savedOperations.length || savingCorrections} onClick={resetAll}>Reset all corrections</button>
          <button disabled={!savedPageOperations.length && !sessionOps.length || savingCorrections} onClick={resetPage}>Reset page</button>
          <button className="primary-button compact" disabled={!sessionOps.length || savingCorrections} onClick={savePage}>{savingCorrections ? "Saving…" : `Save ${sessionOps.length || ""} correction${sessionOps.length === 1 ? "" : "s"}`}</button>
        </div>
      </div>

      <div className="correction-sandbox-tabs" role="tablist" aria-label="Correction sandbox view">
        <button className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>Preview & Edit</button>
        <button className={mode === "before" ? "active" : ""} onClick={() => setMode("before")}>Before JSON</button>
        <button className={mode === "after" ? "active" : ""} onClick={() => setMode("after")}>After JSON</button>
        <button className={mode === "log" ? "active" : ""} onClick={() => setMode("log")}>Correction Log</button>
      </div>

      {mode === "preview" && <>
        <div className="correction-scope-tabs" role="tablist" aria-label="Correction type">
          <button className={editScope === "layout" ? "active" : ""} onClick={() => { setEditScope("layout"); setCrossPageSource(null); setSelectedIds([]); }}>Layout correction</button>
          <button className={editScope === "cross_page" ? "active" : ""} onClick={() => { setEditScope("cross_page"); setDrawMode(false); setSelectedIds([]); }}>Cross-page relationships</button>
        </div>

        {editScope === "layout" ? <div className="correction-toolbar sandbox-correction-toolbar">
          <div className="correction-tools">
            <button className={drawMode ? "active" : ""} onClick={() => setDrawMode((value) => !value)}>＋ Draw</button>
            <select value={drawType} onChange={(event: ChangeEvent<HTMLSelectElement>) => setDrawType(event.target.value as CanonicalElementType)} title="Type for newly drawn regions">
              {STRUCTURE_FILTERS.filter((type): type is CanonicalElementType => type !== "all").map((type) => <option key={type} value={type}>{labelType(type)}</option>)}
            </select>
            <button disabled={selectedIds.length !== 1} onClick={splitSelected}>Split horizontal</button>
            <button disabled={selectedIds.length < 2} onClick={mergeSelected}>Merge selected</button>
            <button disabled={!selectedIds.length} onClick={deleteSelected}>Delete</button>
            <button disabled={!sessionOps.length} onClick={undo}>Undo</button>
            <button disabled={!redoOps.length} onClick={redo}>Redo</button>
          </div>
          <div className="sandbox-overlay-toggles">
            <label><input type="checkbox" checked={showBeforeOverlay} onChange={(event: ChangeEvent<HTMLInputElement>) => setShowBeforeOverlay(event.target.checked)} /> Before</label>
            <label><input type="checkbox" checked={showAfterOverlay} onChange={(event: ChangeEvent<HTMLInputElement>) => setShowAfterOverlay(event.target.checked)} /> After</label>
            <button className="panel-collapse-button" onClick={() => setElementsPanelCollapsed((value) => !value)}>{elementsPanelCollapsed ? "Show elements" : "Hide elements"}</button>
          </div>
        </div> : <div className="cross-page-correction-card">
          <div className="cross-page-correction-head">
            <div>
              <span className="eyebrow">Manual hierarchy correction</span>
              <strong>Link or remove cross-page continuations</strong>
              <small>Select the source element first, move to a later page, select the target, then create a <code>continues</code> relationship.</small>
            </div>
            <div className="correction-tools">
              <button disabled={selectedIds.length !== 1 || Boolean(crossPageSource)} onClick={setSelectedAsCrossPageSource}>Use selected as source</button>
              <button className="primary-button compact" disabled={!crossPageSource || !selectedElement || pageNumber <= (crossPageSource?.page_number ?? pageNumber)} onClick={linkSelectedAsContinuation}>Link continuation</button>
              <button disabled={!crossPageSource} onClick={() => { setCrossPageSource(null); setSelectedIds([]); }}>Cancel source</button>
              <button disabled={!sessionOps.length} onClick={undo}>Undo</button>
              <button disabled={!redoOps.length} onClick={redo}>Redo</button>
            </div>
          </div>

          <div className="cross-page-endpoint-grid">
            <div className={crossPageSource ? "endpoint-card ready" : "endpoint-card"}>
              <span>Source</span>
              {crossPageSource ? <>
                <strong>Page {crossPageSource.page_number} · {labelType(crossPageSource.type)}</strong>
                <code>{crossPageSource.element_id}</code>
                <small>{crossPageSource.text.replace(/\s+/g, " ").slice(0, 180) || "No text"}</small>
              </> : <small>Select an element on the page and click “Use selected as source”.</small>}
            </div>
            <div className={crossPageSource && selectedElement && pageNumber > crossPageSource.page_number ? "endpoint-card ready" : "endpoint-card"}>
              <span>Target</span>
              {selectedElement ? <>
                <strong>Page {pageNumber} · {labelType(selectedElement.type)}</strong>
                <code>{selectedElement.element_id}</code>
                <small>{selectedElement.text.replace(/\s+/g, " ").slice(0, 180) || "No text"}</small>
              </> : <small>{crossPageSource ? `Move to a page after ${crossPageSource.page_number}, then select the continuation element.` : "Choose the source first."}</small>}
            </div>
          </div>

          <div className="cross-page-existing-links">
            <div className="cross-page-existing-head"><strong>Cross-page links touching page {pageNumber}</strong><span className="count-badge">{crossPageRelationsOnPage.length}</span></div>
            {crossPageRelationsOnPage.map((relation) => {
              const sourcePage = elementPageById.get(relation.source_element_id);
              const targetPage = elementPageById.get(relation.target_element_id);
              const sourceElement = elementById.get(relation.source_element_id);
              const targetElement = elementById.get(relation.target_element_id);
              return <div className="cross-page-link-row" key={relation.relation_id}>
                <div>
                  <strong>Page {sourcePage} → Page {targetPage}</strong>
                  <code>{relation.source_element_id} → {relation.target_element_id}</code>
                  <small>{sourceElement?.text.replace(/\s+/g, " ").slice(0, 90) || "Source"} → {targetElement?.text.replace(/\s+/g, " ").slice(0, 90) || "Target"}</small>
                </div>
                <button onClick={() => removeCrossPageRelation(relation)}>Remove link</button>
              </div>;
            })}
            {crossPageRelationsOnPage.length === 0 && <p className="empty-copy">No saved or preview cross-page continuation links touch this page.</p>}
          </div>
        </div>}

        {editScope === "layout" && selectedElement && <div className={`selected-element-editor sandbox-selected-editor ${selectedEditorCollapsed ? "is-collapsed" : ""}`}>
          <div className="selected-editor-head">
            <div><span className="eyebrow">Selected corrected region</span><strong>{selectedElement.element_id}</strong></div>
            <CollapseToggle collapsed={selectedEditorCollapsed} onToggle={() => setSelectedEditorCollapsed((value) => !value)} label="selected region editor" />
          </div>
          {!selectedEditorCollapsed && <>
            <label className="type-editor"><span>Semantic type</span><select value={selectedElement.type} onChange={(event: ChangeEvent<HTMLSelectElement>) => relabelSelected(event.target.value as CanonicalElementType)}>
              {STRUCTURE_FILTERS.filter((type): type is CanonicalElementType => type !== "all").map((type) => <option key={type} value={type}>{labelType(type)}</option>)}
            </select></label>
            <BboxEditor element={selectedElement} width={basePage.width} height={basePage.height} onApply={(bbox) => commitBbox(selectedElement, bbox)} />
            <small>Drag or resize visually, or enter exact bbox coordinates. Text is recalculated from immutable Stage 3 spans when corrections are saved.</small>
          </>}
        </div>}

        {editScope === "layout" && comparison && <div className={`sandbox-diff ${comparison.matches ? "match" : "changed"}`}>
          <strong>{comparison.matches ? "After currently matches automatic Stage 4" : "Before and after differ"}</strong>
          <span>{comparison.unchanged} unchanged · {comparison.changed} changed · {comparison.added} added · {comparison.removed} removed</span>
        </div>}

        <div className={`sandbox-edit-grid ${elementsPanelCollapsed ? "elements-collapsed" : ""}`}>
          <section className="sandbox-preview-card">
            <div className="sandbox-card-head preview"><div><span className="eyebrow">Visual correction</span><strong>Original PDF + before/after overlays</strong></div></div>
            {drawMode && <div className="draw-instruction">Draw mode: drag on empty page space to create a <strong>{labelType(drawType)}</strong> region.</div>}
            <div className="sandbox-preview-shell"><div className="page-canvas">
              <img src={pagePreviewUrl(document.document_id, pageNumber)} alt={`Correction sandbox page ${pageNumber}`} />
              <div className={`overlay-layer correction-layer ${drawMode ? "draw-mode" : ""}`} onPointerDown={startDraw} onPointerMove={moveDraw} onPointerUp={endDraw}>
                {showBeforeOverlay && automaticPage.elements.map((element) => <SandboxOverlayBox key={`before-${element.element_id}`} item={{ id: element.element_id, type: element.type, bbox: element.bbox, text: element.text }} width={automaticPage.width} height={automaticPage.height} variant="baseline" />)}
                {showAfterOverlay && workingElements.map((element) => <EditableStructureOverlay key={`after-${element.element_id}`} element={element} width={basePage.width} height={basePage.height} selected={selectedIds.includes(element.element_id)} onSelect={(multi) => selectElement(element.element_id, multi)} onCommitBbox={(bbox) => commitBbox(element, bbox)} editable={editScope === "layout"} />)}
                {drawPreview && <div className="draw-preview" style={{ left: `${(drawPreview[0] / basePage.width) * 100}%`, top: `${(drawPreview[1] / basePage.height) * 100}%`, width: `${((drawPreview[2] - drawPreview[0]) / basePage.width) * 100}%`, height: `${((drawPreview[3] - drawPreview[1]) / basePage.height) * 100}%` }} />}
              </div>
            </div></div>
          </section>

          {!elementsPanelCollapsed && <section className="sandbox-elements-card">
            <div className="sandbox-card-head"><div><span className="eyebrow">After elements</span><strong>Corrected page regions</strong></div><span className="count-badge">{workingElements.length}</span></div>
            <div className="structure-filter-wrap"><select value={filter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setFilter(event.target.value as "all" | CanonicalElementType)}>
              {STRUCTURE_FILTERS.map((type) => <option key={type} value={type}>{labelType(type)}</option>)}
            </select></div>
            <div className="inspector-list sandbox-elements-list">
              {filteredWorking.map((element) => <StructureElementCard key={element.element_id} element={element} active={selectedIds.includes(element.element_id)} onClick={() => selectElement(element.element_id, selectedIds.length > 0)} />)}
              {filteredWorking.length === 0 && <p className="empty-copy">No matching corrected elements.</p>}
            </div>
          </section>}
        </div>
      </>}

      {mode === "before" && beforePayload && <div className="before-after-json-card">
        <div className="json-explainer"><strong>Before</strong><span>Immutable automatic Stage 4 page JSON. This is never modified by human review.</span></div>
        <PageJsonPanel payload={beforePayload} filename={`${document.document_id}-stage4-before-page-${pageNumber}.json`} />
      </div>}

      {mode === "after" && afterPayload && <div className="before-after-json-card">
        <div className="json-explainer"><strong>After</strong><span>Live Stage 4.5 preview: saved corrections plus the current unsaved session. After saving, backend text reconstruction may refine text fields from Stage 3 spans.</span></div>
        <PageJsonPanel payload={afterPayload} filename={`${document.document_id}-stage45-after-page-${pageNumber}.json`} />
      </div>}

      {mode === "log" && <div className="before-after-json-card">
        <CorrectionsPanel saved={savedOperations} session={sessionOps} pageNumber={pageNumber} documentId={document.document_id} />
        <div className="correction-log-json"><PageJsonPanel payload={correctionLogPayload} filename={`${document.document_id}-stage45-correction-log-page-${pageNumber}.json`} /></div>
      </div>}
    </div>
  );
}

function JsonViewer({
  extraction,
  structure,
  resolved,
  corrections,
  layout,
}: {
  extraction: DocumentExtraction | null;
  structure: StructuredDocument | null;
  resolved: ResolvedStructureArtifact | null;
  corrections: CorrectionArtifact | null;
  layout: LayoutArtifact | null;
}) {
  const defaultMode: JsonMode = resolved ? "resolved" : structure ? "structure" : extraction ? "extraction" : "layout";
  const [mode, setMode] = useState<JsonMode>(defaultMode);

  useEffect(() => {
    if (resolved) setMode("resolved");
    else if (structure) setMode("structure");
    else if (extraction) setMode("extraction");
    else setMode("layout");
  }, [resolved?.resolved_at, structure?.document_id, extraction?.document_id]);

  const payload = mode === "resolved"
    ? resolved
    : mode === "corrections"
      ? corrections
      : mode === "structure"
        ? structure
        : mode === "layout"
          ? layout
          : extraction;

  return (
    <div className="json-stack">
      <div className="json-tabs">
        <button disabled={!resolved} className={mode === "resolved" ? "active" : ""} onClick={() => setMode("resolved")}>Resolved Stage 4.5</button>
        <button disabled={!corrections} className={mode === "corrections" ? "active" : ""} onClick={() => setMode("corrections")}>Corrections</button>
        <button disabled={!structure} className={mode === "structure" ? "active" : ""} onClick={() => setMode("structure")}>Automatic Stage 4</button>
        <button disabled={!layout} className={mode === "layout" ? "active" : ""} onClick={() => setMode("layout")}>Layout engine</button>
        <button disabled={!extraction} className={mode === "extraction" ? "active" : ""} onClick={() => setMode("extraction")}>Stage 3</button>
      </div>
      <pre className="json-viewer">{payload ? JSON.stringify(payload, null, 2) : "No JSON artifact available yet."}</pre>
    </div>
  );
}

function Workspace({
  document,
  extraction,
  structure,
  resolved,
  corrections,
  layout,
  onRunExtraction,
  onRunStructure,
  onSaveCorrections,
  onResetAllCorrections,
  extracting,
  structuring,
  savingCorrections,
}: {
  document: DocumentRecord;
  extraction: DocumentExtraction | null;
  structure: StructuredDocument | null;
  resolved: ResolvedStructureArtifact | null;
  corrections: CorrectionArtifact | null;
  layout: LayoutArtifact | null;
  onRunExtraction: () => void;
  onRunStructure: () => void;
  onSaveCorrections: (operations: CorrectionOperation[]) => Promise<void>;
  onResetAllCorrections: () => Promise<void>;
  extracting: boolean;
  structuring: boolean;
  savingCorrections: boolean;
}) {
  const [tab, setTab] = useState<WorkspaceTab>("overview");
  const [pageNumber, setPageNumber] = useState(1);
  useEffect(() => { setTab("overview"); setPageNumber(1); }, [document.document_id]);

  const availablePageCount = structure?.pages.length ?? extraction?.pages.length ?? document.classification.page_count ?? 1;
  useEffect(() => {
    if (pageNumber > availablePageCount) setPageNumber(Math.max(1, availablePageCount));
  }, [availablePageCount, pageNumber]);

  const canExtract = document.validation_status === "valid" && document.classification.document_family === "pdf";
  const canStructure = document.extraction_status === "completed" && document.classification.document_family === "pdf";

  return (
    <div className="workspace">
      <header className="workspace-header">
        <div className="workspace-title">
          <span className="file-label">{document.extension.replace(".", "").toUpperCase()}</span>
          <div><h1>{document.original_filename}</h1><p>{document.document_id}</p></div>
        </div>
        <div className="header-actions">
          {document.classification.document_family === "pdf" && <a className="secondary-button" href={rawFileUrl(document.document_id)} target="_blank" rel="noreferrer">Open original ↗</a>}
          <button className="secondary-button" disabled={!canExtract || extracting || structuring} onClick={onRunExtraction}>
            {extracting ? "Extracting…" : extraction ? "Re-run Stage 3" : "Run Stage 3"}
          </button>
          <button className="primary-button compact" disabled={!canStructure || extracting || structuring} onClick={onRunStructure}>
            {structuring ? "Structuring…" : structure ? "Re-run Stage 4" : "Run Stage 4"}
          </button>
        </div>
      </header>

      {!canExtract && document.validation_status === "valid" && (
        <div className="notice-bar">The implemented Stage 3 and Stage 4 path currently targets PDF first. This {document.classification.document_family} file remains stored and validated.</div>
      )}
      {document.extraction_status === "completed" && !structure && (
        <div className="stage-ready-banner"><strong>Stage 4 ready.</strong><span>Run layout analysis to classify page regions and build the canonical document structure.</span></div>
      )}

      <StageRail document={document} />

      <nav className="tabs">
        <button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>Overview</button>
        <button className={tab === "extraction" ? "active" : ""} disabled={!extraction} onClick={() => setTab("extraction")}>Raw extraction</button>
        <button className={tab === "structure" ? "active" : ""} disabled={!structure} onClick={() => setTab("structure")}>Structured document</button>
        <button className={tab === "sandbox" ? "active" : ""} disabled={!extraction && !structure} onClick={() => setTab("sandbox")}>Correction Sandbox</button>
        <button className={tab === "json" ? "active" : ""} disabled={!extraction && !structure} onClick={() => setTab("json")}>JSON artifacts</button>
      </nav>

      <div className="workspace-body">
        {tab === "overview" && <Overview document={document} extraction={extraction} structure={structure} resolved={resolved} corrections={corrections} />}
        {tab === "extraction" && extraction && <ExtractionWorkspace document={document} extraction={extraction} pageNumber={pageNumber} setPageNumber={setPageNumber} />}
        {tab === "structure" && structure && <StructureWorkspace
          document={document}
          automaticStructure={structure}
          resolved={resolved}
          pageNumber={pageNumber}
          setPageNumber={setPageNumber}
          onOpenCorrectionSandbox={() => setTab("sandbox")}
        />}
        {tab === "sandbox" && <CorrectionSandbox
          document={document}
          extraction={extraction}
          structure={structure}
          resolved={resolved}
          corrections={corrections}
          pageNumber={pageNumber}
          setPageNumber={setPageNumber}
          onSaveCorrections={onSaveCorrections}
          onResetAllCorrections={onResetAllCorrections}
          savingCorrections={savingCorrections}
        />}
        {tab === "json" && <JsonViewer extraction={extraction} structure={structure} resolved={resolved} corrections={corrections} layout={layout} />}
      </div>
    </div>
  );
}

export default function App() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<DocumentRecord | null>(null);
  const [extraction, setExtraction] = useState<DocumentExtraction | null>(null);
  const [structure, setStructure] = useState<StructuredDocument | null>(null);
  const [resolved, setResolved] = useState<ResolvedStructureArtifact | null>(null);
  const [corrections, setCorrections] = useState<CorrectionArtifact | null>(null);
  const [layout, setLayout] = useState<LayoutArtifact | null>(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [structuring, setStructuring] = useState(false);
  const [savingCorrections, setSavingCorrections] = useState(false);
  const [error, setError] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem("rag-sidebar-collapsed") === "true";
  });

  useEffect(() => {
    window.localStorage.setItem("rag-sidebar-collapsed", String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  async function refreshDocuments(preferId?: string) {
    const rows = await listDocuments();
    setDocuments(rows);
    const id = preferId ?? selectedId ?? rows[0]?.document_id ?? null;
    if (id) setSelectedId(id);
  }

  useEffect(() => {
    refreshDocuments()
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load documents"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setExtraction(null);
      setStructure(null);
      setResolved(null);
      setCorrections(null);
      setLayout(null);
      return;
    }
    setError("");
    Promise.all([
      getDocument(selectedId),
      getExtraction(selectedId),
      getStructure(selectedId),
      getResolvedStructure(selectedId),
      getCorrections(selectedId),
      getLayout(selectedId),
    ])
      .then(([doc, raw, structured, resolvedArtifact, correctionArtifact, layoutArtifact]) => {
        setSelected(doc);
        setExtraction(raw);
        setStructure(structured);
        setResolved(resolvedArtifact);
        setCorrections(correctionArtifact);
        setLayout(layoutArtifact);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load document"));
  }, [selectedId]);

  function updateRecord(updated: DocumentRecord) {
    setSelected(updated);
    setDocuments((items) => items.map((item) => item.document_id === updated.document_id ? updated : item));
  }

  async function handleUploaded(record: DocumentRecord) {
    setDocuments((items) => [record, ...items]);
    setSelectedId(record.document_id);
  }

  async function handleRunExtraction() {
    if (!selected) return;
    setExtracting(true);
    setError("");
    try {
      const result = await runExtraction(selected.document_id);
      const updated = await getDocument(selected.document_id);
      setExtraction(result);
      setStructure(null);
      setResolved(null);
      setCorrections(null);
      setLayout(null);
      updateRecord(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Extraction failed");
      const updated = await getDocument(selected.document_id).catch(() => null);
      if (updated) updateRecord(updated);
    } finally {
      setExtracting(false);
    }
  }

  async function handleRunStructure() {
    if (!selected) return;
    setStructuring(true);
    setError("");
    try {
      const result = await runStructure(selected.document_id);
      const [updated, layoutArtifact] = await Promise.all([getDocument(selected.document_id), getLayout(selected.document_id)]);
      setStructure(result);
      setResolved(null);
      setCorrections(null);
      setLayout(layoutArtifact);
      updateRecord(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Structure reconstruction failed");
      setStructure(null);
      setResolved(null);
      setCorrections(null);
      setLayout(null);
      const updated = await getDocument(selected.document_id).catch(() => null);
      if (updated) updateRecord(updated);
    } finally {
      setStructuring(false);
    }
  }

  async function handleSaveCorrections(operations: CorrectionOperation[]) {
    if (!selected || !structure) return;
    setSavingCorrections(true);
    setError("");
    try {
      const response = await saveCorrections(selected.document_id, {
        base_structured_at: structure.structured_at,
        operations,
      });
      setCorrections(response.corrections);
      setResolved(response.resolved);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Saving corrections failed");
      throw e;
    } finally {
      setSavingCorrections(false);
    }
  }

  async function handleResetAllCorrections() {
    if (!selected) return;
    setSavingCorrections(true);
    setError("");
    try {
      await resetCorrections(selected.document_id);
      setCorrections(null);
      setResolved(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resetting corrections failed");
      throw e;
    } finally {
      setSavingCorrections(false);
    }
  }

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <DocumentSidebar
        documents={documents}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onUploaded={handleUploaded}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
      />
      <main className="main-area">
        {error && <div className="global-error"><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
        {loading ? (
          <div className="empty-state"><div className="spinner" />Loading workspace…</div>
        ) : selected ? (
          <Workspace
            document={selected}
            extraction={extraction}
            structure={structure}
            resolved={resolved}
            corrections={corrections}
            layout={layout}
            onRunExtraction={handleRunExtraction}
            onRunStructure={handleRunStructure}
            onSaveCorrections={handleSaveCorrections}
            onResetAllCorrections={handleResetAllCorrections}
            extracting={extracting}
            structuring={structuring}
            savingCorrections={savingCorrections}
          />
        ) : (
          <div className="welcome-state">
            <div className="welcome-mark">04</div>
            <h1>Document structure workspace</h1>
            <p>Stages 1–3 preserve and expose the raw document. Stage 4 adds layout-aware reading order and converts page regions into a traceable canonical structure before any chunking or embeddings happen.</p>
            <StageRail />
          </div>
        )}
      </main>
    </div>
  );
}
