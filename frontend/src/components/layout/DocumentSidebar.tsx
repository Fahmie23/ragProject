import { useState } from "react";
import type { ChangeEvent } from "react";
import { uploadDocument } from "../../api";
import type { DocumentRecord } from "../../types";

function documentStatus(doc: DocumentRecord) {
  if (doc.structure_status === "completed") return "Structured";
  if (doc.extraction_status === "completed") return "Extracted";
  if (doc.validation_status === "valid") return doc.classification.pdf_type ? `${doc.classification.pdf_type} PDF` : "Validated";
  return "Needs attention";
}

function UploadPdfButton({ onUploaded }: { onUploaded: (record: DocumentRecord) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleFile(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const record = await uploadDocument(file);
      onUploaded(record);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="v2-upload-wrap">
      <label className={`v2-upload-button ${busy ? "busy" : ""}`}>
        <input
          type="file"
          accept=".pdf,application/pdf"
          disabled={busy}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            const file = event.target.files?.[0] ?? null;
            void handleFile(file);
            event.target.value = "";
          }}
        />
        <span aria-hidden="true">＋</span>
        <strong>{busy ? "Uploading…" : "Upload PDF"}</strong>
      </label>
      {error && <small className="v2-upload-error">{error}</small>}
    </div>
  );
}


export function CompactDocumentBar({
  documents,
  selectedId,
  onSelect,
  onUploaded,
}: {
  documents: DocumentRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onUploaded: (record: DocumentRecord) => void;
}) {
  return (
    <div className="v2-compact-document-bar">
      <div className="v2-compact-brand" aria-label="Document Intelligence">R</div>
      <label className="v2-compact-document-select">
        <span>Document</span>
        <select value={selectedId ?? ""} onChange={(event) => event.target.value && onSelect(event.target.value)}>
          {documents.map((doc) => <option key={doc.document_id} value={doc.document_id}>{doc.original_filename}</option>)}
        </select>
      </label>
      <UploadPdfButton onUploaded={onUploaded} />
    </div>
  );
}

export function DocumentSidebar({
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
    <aside className={`sidebar v2-sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="v2-brand-row">
        <div className="v2-brand-mark">R</div>
        {!collapsed && (
          <div className="v2-brand-copy">
            <strong>Document Intelligence</strong>
            <span>Extraction & structure inspector</span>
          </div>
        )}
        <button
          className="sidebar-toggle v2-sidebar-toggle"
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? "Expand document sidebar" : "Collapse document sidebar"}
          title={collapsed ? "Expand document sidebar" : "Collapse document sidebar"}
        >
          {collapsed ? "›" : "‹"}
        </button>
      </div>

      {!collapsed ? <UploadPdfButton onUploaded={onUploaded} /> : (
        <button className="compact-upload-toggle" onClick={onToggleCollapsed} title="Expand sidebar to upload a PDF" aria-label="Upload PDF">＋</button>
      )}

      {!collapsed && (
        <div className="v2-sidebar-heading">
          <span>Documents</span>
          <span>{documents.length}</span>
        </div>
      )}

      <div className="document-list v2-document-list">
        {documents.map((doc) => (
          <button
            key={doc.document_id}
            type="button"
            className={`document-item v2-document-item ${collapsed ? "collapsed-item" : ""} ${selectedId === doc.document_id ? "selected" : ""}`}
            onClick={() => onSelect(doc.document_id)}
            title={collapsed ? doc.original_filename : undefined}
          >
            <span className="file-kind">PDF</span>
            {!collapsed && (
              <span className="document-copy">
                <strong>{doc.original_filename}</strong>
                <small>{doc.classification.page_count ? `${doc.classification.page_count} pages · ` : ""}{documentStatus(doc)}</small>
              </span>
            )}
            <span className={`tiny-dot ${doc.structure_status === "completed" ? "completed" : doc.extraction_status}`} />
          </button>
        ))}
        {!documents.length && !collapsed && <p className="sidebar-empty">Upload a PDF to begin.</p>}
      </div>

      {!collapsed && <div className="v2-sidebar-foot">V1 scope: digitally generated PDFs with extractable text layers.</div>}
    </aside>
  );
}
