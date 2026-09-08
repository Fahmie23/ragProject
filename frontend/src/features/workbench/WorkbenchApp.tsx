import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import {
  generateChunks,
  getChunks,
  getEmbeddingStatus,
  getCorrections,
  getDocument,
  getExtraction,
  getLayout,
  getResolvedStructure,
  getStructure,
  listDocuments,
  deleteDocument,
  pagePreviewUrl,
  rawFileUrl,
  resetChunks,
  resetCorrections,
  runExtraction,
  runStructure,
  saveCorrections,
  validateCorrections,
} from "../../api";
import type {
  CanonicalElement,
  CanonicalElementType,
  ChunkingArtifact,
  ChunkingConfig,
  CorrectionArtifact,
  CorrectionElementSpec,
  CorrectionOperation,
  DocumentExtraction,
  DocumentRecord,
  ImageBlock,
  LayoutArtifact,
  PageExtraction,
  RelationshipIntegrityReport,
  ResolvedStructureArtifact,
  SectionRecord,
  StructuralRelation,
  StructuredDocument,
  TableExtraction,
  TextBlock,
  EmbeddingStatus,
} from "../../types";
import { CompactDocumentBar, DocumentSidebar as V2DocumentSidebar } from "../../components/layout/DocumentSidebar";
import { DocumentWorkflowNav } from "../../components/layout/DocumentWorkflowNav";
import { DocumentTree } from "../../components/structure/DocumentTree";
import { OverviewPage } from "../../pages/OverviewPage";
import { ChunkingPage } from "../../pages/ChunkingPage";
import { IndexPage } from "../../pages/IndexPage";
import type { WorkspaceTab } from "../../app/workspace";
import { useViewportMode } from "../../hooks/useViewportMode";

type LayoutViewMode = "reconstructed" | "original" | "compare";
type LayoutSourceMode = "resolved" | "stage4" | "stage3" | "pasted";
type LayoutInspectorMode = "details" | "json" | "issues";

type LayoutRenderItem = {
  id: string;
  type: string;
  bbox: number[];
  text: string;
  readingOrder?: number | null;
  table?: { row_count: number; col_count: number; cells: (string | null)[][] } | null;
  raw: unknown;
};

type LayoutRenderPage = {
  pageNumber: number;
  width: number;
  height: number;
  items: LayoutRenderItem[];
  raw: unknown;
  sourceLabel: string;
};
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
  "group_header",
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

const SAFE_SPLIT_TYPES = new Set<CanonicalElementType>(["paragraph", "definition_text", "list_item", "caption", "footnote", "formula", "page_header", "page_footer"]);
const SAFE_MERGE_TYPES = new Set<CanonicalElementType>(["paragraph", "definition_text", "list_item", "caption", "footnote", "formula"]);
const STRUCTURAL_PROMOTION_TYPES = new Set<CanonicalElementType>(["title", "subtitle", "document_metadata", "section_header", "clause", "subclause", "table", "figure"]);
const SAFE_DRAW_TYPES = new Set<CanonicalElementType>(["definition_term", "definition_text", "paragraph", "list_item", "caption", "page_header", "page_footer", "footnote", "formula", "unknown"]);
const SAFE_SPAN_REBUILD_TYPES = new Set<CanonicalElementType>(SAFE_DRAW_TYPES);

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
      <span className="collapse-toggle-label">{collapsed ? "Expand" : "Collapse"}</span>
    </button>
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

function tableCellLines(value: string | null) {
  return (value ?? "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

type InspectableTable = Pick<TableExtraction, "row_count" | "col_count" | "cells">;

function possibleMergedTocRows(table: InspectableTable) {
  const marker = /^\d+[A-Za-z]?(?:\.\d+)*\.?$/;
  const pageReference = /^\d{1,4}$/;
  const headingLike = (value: string) => {
    const letters = [...value].filter((char) => /[A-Za-z]/.test(char));
    if (letters.length < 4) return false;
    return letters.filter((char) => char === char.toUpperCase()).length / letters.length >= 0.8;
  };

  return table.cells.flatMap((row, rowIndex) => {
    if (row.length !== 3) return [];
    const left = tableCellLines(row[0]);
    const middle = tableCellLines(row[1]);
    const right = tableCellLines(row[2]);
    const suspicious = left.length >= 2
      && middle.length >= 2
      && right.length === 1
      && pageReference.test(right[0])
      && marker.test(left[left.length - 1])
      && !marker.test(left[0])
      && headingLike(middle[0]);
    return suspicious ? [rowIndex] : [];
  });
}

function TableStructureInspector({
  table,
  elementId,
}: {
  table: InspectableTable;
  elementId: string;
}) {
  const suspiciousRows = possibleMergedTocRows(table);
  return (
    <div className="table-structure-inspector">
      <div className="table-structure-head">
        <div><span className="eyebrow">Selected table</span><strong>{elementId}</strong></div>
        <span>{table.row_count} × {table.col_count}</span>
      </div>
      {suspiciousRows.length > 0 ? (
        <div className="table-quality-warning">
          Possible merged visual row{ suspiciousRows.length === 1 ? "" : "s" }: {suspiciousRows.map((row) => row + 1).join(", ")}. Compare these rows with the PDF.
        </div>
      ) : (
        <div className="table-quality-ok">No obvious heading + entry row merge signal in this table.</div>
      )}
      <div className="table-detail-scroll">
        <table className="table-detail">
          <tbody>
            {table.cells.map((row, rowIndex) => (
              <tr key={rowIndex} className={suspiciousRows.includes(rowIndex) ? "suspicious" : ""}>
                <th scope="row">{rowIndex + 1}</th>
                {row.map((cell, colIndex) => <td key={colIndex}>{cell ?? ""}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RawOverlayBox({
  item,
  page,
  selected,
  onClick,
  showLabel = false,
}: {
  item: RawInspectorItem;
  page: PageExtraction;
  selected: boolean;
  onClick: () => void;
  showLabel?: boolean;
}) {
  const [x0, y0, x1, y1] = item.bbox;
  const style = {
    left: `${(x0 / page.width) * 100}%`,
    top: `${(y0 / page.height) * 100}%`,
    width: `${((x1 - x0) / page.width) * 100}%`,
    height: `${((y1 - y0) / page.height) * 100}%`,
  };
  return <button className={`overlay-box ${item.type} ${selected ? "selected" : ""}`} style={style} onClick={onClick} aria-label={item.id}>
    {showLabel && <span className="overlay-debug-label">{item.id} · {item.type}</span>}
  </button>;
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
  const [showLabels, setShowLabels] = useState(false);
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
  const selectedItem = selectedId ? items.find((item) => item.id === selectedId) ?? null : null;
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
            <OverlayLabelToggle checked={showLabels} onChange={setShowLabels} disabled={!showOverlays} />
            <button className="panel-collapse-button" onClick={() => setInspectorCollapsed((value) => !value)}>{inspectorCollapsed ? "Show inspector" : "Hide inspector"}</button>
          </div>
        </div>
        {page.warnings.length > 0 && <div className="page-warning">{page.warnings.join(" ")}</div>}
        <div className="page-canvas-shell"><div className="page-canvas">
          <img src={pagePreviewUrl(document.document_id, pageNumber)} alt={`Page ${pageNumber}`} />
          {showOverlays && <div className="overlay-layer">{items.map((item) => (
            <RawOverlayBox key={item.id} item={item} page={page} selected={selectedId === item.id} onClick={() => setSelectedId(item.id)} showLabel={showLabels} />
          ))}</div>}
        </div></div>
      </div>

      {!inspectorCollapsed && <div className="inspector-panel">
        <div className="inspector-header"><div><span className="eyebrow">Stage 3 · Page {pageNumber}</span><h3>Raw page inspection</h3></div><span className="count-badge">{items.length}</span></div>
        <InspectorModeTabs mode={inspectorMode} onChange={setInspectorMode} />
        {inspectorMode === "elements" ? (
          <>
            {selectedItem?.type === "table" && <TableStructureInspector table={selectedItem.table} elementId={selectedItem.id} />}
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


function canonicalRenderPage(page: StructuredDocument["pages"][number]): LayoutRenderPage {
  return {
    pageNumber: page.page_number,
    width: page.width,
    height: page.height,
    sourceLabel: "Stage 4 canonical JSON",
    raw: page,
    items: page.elements.map((element) => ({
      id: element.element_id,
      type: element.type,
      bbox: element.bbox,
      text: element.text,
      readingOrder: element.reading_order,
      table: element.table ?? null,
      raw: element,
    })),
  };
}

function extractionRenderPage(page: PageExtraction): LayoutRenderPage {
  const blockItems: LayoutRenderItem[] = page.blocks.map((block) => ({
    id: block.block_id,
    type: block.type,
    bbox: block.bbox,
    text: block.type === "text" ? block.text : "Image block",
    readingOrder: block.number,
    table: null,
    raw: block,
  }));
  const tableItems: LayoutRenderItem[] = page.tables.map((table) => ({
    id: table.table_id,
    type: "table",
    bbox: table.bbox,
    text: table.cells.map((row) => row.filter(Boolean).join(" | ")).join("\n"),
    readingOrder: null,
    table,
    raw: table,
  }));
  return {
    pageNumber: page.page_number,
    width: page.width,
    height: page.height,
    sourceLabel: "Stage 3 extraction JSON",
    raw: page,
    items: [...blockItems, ...tableItems],
  };
}

function finitePageNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function parsedTable(value: unknown): LayoutRenderItem["table"] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const rowCount = (value as { row_count?: unknown }).row_count;
  const colCount = (value as { col_count?: unknown }).col_count;
  const cells = (value as { cells?: unknown }).cells;
  if (typeof rowCount !== "number" || typeof colCount !== "number" || !Array.isArray(cells)) return null;
  const normalized = cells.map((row) => Array.isArray(row) ? row.map((cell) => cell == null ? null : String(cell)) : []);
  return { row_count: rowCount, col_count: colCount, cells: normalized };
}

function parsePastedLayoutJson(text: string, preferredPage: number): { page: LayoutRenderPage | null; error: string } {
  if (!text.trim()) return { page: null, error: "Paste a Stage 3 or Stage 4 page JSON artifact first." };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    return { page: null, error: error instanceof Error ? `Invalid JSON: ${error.message}` : "Invalid JSON." };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return { page: null, error: "The JSON root must be an object." };
  const root = parsed as Record<string, unknown>;
  let candidate: unknown = root.page ?? root;
  if (Array.isArray(root.pages)) {
    const preferred = root.pages.find((entry) => entry && typeof entry === "object" && !Array.isArray(entry) && (entry as Record<string, unknown>).page_number === preferredPage);
    candidate = preferred ?? root.pages[0];
  }
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return { page: null, error: "No page object was found in the JSON." };
  const page = candidate as Record<string, unknown>;
  const width = typeof page.width === "number" && Number.isFinite(page.width) && page.width > 0 ? page.width : null;
  const height = typeof page.height === "number" && Number.isFinite(page.height) && page.height > 0 ? page.height : null;
  if (!width || !height) return { page: null, error: "The page needs numeric width and height values." };
  const pageNumber = finitePageNumber(page.page_number) ?? preferredPage;

  if (Array.isArray(page.elements)) {
    const items: LayoutRenderItem[] = [];
    for (const [index, raw] of page.elements.entries()) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
      const item = raw as Record<string, unknown>;
      const bbox = Array.isArray(item.bbox) && item.bbox.length === 4 && item.bbox.every((n) => typeof n === "number" && Number.isFinite(n)) ? item.bbox as number[] : null;
      if (!bbox) continue;
      items.push({
        id: typeof item.element_id === "string" ? item.element_id : `element-${index + 1}`,
        type: typeof item.type === "string" ? item.type : "unknown",
        bbox,
        text: typeof item.text === "string" ? item.text : "",
        readingOrder: typeof item.reading_order === "number" ? item.reading_order : null,
        table: parsedTable(item.table),
        raw,
      });
    }
    return { page: { pageNumber, width, height, items, raw: page, sourceLabel: "Pasted canonical JSON" }, error: "" };
  }

  if (Array.isArray(page.blocks) || Array.isArray(page.tables)) {
    const items: LayoutRenderItem[] = [];
    const blocks = Array.isArray(page.blocks) ? page.blocks : [];
    const tables = Array.isArray(page.tables) ? page.tables : [];
    blocks.forEach((raw, index) => {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;
      const block = raw as Record<string, unknown>;
      const bbox = Array.isArray(block.bbox) && block.bbox.length === 4 && block.bbox.every((n) => typeof n === "number" && Number.isFinite(n)) ? block.bbox as number[] : null;
      if (!bbox) return;
      items.push({
        id: typeof block.block_id === "string" ? block.block_id : `block-${index + 1}`,
        type: typeof block.type === "string" ? block.type : "text",
        bbox,
        text: typeof block.text === "string" ? block.text : (block.type === "image" ? "Image block" : ""),
        readingOrder: typeof block.number === "number" ? block.number : null,
        table: null,
        raw,
      });
    });
    tables.forEach((raw, index) => {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;
      const table = raw as Record<string, unknown>;
      const bbox = Array.isArray(table.bbox) && table.bbox.length === 4 && table.bbox.every((n) => typeof n === "number" && Number.isFinite(n)) ? table.bbox as number[] : null;
      if (!bbox) return;
      const parsed = parsedTable(table);
      items.push({
        id: typeof table.table_id === "string" ? table.table_id : `table-${index + 1}`,
        type: "table",
        bbox,
        text: parsed?.cells.map((row) => row.filter(Boolean).join(" | ")).join("\n") ?? "",
        readingOrder: null,
        table: parsed,
        raw,
      });
    });
    return { page: { pageNumber, width, height, items, raw: page, sourceLabel: "Pasted Stage 3 JSON" }, error: "" };
  }

  return { page: null, error: "Unsupported page JSON. Expected page.elements or page.blocks/page.tables." };
}

function layoutPageIssues(page: LayoutRenderPage): string[] {
  const issues: string[] = [];
  const orders = new Map<number, number>();
  page.items.forEach((item) => {
    const [x1, y1, x2, y2] = item.bbox;
    if (x2 <= x1 || y2 <= y1) issues.push(`${item.id}: bbox has zero or negative size.`);
    if (x1 < 0 || y1 < 0 || x2 > page.width || y2 > page.height) issues.push(`${item.id}: bbox extends outside the page bounds.`);
    if (typeof item.readingOrder === "number") orders.set(item.readingOrder, (orders.get(item.readingOrder) ?? 0) + 1);
    if (item.table) {
      if (item.table.row_count !== item.table.cells.length) issues.push(`${item.id}: table row_count does not match cells.length.`);
      const widest = item.table.cells.reduce((max, row) => Math.max(max, row.length), 0);
      if (widest > item.table.col_count) issues.push(`${item.id}: one or more rows exceed col_count.`);
    }
  });
  orders.forEach((count, order) => { if (count > 1) issues.push(`Reading order ${order} is assigned to ${count} elements.`); });
  return issues;
}

function ReconstructedElement({
  item,
  page,
  selected,
  showBoxes,
  showLabels,
  showReadingOrder,
  onSelect,
}: {
  item: LayoutRenderItem;
  page: LayoutRenderPage;
  selected: boolean;
  showBoxes: boolean;
  showLabels: boolean;
  showReadingOrder: boolean;
  onSelect: () => void;
}) {
  const [x1, y1, x2, y2] = item.bbox;
  const style = {
    left: `${(x1 / page.width) * 100}%`,
    top: `${(y1 / page.height) * 100}%`,
    width: `${((x2 - x1) / page.width) * 100}%`,
    height: `${((y2 - y1) / page.height) * 100}%`,
  };
  const isImage = item.type === "image" || item.type === "figure";
  return (
    <button
      className={`reconstructed-element type-${item.type} ${selected ? "selected" : ""} ${showBoxes ? "show-box" : "hide-box"}`}
      style={style}
      onClick={onSelect}
      title={`${item.id} · ${labelType(item.type)}`}
      type="button"
    >
      {showLabels && <span className="reconstructed-label">{item.id} · {labelType(item.type)}</span>}
      {showReadingOrder && typeof item.readingOrder === "number" && <span className="reading-order-dot">{item.readingOrder + 1}</span>}
      {item.table ? (
        <span className="reconstructed-table" style={{ gridTemplateColumns: `repeat(${Math.max(1, item.table.col_count)}, minmax(0, 1fr))` }}>
          {item.table.cells.flatMap((row, rowIndex) => row.map((cell, colIndex) => (
            <span className="reconstructed-cell" key={`${rowIndex}-${colIndex}`}>{cell ?? ""}</span>
          )))}
        </span>
      ) : isImage ? (
        <span className="reconstructed-image-placeholder">{labelType(item.type)}</span>
      ) : (
        <span className="reconstructed-text">{item.text}</span>
      )}
    </button>
  );
}

function ReconstructedPage({
  page,
  selectedId,
  setSelectedId,
  showBoxes,
  showLabels,
  showReadingOrder,
  filter,
}: {
  page: LayoutRenderPage;
  selectedId: string | null;
  setSelectedId: (id: string) => void;
  showBoxes: boolean;
  showLabels: boolean;
  showReadingOrder: boolean;
  filter: string;
}) {
  const items = filter === "all" ? page.items : page.items.filter((item) => item.type === filter);
  return (
    <div className="reconstructed-page" style={{ aspectRatio: `${page.width} / ${page.height}` }}>
      {items.map((item) => <ReconstructedElement
        key={item.id}
        item={item}
        page={page}
        selected={selectedId === item.id}
        showBoxes={showBoxes}
        showLabels={showLabels}
        showReadingOrder={showReadingOrder}
        onSelect={() => setSelectedId(item.id)}
      />)}
    </div>
  );
}

function LayoutWorkspace({
  document,
  extraction,
  structure,
  resolved,
  pageNumber,
  setPageNumber,
}: {
  document: DocumentRecord;
  extraction: DocumentExtraction | null;
  structure: StructuredDocument | null;
  resolved: ResolvedStructureArtifact | null;
  pageNumber: number;
  setPageNumber: (value: number) => void;
}) {
  const defaultSource: LayoutSourceMode = resolved ? "resolved" : structure ? "stage4" : extraction ? "stage3" : "pasted";
  const [sourceMode, setSourceMode] = useState<LayoutSourceMode>(defaultSource);
  const [viewMode, setViewMode] = useState<LayoutViewMode>("reconstructed");
  const [inspectorMode, setInspectorMode] = useState<LayoutInspectorMode>("details");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [showLabels, setShowLabels] = useState(false);
  const [showReadingOrder, setShowReadingOrder] = useState(false);
  const [filter, setFilter] = useState("all");
  const [pastedText, setPastedText] = useState("");
  const [pastedPage, setPastedPage] = useState<LayoutRenderPage | null>(null);
  const [pasteError, setPasteError] = useState("");
  const [pasteOpen, setPasteOpen] = useState(false);

  useEffect(() => {
    setSourceMode(resolved ? "resolved" : structure ? "stage4" : extraction ? "stage3" : "pasted");
    setSelectedId(null);
    setPastedPage(null);
    setPastedText("");
    setPasteError("");
    setPasteOpen(false);
  }, [document.document_id]);

  const resolvedPage = resolved?.structure.pages.find((page) => page.page_number === pageNumber) ?? null;
  const stage4Page = structure?.pages.find((page) => page.page_number === pageNumber) ?? null;
  const stage3Page = extraction?.pages.find((page) => page.page_number === pageNumber) ?? null;
  const renderedPage = sourceMode === "resolved"
    ? (resolvedPage ? { ...canonicalRenderPage(resolvedPage), sourceLabel: "Resolved Stage 4.5 JSON" } : null)
    : sourceMode === "stage4"
      ? (stage4Page ? canonicalRenderPage(stage4Page) : null)
      : sourceMode === "stage3"
        ? (stage3Page ? extractionRenderPage(stage3Page) : null)
        : pastedPage;

  const totalPages = sourceMode === "resolved"
    ? resolved?.structure.pages.length ?? structure?.pages.length ?? extraction?.pages.length ?? 1
    : sourceMode === "stage4"
      ? structure?.pages.length ?? extraction?.pages.length ?? 1
      : sourceMode === "stage3"
        ? extraction?.pages.length ?? structure?.pages.length ?? 1
        : Math.max(document.classification.page_count ?? 1, pastedPage?.pageNumber ?? 1);

  useEffect(() => {
    setSelectedId(null);
    setFilter("all");
  }, [pageNumber, sourceMode]);

  useEffect(() => {
    if (sourceMode === "resolved" && !resolved) setSourceMode(structure ? "stage4" : extraction ? "stage3" : "pasted");
    if (sourceMode === "stage4" && !structure) setSourceMode(resolved ? "resolved" : extraction ? "stage3" : "pasted");
    if (sourceMode === "stage3" && !extraction) setSourceMode(resolved ? "resolved" : structure ? "stage4" : "pasted");
  }, [sourceMode, resolved, structure, extraction]);

  const selectedItem = renderedPage?.items.find((item) => item.id === selectedId) ?? null;
  const itemTypes = renderedPage ? Array.from(new Set(renderedPage.items.map((item) => item.type))).sort() : [];
  const issues = renderedPage ? layoutPageIssues(renderedPage) : [];

  function renderPasted() {
    const result = parsePastedLayoutJson(pastedText, pageNumber);
    setPasteError(result.error);
    setPastedPage(result.page);
    if (result.page) {
      setPageNumber(result.page.pageNumber);
      setSelectedId(result.page.items[0]?.id ?? null);
      setPasteOpen(false);
    }
  }

  function sourcePageJson() {
    if (sourceMode === "resolved" && resolvedPage && resolved) {
      return {
        stage: "stage_4_5_resolved_structure",
        schema_version: resolved.schema_version,
        document_id: resolved.document_id,
        correction_count: resolved.correction_count,
        page: resolvedPage,
      };
    }
    if (sourceMode === "stage4" && stage4Page && structure) {
      return {
        stage: "stage_4_canonical_structure",
        schema_version: structure.schema_version,
        document_id: structure.document_id,
        source_filename: structure.source_filename,
        page: stage4Page,
      };
    }
    if (sourceMode === "stage3" && stage3Page && extraction) {
      return {
        stage: "stage_3_raw_extraction",
        schema_version: extraction.schema_version,
        document_id: extraction.document_id,
        source_filename: extraction.source_filename,
        page: stage3Page,
      };
    }
    return pastedPage?.raw ?? null;
  }

  return (
    <div className="layout-workbench">
      <div className="layout-toolbar-card">
        <div className="layout-toolbar-row">
          {sourceMode === "pasted" ? (
            <div className="pasted-page-indicator">Pasted page {pastedPage?.pageNumber ?? "—"}</div>
          ) : (
            <PageNav pageNumber={pageNumber} total={Math.max(1, totalPages)} setPageNumber={setPageNumber} />
          )}
          <div className="layout-source-switch" aria-label="Layout JSON source">
            <button type="button" disabled={!resolved} className={sourceMode === "resolved" ? "active" : ""} onClick={() => setSourceMode("resolved")}>Resolved 4.5</button>
            <button type="button" disabled={!structure} className={sourceMode === "stage4" ? "active" : ""} onClick={() => setSourceMode("stage4")}>Stage 4 JSON</button>
            <button type="button" disabled={!extraction} className={sourceMode === "stage3" ? "active" : ""} onClick={() => setSourceMode("stage3")}>Stage 3 JSON</button>
            <button type="button" className={sourceMode === "pasted" ? "active" : ""} onClick={() => { setSourceMode("pasted"); setPasteOpen(true); }}>Paste JSON</button>
          </div>
        </div>
        <div className="layout-toolbar-row secondary">
          <div className="layout-view-switch">
            {(["reconstructed", "original", "compare"] as LayoutViewMode[]).map((mode) => (
              <button type="button" key={mode} className={viewMode === mode ? "active" : ""} onClick={() => setViewMode(mode)}>{mode === "reconstructed" ? "Reconstructed" : mode === "original" ? "Original PDF" : "Compare"}</button>
            ))}
          </div>
          <div className="layout-controls">
            <label><input type="checkbox" checked={showBoxes} onChange={(event: ChangeEvent<HTMLInputElement>) => setShowBoxes(event.target.checked)} /> Boxes</label>
            <label><input type="checkbox" checked={showLabels} onChange={(event: ChangeEvent<HTMLInputElement>) => setShowLabels(event.target.checked)} /> Labels</label>
            <label><input type="checkbox" checked={showReadingOrder} onChange={(event: ChangeEvent<HTMLInputElement>) => setShowReadingOrder(event.target.checked)} /> Reading order</label>
            <select value={filter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setFilter(event.target.value)} aria-label="Element type filter">
              <option value="all">All element types</option>
              {itemTypes.map((type) => <option value={type} key={type}>{labelType(type)}</option>)}
            </select>
          </div>
        </div>
        {pasteOpen && <div className="paste-json-panel">
          <div className="paste-json-head"><div><strong>Paste page or document JSON</strong><small>Supports Stage 3 blocks/tables and Stage 4 page.elements.</small></div><button type="button" className="secondary-button compact" onClick={() => setPasteOpen(false)}>Close</button></div>
          <textarea value={pastedText} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setPastedText(event.target.value)} placeholder={'{\n  "page": {\n    "page_number": 3,\n    "width": 597,\n    "height": 843,\n    "elements": [...]\n  }\n}'} />
          <div className="paste-json-actions"><button type="button" className="primary-button compact" onClick={renderPasted}>Render JSON</button>{pasteError && <span className="inline-error">{pasteError}</span>}</div>
        </div>}
      </div>

      <div className="layout-main-grid">
        <section className="layout-preview-panel">
          <div className="layout-preview-head">
            <div><span className="eyebrow">JSON → visual reconstruction</span><h3>{renderedPage ? `Page ${renderedPage.pageNumber}` : "No layout source"}</h3></div>
            {renderedPage && <span className="layout-source-badge">{renderedPage.sourceLabel}</span>}
          </div>
          {!renderedPage ? (
            <div className="layout-empty"><strong>No page JSON available.</strong><span>Select an available pipeline artifact or paste page-level JSON.</span>{sourceMode === "pasted" && <button type="button" className="primary-button compact" onClick={() => setPasteOpen(true)}>Paste JSON</button>}</div>
          ) : viewMode === "reconstructed" ? (
            <div className="layout-canvas-shell"><ReconstructedPage page={renderedPage} selectedId={selectedId} setSelectedId={setSelectedId} showBoxes={showBoxes} showLabels={showLabels} showReadingOrder={showReadingOrder} filter={filter} /></div>
          ) : viewMode === "original" ? (
            <div className="layout-canvas-shell"><div className="original-page-frame" style={{ aspectRatio: `${renderedPage.width} / ${renderedPage.height}` }}><img src={pagePreviewUrl(document.document_id, renderedPage.pageNumber)} alt={`Original PDF page ${renderedPage.pageNumber}`} /></div></div>
          ) : (
            <div className="layout-compare-grid">
              <div className="layout-compare-pane"><div className="compare-label">Original PDF</div><div className="original-page-frame" style={{ aspectRatio: `${renderedPage.width} / ${renderedPage.height}` }}><img src={pagePreviewUrl(document.document_id, renderedPage.pageNumber)} alt={`Original PDF page ${renderedPage.pageNumber}`} /></div></div>
              <div className="layout-compare-pane"><div className="compare-label">Reconstructed from JSON</div><ReconstructedPage page={renderedPage} selectedId={selectedId} setSelectedId={setSelectedId} showBoxes={showBoxes} showLabels={showLabels} showReadingOrder={showReadingOrder} filter={filter} /></div>
            </div>
          )}
          {renderedPage && renderedPage.items.some((item) => item.table) && <div className="layout-method-note">Table regions use the table bbox from JSON. Internal cells are distributed evenly because the current schema stores table cells but not individual cell bounding boxes.</div>}
        </section>

        <aside className="layout-inspector-panel">
          <div className="inspector-header"><div><span className="eyebrow">Layout inspector</span><h3>{selectedItem ? selectedItem.id : "Select an element"}</h3></div>{renderedPage && <span className="count-badge">{renderedPage.items.length}</span>}</div>
          <div className="layout-inspector-tabs">
            {(["details", "json", "issues"] as LayoutInspectorMode[]).map((mode) => <button type="button" key={mode} className={inspectorMode === mode ? "active" : ""} onClick={() => setInspectorMode(mode)}>{mode}</button>)}
          </div>
          {inspectorMode === "details" ? (
            <div className="layout-inspector-body">
              {selectedItem ? <>
                <div className="detail-grid"><span>Type</span><strong>{labelType(selectedItem.type)}</strong><span>BBox</span><code>[{selectedItem.bbox.map((value) => Number(value.toFixed(3))).join(", ")}]</code><span>Reading order</span><strong>{typeof selectedItem.readingOrder === "number" ? selectedItem.readingOrder : "—"}</strong></div>
                {selectedItem.text && <div className="selected-text"><span>Extracted text</span><p>{selectedItem.text}</p></div>}
                {selectedItem.table && <TableStructureInspector table={selectedItem.table} elementId={selectedItem.id} />}
              </> : <p className="empty-copy">Click an extracted region in the reconstructed page to inspect its JSON.</p>}
            </div>
          ) : inspectorMode === "json" ? (
            <div className="layout-inspector-json"><pre>{JSON.stringify(selectedItem?.raw ?? sourcePageJson(), null, 2)}</pre></div>
          ) : (
            <div className="layout-inspector-body">
              {issues.length === 0 ? <div className="layout-check-good"><strong>Basic structural checks passed</strong><span>No invalid/out-of-page boxes, duplicate reading-order values, or obvious table shape mismatches were found on this page.</span></div> : issues.map((issue) => <div className="layout-check-warning" key={issue}>{issue}</div>)}
              <div className="layout-check-info"><strong>Visual QA is still required</strong><span>These checks can validate JSON consistency, but only comparison with the original PDF can confirm that the extraction is semantically and visually correct.</span></div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function PageNav({ pageNumber, total, setPageNumber, className = "" }: { pageNumber: number; total: number; setPageNumber: (value: number) => void; className?: string }) {
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
    // Blur fires after typing a page number when the reviewer clicks back into
    // the correction workspace. Committing the already-current page must be a
    // no-op; otherwise CorrectionSandbox.safeSetPage() would clear selection.
    if (next === pageNumber) return;
    setPageNumber(next);
  }

  return (
    <div className={`page-nav ${className}`.trim()}>
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

function OverlayLabelToggle({ checked, onChange, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return <label className={`toggle ${disabled ? "disabled" : ""}`}><input type="checkbox" checked={checked} disabled={disabled} onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.checked)} /><span /> Labels</label>;
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
  showLabel = false,
}: {
  element: CanonicalElement;
  width: number;
  height: number;
  selected: boolean;
  onClick: () => void;
  showLabel?: boolean;
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
    >
      {showLabel && <span className="overlay-debug-label">{element.reading_order + 1} · {labelType(element.type)}</span>}
    </button>
  );
}

function structureElementDisplayContext(elementId: string) {
  const rowMatch = elementId.match(/-r(\d+)-(?:term|definition)$/i);
  if (rowMatch) return `Row ${rowMatch[1]}`;

  const elementMatch = elementId.match(/-e(\d+)/i);
  if (elementMatch) return `Element ${elementMatch[1]}`;

  return "Element";
}

function compactElementPreview(text: string) {
  return text.replace(/\s+/g, " ").trim();
}

function StructureElementCard({
  element,
  active,
  onClick,
}: {
  element: CanonicalElement;
  active: boolean;
  onClick: (event: ReactMouseEvent<HTMLButtonElement>) => void;
}) {
  const preview = element.text ? compactElementPreview(element.text) : "";
  const context = structureElementDisplayContext(element.element_id);
  const accessibleDescription = [labelType(element.type), context, element.element_id, preview].filter(Boolean).join(" · ");

  return (
    <button
      className={`structure-card structure-card-compact ${active ? "active" : ""}`}
      onClick={onClick}
      title={accessibleDescription}
      aria-label={accessibleDescription}
    >
      <div className="structure-card-head">
        <span className={`semantic-chip semantic-${element.type}`}>{labelType(element.type)}</span>
        <span className="structure-card-context">{context}</span>
      </div>
      {preview && <p className="structure-card-preview">{preview}</p>}
      {!preview && element.table && <p className="structure-card-preview structure-card-placeholder">Table structure available</p>}
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


type Stage3SpanItem = {
  spanId: string;
  lineId: string;
  blockId: string;
  text: string;
  bbox: number[];
  font?: string | null;
  size?: number | null;
  order: number;
};

function stage3SpanItems(page: PageExtraction | null | undefined): Stage3SpanItem[] {
  if (!page) return [];
  const items: Stage3SpanItem[] = [];
  let order = 0;
  page.blocks.forEach((block) => {
    if (block.type !== "text") return;
    block.lines.forEach((line, lineIndex) => {
      const lineId = line.line_id || `${block.block_id}-l${lineIndex + 1}`;
      line.spans.forEach((span, spanIndex) => {
        const spanId = span.span_id || `${lineId}-s${spanIndex + 1}`;
        items.push({
          spanId,
          lineId,
          blockId: block.block_id,
          text: span.text,
          bbox: span.bbox,
          font: span.font,
          size: span.size,
          order: order++,
        });
      });
    });
  });
  return items;
}

function spanSelectionPayload(items: Stage3SpanItem[], selectedIds: string[]) {
  const selectedSet = new Set(selectedIds);
  const selected = items.filter((item) => selectedSet.has(item.spanId)).sort((a, b) => a.order - b.order);
  if (!selected.length) return null;
  const bbox = [
    Math.min(...selected.map((item) => item.bbox[0])),
    Math.min(...selected.map((item) => item.bbox[1])),
    Math.max(...selected.map((item) => item.bbox[2])),
    Math.max(...selected.map((item) => item.bbox[3])),
  ].map((value) => Math.round(value * 1000) / 1000);
  const lines: string[] = [];
  let currentLine = "";
  let currentLineId: string | null = null;
  for (const item of selected) {
    if (currentLineId !== null && item.lineId !== currentLineId) {
      if (currentLine.trim()) lines.push(currentLine.trim());
      currentLine = "";
    }
    currentLineId = item.lineId;
    currentLine += item.text;
  }
  if (currentLine.trim()) lines.push(currentLine.trim());
  return {
    selected,
    bbox,
    text: lines.join("\n").trim(),
    blockIds: [...new Set(selected.map((item) => item.blockId))],
    lineIds: [...new Set(selected.map((item) => item.lineId))],
    spanIds: selected.map((item) => item.spanId),
  };
}

function spanOverlapsElement(spanPayload: ReturnType<typeof spanSelectionPayload>, element: CanonicalElement) {
  if (!spanPayload) return false;
  const exact = new Set(element.source.stage3_span_ids ?? []);
  if (spanPayload.spanIds.some((spanId) => exact.has(spanId))) return true;
  return geometryMatchesRegion(element.bbox, spanPayload.bbox, 0.65);
}

function stage3SpanIdsForElement(items: Stage3SpanItem[], element: CanonicalElement) {
  const available = new Set(items.map((item) => item.spanId));
  const exact = (element.source.stage3_span_ids ?? []).filter((spanId) => available.has(spanId));
  if (exact.length) return [...new Set(exact)];
  return items
    .filter((item) => item.text.trim() && geometryMatchesRegion(item.bbox, element.bbox, 0.35))
    .map((item) => item.spanId);
}

function contiguousResidualSpanGroups(items: Stage3SpanItem[], sourceSpanIds: string[], selected: Set<string>) {
  const itemById = new Map(items.map((item) => [item.spanId, item]));
  const ordered = sourceSpanIds
    .map((spanId) => itemById.get(spanId))
    .filter((item): item is Stage3SpanItem => Boolean(item))
    .sort((a, b) => a.order - b.order);
  const groups: string[][] = [];
  let current: string[] = [];
  for (const item of ordered) {
    if (selected.has(item.spanId)) {
      if (current.length) groups.push(current);
      current = [];
      continue;
    }
    current.push(item.spanId);
  }
  if (current.length) groups.push(current);
  return groups;
}


function correctionOperationTouchesPage(operation: CorrectionOperation, pageNumber: number) {
  if (operation.relationships?.some((relation) => relation.source_page_number === pageNumber || relation.target_page_number === pageNumber)) return true;
  if (operation.target_page_number === pageNumber) return true;
  return operation.page_number === pageNumber;
}

function cloneCanonicalElement(element: CanonicalElement): CanonicalElement {
  return JSON.parse(JSON.stringify(element)) as CanonicalElement;
}

function area(bbox: number[]) {
  return Math.max(0, bbox[2] - bbox[0]) * Math.max(0, bbox[3] - bbox[1]);
}

function intersectionArea(a: number[], b: number[]) {
  const x0 = Math.max(a[0], b[0]);
  const y0 = Math.max(a[1], b[1]);
  const x1 = Math.min(a[2], b[2]);
  const y1 = Math.min(a[3], b[3]);
  return Math.max(0, x1 - x0) * Math.max(0, y1 - y0);
}

function centerInside(inner: number[], outer: number[]) {
  const cx = (inner[0] + inner[2]) / 2;
  const cy = (inner[1] + inner[3]) / 2;
  return outer[0] <= cx && cx <= outer[2] && outer[1] <= cy && cy <= outer[3];
}

function geometryMatchesRegion(source: number[], region: number[], threshold = 0.35) {
  const overlap = intersectionArea(source, region);
  const sourceFraction = overlap / Math.max(area(source), 1);
  const smallerFraction = overlap / Math.max(Math.min(area(source), area(region)), 1);
  return sourceFraction >= threshold || smallerFraction >= threshold || centerInside(source, region) || centerInside(region, source);
}

function validatedBbox(bbox: Array<number | string>, width: number, height: number): { bbox: number[] | null; error: string | null } {
  if (bbox.length !== 4) return { bbox: null, error: "Enter exactly four bbox coordinates." };
  const values = bbox.map(Number);
  if (values.some((value) => !Number.isFinite(value))) return { bbox: null, error: "All bbox coordinates must be finite numbers." };
  let [x0, y0, x1, y1] = values;
  [x0, x1] = [Math.min(x0, x1), Math.max(x0, x1)];
  [y0, y1] = [Math.min(y0, y1), Math.max(y0, y1)];
  x0 = Math.max(0, Math.min(width, x0));
  x1 = Math.max(0, Math.min(width, x1));
  y0 = Math.max(0, Math.min(height, y0));
  y1 = Math.max(0, Math.min(height, y1));
  if (x1 - x0 < 1 || y1 - y0 < 1) return { bbox: null, error: "BBox width and height must be at least 1 PDF point." };
  return { bbox: [x0, y0, x1, y1].map((value) => Math.round(value * 1000) / 1000), error: null };
}

function clampBbox(bbox: number[], width: number, height: number): number[] {
  return validatedBbox(bbox, width, height).bbox ?? [0, 0, Math.min(1, width), Math.min(1, height)];
}

function previewTextAndSource(extraction: DocumentExtraction | null, pageNumber: number, bbox: number[]) {
  const page = extraction?.pages.find((item) => item.page_number === pageNumber);
  if (!page) return { text: "", blockIds: [] as string[], lineIds: [] as string[], spanIds: [] as string[], tableIds: [] as string[] };
  const lines: Array<[number, number, string]> = [];
  const blockIds = new Set<string>();
  const lineIds = new Set<string>();
  const spanIds: string[] = [];
  const seen = new Set<string>();
  for (const item of stage3SpanItems(page)) {
    if (!geometryMatchesRegion(item.bbox, bbox, 0.35)) continue;
    const text = item.text.trim();
    if (!text) continue;
    const key = `${item.bbox.map((value) => value.toFixed(2)).join(",")}|${text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    blockIds.add(item.blockId);
    lineIds.add(item.lineId);
    spanIds.push(item.spanId);
  }
  for (const block of page.blocks) {
    if (block.type !== "text") continue;
    block.lines.forEach((line, lineIndex) => {
      const lineId = line.line_id || `${block.block_id}-l${lineIndex + 1}`;
      const parts = stage3SpanItems(page).filter((item) => item.lineId === lineId && spanIds.includes(item.spanId)).sort((a, b) => a.bbox[0] - b.bbox[0]);
      if (parts.length) lines.push([line.bbox[1], line.bbox[0], parts.map((item) => item.text).join("").trim()]);
    });
  }
  lines.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const tableIds = page.tables.filter((table) => geometryMatchesRegion(table.bbox, bbox, 0.2)).map((table) => table.table_id);
  return { text: lines.map((item) => item[2]).filter(Boolean).join("\n").trim(), blockIds: [...blockIds], lineIds: [...lineIds], spanIds, tableIds };
}

function clearIncompatibleMetadata(element: CanonicalElement, newType: CanonicalElementType) {
  if (newType !== "section_header") {
    element.heading_level = null;
    element.heading_level_source = null;
  }
  if (newType !== "clause" && newType !== "subclause") {
    element.clause_number = null;
    element.clause_id = null;
    element.parent_clause_id = null;
    element.subclause_marker = null;
  }
  // A semantic type change must never silently carry a previous definition
  // membership into the new role. Definition membership is an explicit
  // Stage 4.5 relationship decision and can be re-applied after relabeling.
  element.definition_entry_id = null;
  if (newType !== "table") {
    element.logical_table_id = null;
    element.table = null;
  }
  if (newType !== "figure") element.figure_id = null;
}

function horizontalOverlapFraction(a: number[], b: number[]) {
  const overlap = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
  return overlap / Math.max(Math.min(a[2] - a[0], b[2] - b[0]), 1);
}

function reconcilePreviewReadingOrder(elements: CanonicalElement[], touchedIds: Set<string>) {
  if (elements.length < 2 || touchedIds.size === 0) return elements;
  const result = [...elements];
  const touchedInOrder = result.filter((element) => touchedIds.has(element.element_id)).map((element) => element.element_id);
  for (const elementId of touchedInOrder) {
    const currentIndex = result.findIndex((element) => element.element_id === elementId);
    if (currentIndex < 0) continue;
    const [item] = result.splice(currentIndex, 1);
    const comparable = result
      .map((other, index) => ({ other, index }))
      .filter(({ other }) => horizontalOverlapFraction(item.bbox, other.bbox) >= 0.2);
    if (!comparable.length) {
      result.splice(Math.min(currentIndex, result.length), 0, item);
      continue;
    }
    const above = comparable.filter(({ other }) => other.bbox[3] <= item.bbox[1] + 0.5).map(({ index }) => index);
    const below = comparable.filter(({ other }) => item.bbox[3] <= other.bbox[1] + 0.5).map(({ index }) => index);
    const lowerBound = above.length ? Math.max(...above) + 1 : 0;
    const upperBound = below.length ? Math.min(...below) : result.length;
    const insertAt = lowerBound <= upperBound
      ? Math.min(Math.max(currentIndex, lowerBound), upperBound)
      : Math.min(currentIndex, result.length);
    result.splice(insertAt, 0, item);
  }
  result.forEach((element, index) => { element.reading_order = index; });
  return result;
}

function localApplyCorrection(
  source: CanonicalElement[],
  operation: CorrectionOperation,
  width: number,
  height: number,
  extraction: DocumentExtraction | null,
): CanonicalElement[] {
  const elements = source.map(cloneCanonicalElement);
  const indexOf = (id: string) => elements.findIndex((element) => element.element_id === id);

  if (operation.operation === "relabel" && operation.source_element_ids.length > 0 && operation.new_type) {
    for (const elementId of operation.source_element_ids) {
      const index = indexOf(elementId);
      if (index < 0) continue;
      const oldType = elements[index].type;
      elements[index].type = operation.new_type;
      elements[index].role_source = "manual_relabel_preview";
      if (oldType !== operation.new_type) clearIncompatibleMetadata(elements[index], operation.new_type);
    }
    return elements;
  }

  if (operation.operation === "set_structure" && operation.source_element_ids.length === 1 && operation.structure) {
    const index = indexOf(operation.source_element_ids[0]);
    if (index >= 0) {
      const spec = operation.structure;
      const element = elements[index];
      element.type = spec.type;
      element.role_source = "manual_structural_review_preview";
      element.definition_entry_id = null;
      element.logical_table_id = null;
      element.figure_id = null;
      element.appendix_id = null;
      element.table = null;
      if (spec.type === "section_header") {
        element.section_id = spec.section_id ?? null;
        element.heading_level = spec.heading_level ?? null;
        element.heading_level_source = "unknown";
        element.clause_id = null;
        element.clause_number = null;
        element.parent_clause_id = null;
        element.subclause_marker = null;
      } else if (spec.type === "clause") {
        element.section_id = spec.section_id ?? null;
        element.heading_level = null;
        element.heading_level_source = null;
        element.clause_id = spec.clause_id ?? null;
        element.clause_number = spec.clause_number ?? null;
        element.parent_clause_id = spec.parent_clause_id ?? null;
        element.subclause_marker = null;
      } else {
        element.section_id = spec.section_id ?? null;
        element.heading_level = null;
        element.heading_level_source = null;
        element.clause_id = spec.clause_id ?? null;
        element.clause_number = null;
        element.parent_clause_id = spec.parent_clause_id ?? null;
        element.subclause_marker = spec.subclause_marker ?? null;
      }
    }
    return elements;
  }

  if (operation.operation === "delete") {
    const ids = new Set(operation.source_element_ids);
    return elements.filter((element) => !ids.has(element.element_id));
  }

  if (operation.operation === "link_definition" && operation.source_element_ids.length === 2) {
    const [termId, textId] = operation.source_element_ids;
    const term = elements.find((element) => element.element_id === termId);
    const definitionText = elements.find((element) => element.element_id === textId);
    if (!term || !definitionText || term.type !== "definition_term" || definitionText.type !== "definition_text") return elements;
    const definitionId = term.definition_entry_id || `manual-def-${term.element_id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
    term.definition_entry_id = definitionId;
    definitionText.definition_entry_id = definitionId;
    definitionText.section_id = term.section_id ?? null;
    term.role_source = "manual_definition_link_preview";
    definitionText.role_source = "manual_definition_link_preview";
    return elements;
  }

  if (operation.operation === "unlink_definition" && operation.source_element_ids.length === 2) {
    const [termId, textId] = operation.source_element_ids;
    const term = elements.find((element) => element.element_id === termId);
    const definitionText = elements.find((element) => element.element_id === textId);
    if (!term || !definitionText || term.type !== "definition_term" || definitionText.type !== "definition_text") return elements;
    if (term.definition_entry_id && definitionText.definition_entry_id === term.definition_entry_id) {
      const definitionId = term.definition_entry_id;
      definitionText.definition_entry_id = null;
      definitionText.role_source = "manual_definition_unlink_preview";
      if (!elements.some((element) => element.type === "definition_text" && element.element_id !== definitionText.element_id && element.definition_entry_id === definitionId)) {
        term.definition_entry_id = null;
        term.role_source = "manual_definition_unlink_preview";
      }
    }
    return elements;
  }

  if (operation.operation === "move_resize" && operation.source_element_ids.length === 1 && operation.result_elements.length === 1) {
    const index = indexOf(operation.source_element_ids[0]);
    if (index >= 0) {
      const bbox = clampBbox(operation.result_elements[0].bbox, width, height);
      elements[index].bbox = bbox;
      const recovered = previewTextAndSource(extraction, operation.page_number, bbox);
      elements[index].text = recovered.text;
      elements[index].source = {
        layout_box_index: -1,
        layout_box_class: "manual_bbox_preview",
        stage3_block_ids: recovered.blockIds,
        stage3_line_ids: recovered.lineIds,
        stage3_span_ids: recovered.spanIds,
        stage3_table_ids: recovered.tableIds,
      };
      elements[index].role_source = "manual_bbox_preview";
    }
    return elements;
  }

  if (operation.operation === "split" && operation.source_element_ids.length === 1) {
    const index = indexOf(operation.source_element_ids[0]);
    if (index < 0) return elements;
    const template = elements[index];
    const usedText = new Set<string>();
    const replacements = operation.result_elements.map((spec) => {
      const bbox = clampBbox(spec.bbox, width, height);
      const recovered = previewTextAndSource(extraction, operation.page_number, bbox);
      let text = recovered.text;
      // Avoid showing the same coarse Stage-3 span in both split halves. The
      // backend performs a stricter exclusive span assignment on save.
      if (text && usedText.has(text)) text = "";
      if (text) usedText.add(text);
      const next = {
        ...cloneCanonicalElement(template),
        element_id: spec.element_id,
        type: spec.type,
        bbox,
        text,
        role_source: "manual_split_preview",
        source: {
          layout_box_index: -1,
          layout_box_class: "manual_split_preview",
          stage3_block_ids: recovered.blockIds,
          stage3_line_ids: recovered.lineIds,
          stage3_span_ids: recovered.spanIds,
          stage3_table_ids: recovered.tableIds,
        },
      };
      if (spec.type !== template.type) clearIncompatibleMetadata(next, spec.type);
      return next;
    });
    elements.splice(index, 1, ...replacements);
    return elements;
  }

  if (operation.operation === "merge" && operation.result_elements.length === 1) {
    const ids = new Set(operation.source_element_ids);
    const selected = elements.filter((element) => ids.has(element.element_id));
    if (selected.length < 2) return elements;
    const insertAt = Math.min(...selected.map((element) => indexOf(element.element_id)));
    const spec = operation.result_elements[0];
    const bbox = clampBbox(spec.bbox, width, height);
    const recovered = previewTextAndSource(extraction, operation.page_number, bbox);
    const merged = {
      ...cloneCanonicalElement(selected[0]),
      element_id: spec.element_id,
      type: spec.type,
      bbox,
      text: recovered.text,
      role_source: "manual_merge_preview",
      source: {
        layout_box_index: -1,
        layout_box_class: "manual_merge_preview",
        stage3_block_ids: recovered.blockIds,
        stage3_line_ids: recovered.lineIds,
        stage3_span_ids: recovered.spanIds,
        stage3_table_ids: recovered.tableIds,
      },
    };
    const remainder = elements.filter((element) => !ids.has(element.element_id));
    remainder.splice(Math.min(insertAt, remainder.length), 0, merged);
    return remainder;
  }

  if (operation.operation === "span_rebuild" && operation.result_elements.length >= 1) {
    const sourceIds = new Set(operation.source_element_ids);
    const sourceElements = elements.filter((element) => sourceIds.has(element.element_id));
    const rawPage = extraction?.pages.find((page) => page.page_number === operation.page_number);
    const spanItems = stage3SpanItems(rawPage);
    const sourceSpanSets = new Map(sourceElements.map((element) => [element.element_id, new Set(stage3SpanIdsForElement(spanItems, element))]));
    const replacements: CanonicalElement[] = [];
    for (const spec of operation.result_elements) {
      const selected = spanSelectionPayload(spanItems, spec.source_span_ids ?? []);
      if (!selected) continue;
      const selectedSet = new Set(selected.spanIds);
      const owningSources = sourceElements.filter((element) => {
        const sourceSet = sourceSpanSets.get(element.element_id) ?? new Set<string>();
        return selectedSet.size > 0 && [...selectedSet].every((spanId) => sourceSet.has(spanId));
      });
      const matchingTemplate = sourceElements.find((element) => element.element_id === spec.element_id)
        ?? (owningSources.length === 1 ? owningSources[0] : null)
        ?? (sourceElements.length === 1 && operation.result_elements.length === 1 ? sourceElements[0] : null);
      if (matchingTemplate) {
        const next = cloneCanonicalElement(matchingTemplate);
        const oldType = next.type;
        next.element_id = spec.element_id;
        next.type = spec.type;
        next.bbox = selected.bbox;
        next.text = selected.text;
        next.role_source = "manual_span_rebuild_preview";
        next.source = {
          layout_box_index: -1,
          layout_box_class: "manual_span_rebuild_preview",
          stage3_block_ids: selected.blockIds,
          stage3_line_ids: selected.lineIds,
          stage3_span_ids: selected.spanIds,
          stage3_table_ids: [],
        };
        next.table = null;
        if (oldType !== spec.type) clearIncompatibleMetadata(next, spec.type);
        replacements.push(next);
      } else {
        const prior = elements.filter((element) => !sourceIds.has(element.element_id) && element.section_id && (element.bbox[1] < selected.bbox[1] || (element.bbox[1] === selected.bbox[1] && element.bbox[0] <= selected.bbox[0])));
        replacements.push({
          element_id: spec.element_id,
          type: spec.type,
          page_number: operation.page_number,
          reading_order: elements.length,
          document_order: elements.length,
          bbox: selected.bbox,
          text: selected.text,
          section_id: prior.length ? prior[prior.length - 1].section_id : null,
          role_source: "manual_span_rebuild_preview",
          source: {
            layout_box_index: -1,
            layout_box_class: "manual_span_rebuild_preview",
            stage3_block_ids: selected.blockIds,
            stage3_line_ids: selected.lineIds,
            stage3_span_ids: selected.spanIds,
            stage3_table_ids: [],
          },
        });
      }
    }
    const remaining = elements.filter((element) => !sourceIds.has(element.element_id));
    const sourceIndices = sourceElements.map((element) => indexOf(element.element_id)).filter((index) => index >= 0);
    const insertAt = sourceIndices.length ? Math.min(...sourceIndices) : remaining.findIndex((element) => replacements.length && (element.bbox[1] > replacements[0].bbox[1] || (element.bbox[1] === replacements[0].bbox[1] && element.bbox[0] > replacements[0].bbox[0])));
    replacements.sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]);
    remaining.splice(insertAt < 0 ? remaining.length : Math.min(insertAt, remaining.length), 0, ...replacements);
    return remaining;
  }

  if (operation.operation === "draw" && operation.result_elements.length === 1) {
    const spec = operation.result_elements[0];
    const bbox = clampBbox(spec.bbox, width, height);
    const recovered = previewTextAndSource(extraction, operation.page_number, bbox);
    elements.push({
      element_id: spec.element_id,
      type: spec.type,
      page_number: operation.page_number,
      reading_order: elements.length,
      document_order: elements.length,
      bbox,
      text: recovered.text,
      role_source: "manual_draw_preview",
      source: {
        layout_box_index: -1,
        layout_box_class: "manual_draw_preview",
        stage3_block_ids: recovered.blockIds,
        stage3_line_ids: recovered.lineIds,
        stage3_span_ids: recovered.spanIds,
        stage3_table_ids: recovered.tableIds,
      },
    });
    elements.sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]);
    return elements;
  }

  return elements;
}

function previewElementBodyText(element: CanonicalElement) {
  const included = new Set<CanonicalElementType>(["title", "subtitle", "section_header", "group_header", "clause", "subclause", "definition_term", "definition_text", "paragraph", "list_item", "table", "caption", "footnote", "formula"]);
  if (!included.has(element.type)) return "";
  if (element.type === "table" && element.table?.markdown) return element.table.markdown.trim();
  return element.text.trim();
}

function reconcilePreviewStructure(
  source: StructuredDocument,
  pageNumber: number,
  workingElements: CanonicalElement[],
  relationships: StructuralRelation[],
): StructuredDocument {
  const preview = JSON.parse(JSON.stringify(source)) as StructuredDocument;
  const page = preview.pages.find((item) => item.page_number === pageNumber);
  if (page) page.elements = workingElements.map(cloneCanonicalElement);

  let documentOrder = 0;
  for (const currentPage of preview.pages) {
    currentPage.elements.forEach((element, index) => {
      element.page_number = currentPage.page_number;
      element.reading_order = index;
      element.document_order = documentOrder++;
    });
    currentPage.body_text = currentPage.elements.map(previewElementBodyText).filter(Boolean).join("\n\n");
  }
  preview.body_text = preview.pages.map((item) => item.body_text).filter(Boolean).join("\n\n");

  const elements = preview.pages.flatMap((item) => item.elements);
  const byId = new Map(elements.map((element) => [element.element_id, element]));
  const ids = new Set(byId.keys());
  preview.outline_root_element_id = preview.outline_root_element_id && ids.has(preview.outline_root_element_id) ? preview.outline_root_element_id : null;
  preview.metadata_element_ids = preview.metadata_element_ids.filter((id) => ids.has(id));

  preview.sections = preview.sections.filter((section) => byId.get(section.element_id)?.type === "section_header");
  const validSections = new Set(preview.sections.map((section) => section.section_id));
  preview.sections.forEach((section) => {
    section.content_element_ids = [];
    if (section.parent_section_id && !validSections.has(section.parent_section_id)) section.parent_section_id = null;
    const element = byId.get(section.element_id);
    if (element) {
      section.page_number = element.page_number;
      if (element.text.trim()) section.title = element.text.trim();
    }
  });
  elements.forEach((element) => { if (element.section_id && !validSections.has(element.section_id)) element.section_id = null; });
  const sectionById = new Map(preview.sections.map((section) => [section.section_id, section]));
  elements.forEach((element) => {
    if (element.type !== "section_header" && element.section_id && sectionById.has(element.section_id)) {
      sectionById.get(element.section_id)!.content_element_ids.push(element.element_id);
    }
  });

  preview.clauses = preview.clauses.filter((clause) => byId.get(clause.element_id)?.type === clause.kind);
  const validClauses = new Set(preview.clauses.map((clause) => clause.clause_id));
  preview.clauses.forEach((clause) => {
    const element = byId.get(clause.element_id);
    if (!element) return;
    clause.page_number = element.page_number;
    clause.section_id = element.section_id;
    if (clause.parent_clause_id && !validClauses.has(clause.parent_clause_id)) clause.parent_clause_id = null;
    element.clause_id = clause.clause_id;
    element.parent_clause_id = clause.parent_clause_id ?? null;
    if (clause.kind === "clause") {
      element.clause_number = clause.number;
      element.subclause_marker = null;
    } else {
      element.clause_number = null;
      element.subclause_marker = clause.number;
    }
  });

  preview.appendices = preview.appendices.filter((appendix) => ids.has(appendix.label_element_id) && (!appendix.title_element_id || ids.has(appendix.title_element_id)));
  preview.tables = preview.tables.filter((table) => table.fragment_element_ids.every((id) => byId.get(id)?.type === "table" && Boolean(byId.get(id)?.table)));
  preview.figures = preview.figures.filter((figure) => byId.get(figure.element_id)?.type === "figure");
  preview.figures.forEach((figure) => {
    figure.intro_element_ids = figure.intro_element_ids.filter((id) => ids.has(id));
    figure.caption_element_ids = figure.caption_element_ids.filter((id) => ids.has(id));
    figure.explanation_element_ids = figure.explanation_element_ids.filter((id) => ids.has(id));
    figure.source_element_ids = figure.source_element_ids.filter((id) => ids.has(id));
  });
  preview.relationships = relationships.filter((relation) => ids.has(relation.source_element_id) && ids.has(relation.target_element_id));
  const clauseById = new Map(preview.clauses.map((clause) => [clause.clause_id, clause]));
  const sectionRecordById = new Map(preview.sections.map((section) => [section.section_id, section]));
  const clauseElementIds = new Set(preview.clauses.map((clause) => clause.element_id));
  const sectionElementIds = new Set(preview.sections.map((section) => section.element_id));
  preview.relationships = preview.relationships.filter((relation) => !(
    (relation.type === "belongs_to" && clauseElementIds.has(relation.source_element_id) && sectionElementIds.has(relation.target_element_id))
    || (relation.type === "parent_of" && clauseElementIds.has(relation.source_element_id) && clauseElementIds.has(relation.target_element_id))
  ));
  for (const clause of preview.clauses) {
    if (clause.kind === "clause" && clause.section_id && sectionRecordById.has(clause.section_id)) {
      const target = sectionRecordById.get(clause.section_id)!;
      if (!preview.relationships.some((relation) => relation.type === "belongs_to" && relation.source_element_id === clause.element_id && relation.target_element_id === target.element_id)) {
        preview.relationships.push({ relation_id: `preview-${clause.clause_id}-section`, type: "belongs_to", source_element_id: clause.element_id, target_element_id: target.element_id, evidence: "preview canonical clause section membership" });
      }
    }
    if (clause.parent_clause_id && clauseById.has(clause.parent_clause_id)) {
      const parent = clauseById.get(clause.parent_clause_id)!;
      if (!preview.relationships.some((relation) => relation.type === "parent_of" && relation.source_element_id === parent.element_id && relation.target_element_id === clause.element_id)) {
        preview.relationships.push({ relation_id: `preview-${clause.clause_id}-parent`, type: "parent_of", source_element_id: parent.element_id, target_element_id: clause.element_id, evidence: "preview canonical clause parent membership" });
      }
    }
  }

  const oldDefinitionById = new Map(preview.definitions.map((entry) => [entry.definition_id, entry]));
  const tableDefinitions = preview.definitions.filter((entry) => entry.source_kind === "table_rows" && entry.source_table_element_id && byId.get(entry.source_table_element_id)?.type === "table");
  const grouped = new Map<string, { term: CanonicalElement | null; texts: CanonicalElement[] }>();
  for (const element of elements) {
    if (!element.definition_entry_id || (element.type !== "definition_term" && element.type !== "definition_text")) continue;
    if (!grouped.has(element.definition_entry_id)) grouped.set(element.definition_entry_id, { term: null, texts: [] });
    const group = grouped.get(element.definition_entry_id)!;
    if (element.type === "definition_term") group.term = element;
    if (element.type === "definition_text") group.texts.push(element);
  }
  const layoutDefinitions = [...grouped.entries()].flatMap(([definitionId, group]) => {
    if (!group.term || group.texts.length === 0) return [];
    group.texts.sort((a, b) => a.document_order - b.document_order);
    const pages = [group.term.page_number, ...group.texts.map((item) => item.page_number)];
    const existing = oldDefinitionById.get(definitionId);
    return [{
      definition_id: definitionId,
      term: group.term.text,
      section_id: group.term.section_id ?? null,
      term_element_id: group.term.element_id,
      source_table_element_id: null,
      source_kind: "layout_columns" as const,
      definition_text: group.texts.map((item) => item.text).filter(Boolean).join("\n\n"),
      items: existing?.items ?? [],
      definition_element_ids: group.texts.map((item) => item.element_id),
      start_page: Math.min(...pages),
      end_page: Math.max(...pages),
      spans_multiple_pages: Math.min(...pages) !== Math.max(...pages),
      continues_to_next_page: existing?.continues_to_next_page ?? false,
    }];
  });
  preview.definitions = [...layoutDefinitions, ...tableDefinitions].sort((a, b) => {
    const aId = a.term_element_id ?? a.source_table_element_id ?? "";
    const bId = b.term_element_id ?? b.source_table_element_id ?? "";
    return (byId.get(aId)?.document_order ?? Number.MAX_SAFE_INTEGER) - (byId.get(bId)?.document_order ?? Number.MAX_SAFE_INTEGER);
  });

  const counts = new Map<string, number>();
  elements.forEach((element) => counts.set(element.type, (counts.get(element.type) ?? 0) + 1));
  preview.summary.element_count = elements.length;
  preview.summary.body_text_char_count = preview.body_text.length;
  preview.summary.section_count = preview.sections.length;
  preview.summary.definition_count = preview.definitions.length;
  preview.summary.clause_count = preview.clauses.length;
  preview.summary.appendix_count = preview.appendices.length;
  preview.summary.logical_table_count = preview.tables.length;
  preview.summary.figure_count = preview.figures.length;
  preview.summary.relation_count = preview.relationships.length;
  preview.summary.element_counts = Object.fromEntries([...counts.entries()].sort(([a], [b]) => a.localeCompare(b)));
  return preview;
}

function EditableStructureOverlay({
  element,
  width,
  height,
  selected,
  onSelect,
  onCommitBbox,
  splitY = null,
  editable = true,
}: {
  element: CanonicalElement;
  width: number;
  height: number;
  selected: boolean;
  onSelect: (multi: boolean) => void;
  onCommitBbox: (bbox: number[]) => void;
  splitY?: number | null;
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
    const multiSelect = event.shiftKey || event.ctrlKey || event.metaKey;
    onSelect(multiSelect);
    // Modifier-click is selection-only. Do not accidentally move a box while
    // the reviewer is building a multi-selection for merge/suppress actions.
    if (multiSelect || !editable) return;
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

  function cancelDrag(event: ReactPointerEvent<HTMLElement>) {
    if (!drag) return;
    event.preventDefault();
    event.stopPropagation();
    setPreview(element.bbox);
    setDrag(null);
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
      onPointerCancel={cancelDrag}
      title={`${labelType(element.type)} · ${element.element_id}`}
    >
      {selected && <span className="editable-overlay-label">{element.element_id} · {labelType(element.type)}</span>}
      {selected && splitY !== null && splitY > y0 && splitY < y1 && (
        <span className="split-guide" style={{ top: `${((splitY - y0) / Math.max(y1 - y0, 1)) * 100}%` }} />
      )}
      {editable && selected && (["nw", "ne", "sw", "se"] as const).map((handle) => (
        <span
          key={handle}
          className={`resize-handle ${handle}`}
          onPointerDown={(event: ReactPointerEvent<HTMLSpanElement>) => startDrag(event, handle)}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={cancelDrag}
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
  const formattedElementBbox = element.bbox.map((value) => value.toFixed(1));
  const [values, setValues] = useState(formattedElementBbox);
  const [feedback, setFeedback] = useState<"idle" | "applied">("idle");
  const feedbackTimerRef = useRef<number | null>(null);

  useEffect(() => {
    setValues(element.bbox.map((value) => value.toFixed(1)));
  }, [element.element_id, element.bbox.join(",")]);

  useEffect(() => {
    setFeedback("idle");
  }, [element.element_id]);

  useEffect(() => () => {
    if (feedbackTimerRef.current !== null) window.clearTimeout(feedbackTimerRef.current);
  }, []);

  const labels = ["x0", "y0", "x1", "y1"];
  const validation = validatedBbox(values, width, height);
  const baselineBbox = formattedElementBbox.map(Number);
  const hasChanges = Boolean(validation.bbox) && validation.bbox!.some((value, index) => Math.abs(value - baselineBbox[index]) > 0.0005);

  function clearAppliedFeedback() {
    if (feedbackTimerRef.current !== null) {
      window.clearTimeout(feedbackTimerRef.current);
      feedbackTimerRef.current = null;
    }
    setFeedback("idle");
  }

  function applyBbox() {
    if (!validation.bbox || !hasChanges) return;
    onApply(validation.bbox);
    setFeedback("applied");
    if (feedbackTimerRef.current !== null) window.clearTimeout(feedbackTimerRef.current);
    feedbackTimerRef.current = window.setTimeout(() => {
      setFeedback("idle");
      feedbackTimerRef.current = null;
    }, 2200);
  }

  const statusText = validation.error
    ? validation.error
    : feedback === "applied"
      ? "Applied to correction draft. Use Save corrections to persist this change."
      : hasChanges
        ? "BBox changed. Apply the coordinates to add this edit to the correction draft."
        : "No bbox changes to apply.";

  return (
    <div className={`bbox-editor ${feedback === "applied" ? "bbox-editor-applied" : ""}`}>
      <div className="bbox-editor-title"><span>Region coordinates</span><small>PDF page coordinates</small></div>
      {labels.map((label, index) => (
        <label key={label}><span>{label}</span><input value={values[index]} onChange={(event: ChangeEvent<HTMLInputElement>) => {
          const next = [...values]; next[index] = event.target.value; setValues(next); clearAppliedFeedback();
        }} /></label>
      ))}
      <button
        className={feedback === "applied" ? "bbox-apply-success" : ""}
        disabled={!validation.bbox || !hasChanges || feedback === "applied"}
        onClick={applyBbox}
      >
        {feedback === "applied" ? "Applied ✓" : "Apply bbox change"}
      </button>
      <small
        className={`bbox-status ${validation.error ? "error" : feedback === "applied" ? "success" : hasChanges ? "dirty" : "idle"}`}
        aria-live="polite"
      >
        {statusText}
      </small>
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
              {operation.definition_id && <small>definition: {operation.definition_id}</small>}
              {operation.structure && <small>structure: {labelType(operation.structure.type)} · section {operation.structure.section_id ?? "none"}{operation.structure.clause_id ? ` · clause ${operation.structure.clause_id}` : ""}{operation.structure.parent_clause_id ? ` · parent ${operation.structure.parent_clause_id}` : ""}</small>}
              {operation.note && <small>note: {operation.note}</small>}
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
  const pendingTreeSelectionRef = useRef<string | null>(null);
  const [showOverlays, setShowOverlays] = useState(true);
  const [showLabels, setShowLabels] = useState(false);
  const [filter, setFilter] = useState<"all" | CanonicalElementType>("all");
  const [inspectorMode, setInspectorMode] = useState<"elements" | "json">("elements");
  const [treeScope, setTreeScope] = useState<"page-window" | "document">("page-window");
  const [overviewCollapsed, setOverviewCollapsed] = useStoredBoolean("rag-structure-overview-collapsed", false);
  const [inspectorCollapsed, setInspectorCollapsed] = useStoredBoolean("rag-stage4-inspector-collapsed", false);

  useEffect(() => {
    if (!resolved && viewMode === "resolved") setViewMode("automatic");
  }, [resolved?.resolved_at]);

  useEffect(() => {
    const pendingSelection = pendingTreeSelectionRef.current;
    pendingTreeSelectionRef.current = null;
    setSelectedId(pendingSelection);
    setFilter("all");
    setInspectorMode("elements");
  }, [document.document_id, pageNumber, viewMode]);

  const displayStructure = viewMode === "resolved" && resolved ? resolved.structure : automaticStructure;
  const page = displayStructure.pages[pageNumber - 1];
  if (!page) return <div className="empty-state">No structured pages found.</div>;

  const filtered = filter === "all" ? page.elements : page.elements.filter((element) => element.type === filter);
  const selectedElement = selectedId ? page.elements.find((element) => element.element_id === selectedId) ?? null : null;
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
    const hierarchyTypes = new Set<CanonicalElementType>(["group_header", "clause", "subclause", "list_item"]);
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

  function selectFromDocumentTree(elementId: string, targetPage: number) {
    setFilter("all");
    setInspectorMode("elements");
    if (targetPage === pageNumber) {
      setSelectedId(elementId);
      return;
    }
    pendingTreeSelectionRef.current = elementId;
    setPageNumber(targetPage);
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

      <div className="v2-structure-workspace-grid">
        <DocumentTree
          structure={displayStructure}
          selectedElementId={selectedId}
          currentPage={pageNumber}
          onSelectElement={selectFromDocumentTree}
          onJumpContinuation={selectFromDocumentTree}
          title={treeScope === "page-window" ? "Nearby page structure" : "Document tree"}
          subtitle={treeScope === "page-window"
            ? `Previous, current, and next page around p${pageNumber}. Current-page nodes are emphasized.`
            : "Full canonical document hierarchy. Select a node to locate its region on the PDF."}
          resolved={viewMode === "resolved"}
          collapsible
          scope={treeScope}
          scopeToggle={{ value: treeScope, onChange: setTreeScope }}
        />
        <div className={`extraction-workspace v2-structure-inspection ${inspectorCollapsed ? "inspector-collapsed" : ""}`}>
          <div className="page-panel">
          <div className="panel-toolbar">
            <PageNav pageNumber={pageNumber} total={displayStructure.pages.length} setPageNumber={setPageNumber} />
            <div className="panel-toolbar-actions">
              <OverlayToggle checked={showOverlays} onChange={setShowOverlays} />
              <OverlayLabelToggle checked={showLabels} onChange={setShowLabels} disabled={!showOverlays} />
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
              <StructureOverlayBox key={element.element_id} element={element} width={page.width} height={page.height} selected={selectedId === element.element_id} onClick={() => setSelectedId(element.element_id)} showLabel={showLabels} />
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
            {selectedElement?.table && <TableStructureInspector table={selectedElement.table} elementId={selectedElement.element_id} />}
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

function SpanOverlayBox({
  item,
  width,
  height,
  selected,
  onSelect,
}: {
  item: Stage3SpanItem;
  width: number;
  height: number;
  selected: boolean;
  onSelect: (multi: boolean) => void;
}) {
  const [x0, y0, x1, y1] = item.bbox;
  return (
    <button
      type="button"
      className={`span-overlay ${selected ? "selected" : ""}`}
      style={{
        left: `${(x0 / width) * 100}%`,
        top: `${(y0 / height) * 100}%`,
        width: `${((x1 - x0) / width) * 100}%`,
        height: `${((y1 - y0) / height) * 100}%`,
      }}
      onClick={(event: ReactMouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        onSelect(event.shiftKey || event.ctrlKey || event.metaKey);
      }}
      title={`${item.spanId}\n${item.text}`}
    >
      {selected && <span>{item.spanId}</span>}
    </button>
  );
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
  const [editScope, setEditScope] = useState<"layout" | "span">("layout");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const pendingTreeSelectionRef = useRef<string | null>(null);
  const [selectedSpanIds, setSelectedSpanIds] = useState<string[]>([]);
  const [spanResultType, setSpanResultType] = useState<CanonicalElementType>("paragraph");
  const [workingElements, setWorkingElements] = useState<CanonicalElement[]>([]);
  const [sessionOps, setSessionOps] = useState<CorrectionOperation[]>([]);
  const sessionOpsRef = useRef<CorrectionOperation[]>([]);
  const [redoOps, setRedoOps] = useState<CorrectionOperation[]>([]);
  const [drawMode, setDrawMode] = useState(false);
  const [drawType, setDrawType] = useState<CanonicalElementType>("paragraph");
  const [drawStart, setDrawStart] = useState<[number, number] | null>(null);
  const [drawCurrent, setDrawCurrent] = useState<[number, number] | null>(null);
  const [splitY, setSplitY] = useState<number | null>(null);
  const [showBeforeOverlay, setShowBeforeOverlay] = useState(true);
  const [showAfterOverlay, setShowAfterOverlay] = useState(true);
  const [filter, setFilter] = useState<"all" | CanonicalElementType>("all");
  const [elementsPanelCollapsed, setElementsPanelCollapsed] = useStoredBoolean("rag-correction-elements-collapsed", false);
  const [selectedEditorCollapsed, setSelectedEditorCollapsed] = useState(false);
  const [definitionSelectionId, setDefinitionSelectionId] = useState("");
  const [integrityPreview, setIntegrityPreview] = useState<RelationshipIntegrityReport | null>(resolved?.integrity ?? null);
  const [validatingIntegrity, setValidatingIntegrity] = useState(false);
  const viewportMode = useViewportMode();
  const compactReview = viewportMode === "compact" || viewportMode === "mobile";
  const [compactPanel, setCompactPanel] = useState<"tree" | "inspector" | null>(null);
  const [compactInspectorView, setCompactInspectorView] = useState<"correct" | "page">("correct");
  const reviewWorkspaceRef = useRef<HTMLDivElement | null>(null);
  const [reviewZoom, setReviewZoom] = useState(1);
  const [reviewZoomMode, setReviewZoomMode] = useState<"fit" | "manual">("fit");

  const reviewZoomBaseWidth = viewportMode === "mobile" ? 620 : viewportMode === "compact" ? 760 : 680;
  const reviewZoomPercent = Math.round(reviewZoom * 100);

  function adjustReviewZoom(delta: number) {
    setReviewZoomMode("manual");
    setReviewZoom((current) => Math.max(0.5, Math.min(2.5, Math.round((current + delta) * 100) / 100)));
  }

  function fitReviewPage() {
    setReviewZoom(1);
    setReviewZoomMode("fit");
  }

  useEffect(() => {
    const workspace = reviewWorkspaceRef.current;
    if (!workspace || compactReview) return;

    const topTarget = 12;
    const canAncestorScroll = (target: EventTarget | null, deltaY: number) => {
      let node = target instanceof HTMLElement ? target : null;
      while (node && node !== workspace) {
        const style = window.getComputedStyle(node);
        const scrollable = /(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1;
        if (scrollable) {
          if (deltaY < 0 && node.scrollTop > 1) return true;
          if (deltaY > 0 && node.scrollTop + node.clientHeight < node.scrollHeight - 1) return true;
        }
        node = node.parentElement;
      }
      return false;
    };

    const handleWheel = (event: WheelEvent) => {
      if (!event.deltaY) return;
      const rect = workspace.getBoundingClientRect();

      if (event.deltaY > 0 && rect.top > topTarget + 1) {
        // Phase 1: finish the browser-page movement until the workbench reaches
        // its resting position, even when the pointer is already over the PDF.
        event.preventDefault();
        const remaining = Math.max(0, rect.top - topTarget);
        window.scrollBy({ top: Math.min(Math.abs(event.deltaY), remaining), behavior: "auto" });
        return;
      }

      if (event.deltaY < 0 && rect.top <= topTarget + 1 && !canAncestorScroll(event.target, event.deltaY)) {
        // Reverse handoff: at the top of the active Tree/PDF/Inspector scroller,
        // return wheel ownership to the browser so the reviewer can reach the
        // controls above without moving the selected/correction state.
        event.preventDefault();
        window.scrollBy({ top: event.deltaY, behavior: "auto" });
      }
    };

    workspace.addEventListener("wheel", handleWheel, { passive: false });
    return () => workspace.removeEventListener("wheel", handleWheel);
  }, [compactReview, mode]);

  useEffect(() => {
    if (!compactReview) setCompactPanel(null);
  }, [compactReview]);

  useEffect(() => {
    fitReviewPage();
  }, [document.document_id]);

  useEffect(() => {
    // Hard-reset the correction editor only when the reviewer actually changes
    // document or page. A late Stage 4 timestamp refresh must never clear a
    // selection that the reviewer has already started interacting with.
    const pendingTreeSelection = pendingTreeSelectionRef.current;
    pendingTreeSelectionRef.current = null;
    setSelectedIds(pendingTreeSelection ? [pendingTreeSelection] : []);
    setSelectedSpanIds([]);
    sessionOpsRef.current = [];
    setSessionOps([]);
    setRedoOps([]);
    setDrawMode(false);
    setSplitY(null);
    setMode("preview");
    setSelectedEditorCollapsed(false);
    setDefinitionSelectionId("");
    setIntegrityPreview(resolved?.integrity ?? null);
    const next = (resolved?.structure ?? structure)?.pages[pageNumber - 1];
    if (next) setWorkingElements(next.elements.map(cloneCanonicalElement));
    else setWorkingElements([]);
  }, [document.document_id, pageNumber]);

  useEffect(() => {
    // Stage 4 can refresh after the sandbox has already become interactive.
    // Refresh the backing elements without treating that refresh like a page
    // navigation. Valid selected IDs are preserved instead of being cleared.
    if (!structure || sessionOpsRef.current.length) return;
    const nextPage = (resolved?.structure ?? structure).pages[pageNumber - 1];
    if (!nextPage) return;
    const nextElements = nextPage.elements.map(cloneCanonicalElement);
    const existingIds = new Set(nextElements.map((element) => element.element_id));
    setWorkingElements(nextElements);
    setSelectedIds((current) => current.filter((id) => existingIds.has(id)));
  }, [structure?.structured_at]);

  useEffect(() => {
    setIntegrityPreview(resolved?.integrity ?? null);
    // A resolved-artifact refresh can happen after validation/save. Do not
    // destroy an active local edit session or its selection merely because
    // the parent refreshed resolved_at. When there is no unsaved session,
    // refresh the page from the new resolved structure and preserve any
    // selected element IDs that still exist.
    if (sessionOpsRef.current.length) return;
    const nextPage = (resolved?.structure ?? structure)?.pages[pageNumber - 1];
    if (!nextPage) {
      setWorkingElements([]);
      setSelectedIds([]);
      return;
    }
    const nextElements = nextPage.elements.map(cloneCanonicalElement);
    const existingIds = new Set(nextElements.map((element) => element.element_id));
    setWorkingElements(nextElements);
    setSelectedIds((current) => current.filter((id) => existingIds.has(id)));
  }, [resolved?.resolved_at]);

  useEffect(() => {
    setDefinitionSelectionId("");
    setSelectedSpanIds([]);
    setEditScope("layout");
  }, [document.document_id, structure?.structured_at]);

  if (!structure) return <div className="empty-state">Build structure before using Correction Sandbox.</div>;

  const automaticPage = structure.pages[pageNumber - 1];
  const resolvedStructure = resolved?.structure ?? structure;
  const basePage = resolvedStructure.pages[pageNumber - 1];
  const savedOperations = corrections?.operations ?? [];
  const savedPageOperations = savedOperations.filter((operation) => correctionOperationTouchesPage(operation, pageNumber));

  if (!automaticPage || !basePage) return <div className="empty-state">No structured page found.</div>;

  const selectedElements = workingElements.filter((element) => selectedIds.includes(element.element_id));
  const selectedElement = selectedElements.length === 1 ? selectedElements[0] : null;
  const selectedTypes = [...new Set(selectedElements.map((element) => element.type))];
  const commonSelectedType: CanonicalElementType | "" = selectedTypes.length === 1 ? selectedTypes[0] : "";
  const selectedDefinitionTexts = selectedElements.filter((element) => element.type === "definition_text");
  const selectedOnlyDefinitionTexts = selectedIds.length > 0 && selectedDefinitionTexts.length === selectedIds.length;
  const selectedDefinitionIds = [...new Set(selectedDefinitionTexts.map((element) => element.definition_entry_id).filter((value): value is string => Boolean(value)))];
  const commonSelectedDefinitionId = selectedDefinitionTexts.length > 0
    && selectedDefinitionIds.length === 1
    && selectedDefinitionTexts.every((element) => element.definition_entry_id === selectedDefinitionIds[0])
    ? selectedDefinitionIds[0]
    : "";
  const rawExtractionPage = extraction?.pages.find((item) => item.page_number === pageNumber) ?? null;
  const spanItems = stage3SpanItems(rawExtractionPage);
  const hasPersistedSpanIds = Boolean(rawExtractionPage && rawExtractionPage.blocks
    .filter((block): block is TextBlock => block.type === "text")
    .every((block) => block.lines.every((line) => Boolean(line.line_id) && line.spans.every((span) => Boolean(span.span_id)))));
  const selectedSpanPayload = spanSelectionPayload(spanItems, selectedSpanIds);
  const spanOverlappingElements = selectedSpanPayload ? workingElements.filter((element) => spanOverlapsElement(selectedSpanPayload, element)) : [];
  const unsafeSpanOverlaps = spanOverlappingElements.filter((element) => !SAFE_SPAN_REBUILD_TYPES.has(element.type));
  const selectedSpanSet = new Set(selectedSpanPayload?.spanIds ?? []);
  const residualSourceSpanIds = [...new Set(spanOverlappingElements
    .filter((element) => SAFE_SPAN_REBUILD_TYPES.has(element.type))
    .flatMap((element) => stage3SpanIdsForElement(spanItems, element))
    .filter((spanId) => !selectedSpanSet.has(spanId)))];
  const filteredWorking = filter === "all" ? workingElements : workingElements.filter((element) => element.type === filter);
  const elementById = new Map<string, CanonicalElement>();
  for (const page of resolvedStructure.pages) {
    for (const element of page.elements) elementById.set(element.element_id, element);
  }
  for (const element of workingElements) elementById.set(element.element_id, element);
  const previewRelationships = resolvedStructure.relationships;


  function makeOperation(
    partial: Omit<CorrectionOperation, "operation_id" | "created_at" | "relationships">,
  ): CorrectionOperation {
    return {
      ...partial,
      relationships: [],
      operation_id: makeOperationId(),
      created_at: new Date().toISOString(),
    };
  }

  function replaceSessionOps(nextOps: CorrectionOperation[]) {
    sessionOpsRef.current = nextOps;
    setSessionOps(nextOps);
  }

  function rebuildWorking(nextOps: CorrectionOperation[], preferredSelection: string[] | null = null) {
    let next = basePage.elements.map(cloneCanonicalElement);
    for (const operation of nextOps) next = localApplyCorrection(next, operation, basePage.width, basePage.height, extraction);
    for (const operation of nextOps) {
      if (operation.operation === "assign_definition" || operation.operation === "unassign_definition") {
        const entry = operation.definition_id
          ? resolvedStructure.definitions.find((candidate) => candidate.definition_id === operation.definition_id) ?? null
          : null;
        const term = entry?.term_element_id ? elementById.get(entry.term_element_id) ?? null : null;
        const sectionId = term?.section_id ?? entry?.section_id ?? null;
        for (const elementId of operation.source_element_ids) {
          const target = next.find((element) => element.element_id === elementId);
          if (!target || target.type !== "definition_text") continue;
          if (operation.operation === "assign_definition" && entry) {
            target.definition_entry_id = entry.definition_id;
            target.section_id = sectionId;
            target.role_source = "manual_definition_assign_preview";
          } else if (operation.operation === "unassign_definition") {
            target.definition_entry_id = null;
            target.role_source = "manual_definition_unassign_preview";
          }
        }
        continue;
      }
      if ((operation.operation === "link_definition" || operation.operation === "unlink_definition") && operation.source_element_ids.length === 2) {
        const [termId, textId] = operation.source_element_ids;
        const target = next.find((element) => element.element_id === textId);
        if (!target) continue;
        const term = elementById.get(termId);
        if (!term) continue;
        const definitionId = term.definition_entry_id || `manual-def-${termId.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
        if (operation.operation === "link_definition") {
          target.definition_entry_id = definitionId;
          target.section_id = term.section_id ?? null;
          target.role_source = "manual_definition_link_preview";
        } else if (target.definition_entry_id === definitionId) {
          target.definition_entry_id = null;
          target.role_source = "manual_definition_unlink_preview";
        }
      }
    }
    if (nextOps.some((operation) => ["move_resize", "split", "merge", "draw", "span_rebuild"].includes(operation.operation))) {
      const touchedIds = new Set<string>();
      for (const operation of nextOps) {
        if (operation.operation === "move_resize") operation.source_element_ids.forEach((id) => touchedIds.add(id));
        if (["split", "merge", "draw", "span_rebuild"].includes(operation.operation)) operation.result_elements.forEach((spec) => touchedIds.add(spec.element_id));
      }
      next = reconcilePreviewReadingOrder(next, touchedIds);
    }
    setWorkingElements(next);
    const existingIds = new Set(next.map((element) => element.element_id));
    setSelectedIds((current) => {
      const requested = preferredSelection ?? current;
      const preserved = requested.filter((id) => existingIds.has(id));
      if (preserved.length === current.length && preserved.every((id, index) => id === current[index])) return current;
      return preserved;
    });
  }

  function addSessionOperation(operation: CorrectionOperation) {
    const next = [...sessionOpsRef.current, operation];
    replaceSessionOps(next);
    setRedoOps([]);
    setIntegrityPreview(null);
    rebuildWorking(next);
  }

  function addSessionOperations(operations: CorrectionOperation[]) {
    if (!operations.length) return;
    const next = [...sessionOpsRef.current, ...operations];
    replaceSessionOps(next);
    setRedoOps([]);
    setIntegrityPreview(null);
    rebuildWorking(next);
  }

  function selectElement(elementId: string, multi = false) {
    setSplitY(null);
    setDefinitionSelectionId("");
    setSelectedIds((current) => {
      if (!multi) return [elementId];
      return current.includes(elementId) ? current.filter((id) => id !== elementId) : [...current, elementId];
    });
    if (compactReview) {
      setCompactInspectorView("correct");
      setCompactPanel("inspector");
    }
  }

  function selectSpan(spanId: string, multi = false) {
    setSelectedIds([]);
    setSplitY(null);
    setSelectedSpanIds((current) => {
      if (!multi) return [spanId];
      return current.includes(spanId) ? current.filter((id) => id !== spanId) : [...current, spanId];
    });
    if (compactReview) {
      setCompactInspectorView("page");
      setCompactPanel("inspector");
    }
  }

  function applySpanRebuild() {
    if (!selectedSpanPayload) return;
    if (!SAFE_SPAN_REBUILD_TYPES.has(spanResultType)) {
      window.alert(`${labelType(spanResultType)} cannot be safely created from text spans in the generic editor.`);
      return;
    }
    if (unsafeSpanOverlaps.length) {
      window.alert(`The selected spans overlap record-bearing structure (${unsafeSpanOverlaps.map((element) => `${element.element_id}: ${labelType(element.type)}`).join(", ")}). Use the dedicated structural editor instead.`);
      return;
    }

    const sourceElements = spanOverlappingElements.filter((element) => SAFE_SPAN_REBUILD_TYPES.has(element.type));
    const selectedSet = new Set(selectedSpanPayload.spanIds);
    const residualSpecs: CorrectionElementSpec[] = [];
    let hasPartialSource = false;

    for (const element of sourceElements) {
      const sourceSpanIds = stage3SpanIdsForElement(spanItems, element);
      if (element.text.trim() && sourceSpanIds.length === 0) {
        window.alert(`Cannot determine the Stage 3 span coverage for ${element.element_id}. Use element-level correction or re-run Stage 3/4 before using span correction on this element.`);
        return;
      }
      const residualGroups = contiguousResidualSpanGroups(spanItems, sourceSpanIds, selectedSet);
      if (!residualGroups.length) continue;
      hasPartialSource = true;
      residualGroups.forEach((residualIds, groupIndex) => {
        const residual = spanSelectionPayload(spanItems, residualIds);
        if (!residual || !residual.text) return;
        residualSpecs.push({
          element_id: groupIndex === 0 ? element.element_id : makeManualId(pageNumber),
          type: element.type,
          bbox: residual.bbox,
          source_span_ids: residual.spanIds,
        });
      });
      if (residualGroups.some((group) => {
        const residual = spanSelectionPayload(spanItems, group);
        return !residual || !residual.text;
      })) {
        window.alert(`The remaining spans for ${element.element_id} could not be reconstructed safely.`);
        return;
      }
    }

    // Reuse the original ID only when one source element is fully represented
    // by the selected spans. For a partial extraction, keep the original ID on
    // the automatically preserved residual and give the selected span group a
    // new manual ID.
    const resultId = sourceElements.length === 1 && !hasPartialSource
      ? sourceElements[0].element_id
      : makeManualId(pageNumber);
    const resultElements: CorrectionElementSpec[] = [{
      element_id: resultId,
      type: spanResultType,
      bbox: selectedSpanPayload.bbox,
      source_span_ids: selectedSpanPayload.spanIds,
    }, ...residualSpecs];

    addSessionOperation(makeOperation({
      operation: "span_rebuild",
      page_number: pageNumber,
      source_element_ids: sourceElements.map((element) => element.element_id),
      result_elements: resultElements,
      note: sourceElements.length
        ? `rebuilt ${selectedSpanPayload.spanIds.length} selected Stage 3 span(s); preserved ${residualSpecs.reduce((count, spec) => count + (spec.source_span_ids?.length ?? 0), 0)} unselected source span(s)`
        : `created from ${selectedSpanPayload.spanIds.length} Stage 3 span(s)`,
    }));
    setSelectedSpanIds([]);
    setSelectedIds([resultId]);
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
    if (!selectedElements.length) return;
    if (STRUCTURAL_PROMOTION_TYPES.has(type) && selectedElements.some((element) => element.type !== type)) {
      window.alert(`${labelType(type)} is not available in the simplified element editor yet.`);
      return;
    }
    const selectionToPreserve = selectedElements.map((element) => element.element_id);
    const operation = makeOperation({
      operation: "relabel",
      page_number: pageNumber,
      source_element_ids: selectionToPreserve,
      result_elements: [],
      new_type: type,
    });
    const next = [...sessionOpsRef.current, operation];
    replaceSessionOps(next);
    setRedoOps([]);
    setIntegrityPreview(null);
    rebuildWorking(next, selectionToPreserve);
    if (type === "definition_term" || type === "definition_text") setDefinitionSelectionId("");
  }

  async function validateCurrentCorrections() {
    if (!structure) return false;
    setValidatingIntegrity(true);
    try {
      const response = await validateCorrections(document.document_id, {
        base_structured_at: structure.structured_at,
        operations: [...savedOperations, ...sessionOpsRef.current],
      });
      const report = response.resolved?.integrity ?? null;
      setIntegrityPreview(report);
      if (!response.valid) {
        const detail = response.errors[0] || report?.errors[0]?.message || "Structure integrity validation failed.";
        window.alert(detail);
        return false;
      }
      return true;
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Structure validation failed.");
      return false;
    } finally {
      setValidatingIntegrity(false);
    }
  }

  function startSplitSelected() {
    if (!selectedElement) return;
    if (!SAFE_SPLIT_TYPES.has(selectedElement.type)) {
      window.alert(`${labelType(selectedElement.type)} cannot be safely split in the generic layout editor.`);
      return;
    }
    const [x0, y0, x1, y1] = selectedElement.bbox;
    if (y1 - y0 < 6) {
      window.alert("This region is too short to split safely.");
      return;
    }
    setSplitY((y0 + y1) / 2);
  }

  function confirmSplitSelected() {
    if (!selectedElement || splitY === null) return;
    const [x0, y0, x1, y1] = selectedElement.bbox;
    const split = Math.max(y0 + 2, Math.min(y1 - 2, splitY));
    addSessionOperation(makeOperation({
      operation: "split",
      page_number: pageNumber,
      source_element_ids: [selectedElement.element_id],
      result_elements: [
        { element_id: makeManualId(pageNumber), type: selectedElement.type, bbox: [x0, y0, x1, split] },
        { element_id: makeManualId(pageNumber), type: selectedElement.type, bbox: [x0, split, x1, y1] },
      ],
    }));
    setSplitY(null);
    setSelectedIds([]);
  }

  function mergeSelected() {
    const selected = workingElements.filter((element) => selectedIds.includes(element.element_id));
    if (selected.length < 2) return;
    const types = new Set(selected.map((element) => element.type));
    if (types.size !== 1) {
      window.alert("Merge requires regions with the same semantic type. Relabel them first if they are truly one element.");
      return;
    }
    const mergeType = selected[0].type;
    if (!SAFE_MERGE_TYPES.has(mergeType)) {
      window.alert(`${labelType(mergeType)} cannot be safely merged in the generic layout editor.`);
      return;
    }
    if (new Set(selected.map((element) => element.section_id ?? null)).size > 1) {
      window.alert("Merge requires regions from the same section.");
      return;
    }
    if (mergeType === "definition_text" && new Set(selected.map((element) => element.definition_entry_id ?? null)).size > 1) {
      window.alert("Definition text from different definition entries cannot be merged.");
      return;
    }
    const bbox = [
      Math.min(...selected.map((element) => element.bbox[0])),
      Math.min(...selected.map((element) => element.bbox[1])),
      Math.max(...selected.map((element) => element.bbox[2])),
      Math.max(...selected.map((element) => element.bbox[3])),
    ];
    const selectedSet = new Set(selectedIds);
    const blockers = workingElements.filter((element) => {
      if (selectedSet.has(element.element_id)) return false;
      const cx = (element.bbox[0] + element.bbox[2]) / 2;
      const cy = (element.bbox[1] + element.bbox[3]) / 2;
      return bbox[0] <= cx && cx <= bbox[2] && bbox[1] <= cy && cy <= bbox[3];
    });
    if (blockers.length) {
      window.alert(`These regions are not contiguous. Unselected content lies inside the merge area: ${blockers.map((element) => element.element_id).join(", ")}`);
      return;
    }
    addSessionOperation(makeOperation({
      operation: "merge",
      page_number: pageNumber,
      source_element_ids: selected.map((element) => element.element_id),
      result_elements: [{ element_id: makeManualId(pageNumber), type: selected[0].type, bbox }],
    }));
    setSplitY(null);
    setSelectedIds([]);
  }

  function deleteSelected() {
    if (!selectedIds.length) return;
    addSessionOperation(makeOperation({
      operation: "delete",
      page_number: pageNumber,
      source_element_ids: selectedIds,
      result_elements: [],
      note: "suppressed during manual review",
    }));
    setSelectedIds([]);
  }

  function assignSelectedDefinition() {
    if (!selectedOnlyDefinitionTexts) {
      window.alert("Select one or more definition_text elements first.");
      return;
    }
    const definitionId = definitionSelectionId || commonSelectedDefinitionId;
    if (!definitionId) {
      window.alert("Choose the DefinitionEntry these text elements belong to.");
      return;
    }
    addSessionOperation(makeOperation({
      operation: "assign_definition",
      page_number: pageNumber,
      source_element_ids: selectedDefinitionTexts.map((element) => element.element_id),
      result_elements: [],
      definition_id: definitionId,
      note: `assign ${selectedDefinitionTexts.length} definition text element(s) to ${definitionId}`,
    }));
    setDefinitionSelectionId(definitionId);
  }

  function unassignSelectedDefinition() {
    if (!selectedOnlyDefinitionTexts) return;
    addSessionOperation(makeOperation({
      operation: "unassign_definition",
      page_number: pageNumber,
      source_element_ids: selectedDefinitionTexts.map((element) => element.element_id),
      result_elements: [],
      definition_id: null,
      note: `clear definition membership from ${selectedDefinitionTexts.length} element(s)`,
    }));
    setDefinitionSelectionId("");
  }

  function undo() {
    const current = sessionOpsRef.current;
    if (!current.length) return;
    const removed = current[current.length - 1];
    const next = current.slice(0, -1);
    replaceSessionOps(next);
    setRedoOps((items) => [removed, ...items]);
    setIntegrityPreview(null);
    rebuildWorking(next);
  }

  function redo() {
    if (!redoOps.length) return;
    const [nextOperation, ...rest] = redoOps;
    const next = [...sessionOpsRef.current, nextOperation];
    replaceSessionOps(next);
    setRedoOps(rest);
    setIntegrityPreview(null);
    rebuildWorking(next);
  }

  async function savePage() {
    if (!sessionOpsRef.current.length) return;
    if (!(await validateCurrentCorrections())) return;
    await onSaveCorrections([...savedOperations, ...sessionOpsRef.current]);
    replaceSessionOps([]);
    setRedoOps([]);
    setSelectedIds([]);
    setIntegrityPreview(null);
  }

  async function finalizeReview() {
    if (resolved || sessionOpsRef.current.length) return;
    if (!(await validateCurrentCorrections())) return;
    await onSaveCorrections(savedOperations);
    setRedoOps([]);
    setSelectedIds([]);
    setIntegrityPreview(null);
  }

  async function resetPage() {
    if (!savedPageOperations.length && !sessionOps.length) return;
    if (!window.confirm(`Reset all manual corrections on page ${pageNumber}?`)) return;
    const remaining = savedOperations.filter((operation) => !correctionOperationTouchesPage(operation, pageNumber));
    if (remaining.length === 0) await onResetAllCorrections();
    else await onSaveCorrections(remaining);
    replaceSessionOps([]);
    setRedoOps([]);
    setSelectedIds([]);
    setIntegrityPreview(null);
  }

  async function resetAll() {
    if (!savedOperations.length) return;
    if (!window.confirm("Reset every Stage 4.5 correction for this document?")) return;
    await onResetAllCorrections();
    replaceSessionOps([]);
    setRedoOps([]);
    setSelectedIds([]);
    setIntegrityPreview(null);
  }

  function safeSetPage(next: number, pendingSelection: string | null = null) {
    // PageNav can commit again on input blur. Re-committing the current page
    // is not navigation and must never clear the active corrected-region
    // selection or local editor state.
    if (next === pageNumber) {
      if (pendingSelection) selectElement(pendingSelection);
      return;
    }
    if (sessionOpsRef.current.length && !window.confirm("This page has unsaved corrections. Discard them and change page?")) return;
    replaceSessionOps([]);
    setRedoOps([]);
    pendingTreeSelectionRef.current = pendingSelection;
    setSelectedIds([]);
    setDrawMode(false);
    setSplitY(null);
    setIntegrityPreview(resolved?.integrity ?? null);
    setPageNumber(next);
  }

  function selectFromResolvedTree(elementId: string, targetPage: number) {
    setEditScope("layout");
    setSelectedSpanIds([]);
    setDefinitionSelectionId("");
    safeSetPage(targetPage, elementId);
    if (compactReview) setCompactPanel(null);
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
    const elementId = makeManualId(pageNumber);
    addSessionOperation(makeOperation({
      operation: "draw",
      page_number: pageNumber,
      source_element_ids: [],
      result_elements: [{ element_id: elementId, type: drawType, bbox }],
    }));
    setSelectedIds([elementId]);
  }

  function cancelDraw(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drawStart) return;
    event.preventDefault();
    setDrawStart(null);
    setDrawCurrent(null);
  }

  const drawPreview = drawStart && drawCurrent ? clampBbox([
    Math.min(drawStart[0], drawCurrent[0]), Math.min(drawStart[1], drawCurrent[1]),
    Math.max(drawStart[0], drawCurrent[0]), Math.max(drawStart[1], drawCurrent[1]),
  ], basePage.width, basePage.height) : null;

  const definitionMembershipPreview = workingElements
    .filter((element) => element.definition_entry_id && (element.type === "definition_term" || element.type === "definition_text"))
    .reduce<Record<string, { term_element_id: string | null; definition_element_ids: string[] }>>((groups, element) => {
      const definitionId = element.definition_entry_id as string;
      if (!groups[definitionId]) groups[definitionId] = { term_element_id: null, definition_element_ids: [] };
      if (element.type === "definition_term") groups[definitionId].term_element_id = element.element_id;
      if (element.type === "definition_text") groups[definitionId].definition_element_ids.push(element.element_id);
      return groups;
    }, {});
  const beforePayload = buildStructuredSandboxPayload(structure, pageNumber, "stage_4_canonical_structure", null) as Record<string, unknown> | null;
  const previewStructure = reconcilePreviewStructure(resolvedStructure, pageNumber, workingElements, previewRelationships);
  const selectedContinuationLinks = selectedElement ? previewStructure.relationships
    .filter((relation) => relation.type === "continues" && (relation.source_element_id === selectedElement.element_id || relation.target_element_id === selectedElement.element_id))
    .map((relation) => {
      const outgoing = relation.source_element_id === selectedElement.element_id;
      const otherId = outgoing ? relation.target_element_id : relation.source_element_id;
      const other = previewStructure.pages.flatMap((page) => page.elements).find((element) => element.element_id === otherId) ?? null;
      return other ? { relation, outgoing, other } : null;
    })
    .filter((item): item is { relation: StructuralRelation; outgoing: boolean; other: CanonicalElement } => Boolean(item && item.other.page_number !== pageNumber)) : [];
  const afterBase = buildStructuredSandboxPayload(previewStructure, pageNumber, "stage_4_5_resolved_structure", corrections) as Record<string, unknown> | null;
  const afterPayload = afterBase ? {
    ...afterBase,
    stage: "stage_4_5_correction_preview",
    corrections_saved_on_page: savedPageOperations,
    corrections_unsaved_on_page: sessionOps,
    definition_membership_preview: definitionMembershipPreview,
    page: previewStructure.pages.find((page) => page.page_number === pageNumber) ?? { ...basePage, elements: workingElements },
  } : null;
  const beforeParsed = beforePayload ? parseSandboxPayload(beforePayload) : null;
  const afterParsed = afterPayload ? parseSandboxPayload(afterPayload) : null;
  const comparison = beforeParsed && afterParsed ? compareSandboxItems(beforeParsed.items, afterParsed.items) : null;

  return (
    <div className="correction-sandbox">
      <div className="sandbox-header-card correction-sandbox-header">
        <div>
          <span className="eyebrow">Stage 4.5 · Human review</span>
          <h3>Review & correct</h3>
          <p>Select a region from the PDF or resolved document tree, correct only what is wrong, then save non-destructive correction operations.</p>
        </div>
      </div>

      <div className="review-steps" aria-label="Manual correction workflow">
        <div><strong>1</strong><span>Select regions or text spans</span></div>
        <div><strong>2</strong><span>Correct geometry, text spans, or semantic type</span></div>
        <div><strong>3</strong><span>Select a required relation when needed</span></div>
        <div><strong>4</strong><span>Save correction operations</span></div>
      </div>

      <div className="sandbox-status-row">
        <div><strong>{savedPageOperations.length}</strong><span>saved on page</span></div>
        <div><strong>{sessionOps.length}</strong><span>unsaved</span></div>
        {editScope === "layout" && comparison && <div className={comparison.matches ? "match" : "changed"}><strong>{comparison.changed + comparison.added + comparison.removed}</strong><span>before/after changes</span></div>}
        {editScope === "span" && <div className={selectedSpanIds.length ? "changed" : "match"}><strong>{selectedSpanIds.length}</strong><span>selected Stage 3 spans</span></div>}
        <div className={integrityPreview?.status === "pass" ? "match" : integrityPreview?.status === "fail" ? "changed" : ""}><strong>{integrityPreview?.status === "pass" ? "VALID" : integrityPreview?.status === "fail" ? "NEEDS FIX" : sessionOps.length ? "PENDING" : "—"}</strong><span>structure status</span></div>
        <div className="sandbox-status-actions">
          <button disabled={!savedOperations.length || savingCorrections} onClick={resetAll}>Reset all corrections</button>
          <button disabled={!savedPageOperations.length && !sessionOps.length || savingCorrections} onClick={resetPage}>Reset page</button>
          <button
            className="primary-button compact"
            disabled={(resolved ? !sessionOps.length : false) || savingCorrections || validatingIntegrity}
            onClick={sessionOps.length ? savePage : finalizeReview}
          >
            {savingCorrections ? "Saving…" : sessionOps.length ? `Save ${sessionOps.length} correction${sessionOps.length === 1 ? "" : "s"}` : resolved ? "Review finalized" : "Finalize review"}
          </button>
        </div>
      </div>

      <div className="review-data-switcher">
        <span className="review-data-switcher-label">Advanced review data</span>
        <div className="correction-sandbox-tabs" role="tablist" aria-label="Correction sandbox view">
          <button className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>Review workspace</button>
          <button className={mode === "before" ? "active" : ""} onClick={() => setMode("before")}>Before JSON</button>
          <button className={mode === "after" ? "active" : ""} onClick={() => setMode("after")}>After JSON</button>
          <button className={mode === "log" ? "active" : ""} onClick={() => setMode("log")}>Correction Log</button>
        </div>
      </div>

      {mode === "preview" && <>
        <div className="correction-scope-tabs" role="tablist" aria-label="Correction type">
          <button className={editScope === "layout" ? "active" : ""} onClick={() => { setEditScope("layout"); setDefinitionSelectionId(""); setSelectedSpanIds([]); setSelectedIds([]); }}>Element correction</button>
          <button className={editScope === "span" ? "active" : ""} onClick={() => { setEditScope("span"); setDrawMode(false); setDefinitionSelectionId(""); setSelectedIds([]); setSelectedSpanIds([]); }}>Exact text spans</button>
        </div>

        {editScope === "layout" && <div className="correction-toolbar sandbox-correction-toolbar">
          <div className="correction-tools">
            <button className={drawMode ? "active" : ""} onClick={() => setDrawMode((value) => !value)}>＋ Draw</button>
            <select value={drawType} onChange={(event: ChangeEvent<HTMLSelectElement>) => setDrawType(event.target.value as CanonicalElementType)} title="Type for newly drawn regions">
              {STRUCTURE_FILTERS.filter((type): type is CanonicalElementType => type !== "all" && SAFE_DRAW_TYPES.has(type)).map((type) => <option key={type} value={type}>{labelType(type)}</option>)}
            </select>
            <button disabled={selectedIds.length !== 1 || !selectedElement || !SAFE_SPLIT_TYPES.has(selectedElement.type)} onClick={startSplitSelected}>Split…</button>
            <button disabled={selectedIds.length < 2} onClick={mergeSelected}>Merge selected</button>
            {selectedIds.length > 0 && <span className="multi-selection-status">{selectedIds.length} selected</span>}
            {selectedIds.length > 1 && <label className="bulk-type-editor" title="Apply one semantic type to every selected region">
              <span>Type</span>
              <select value={commonSelectedType} onChange={(event: ChangeEvent<HTMLSelectElement>) => event.target.value && relabelSelected(event.target.value as CanonicalElementType)}>
                {!commonSelectedType && <option value="">Mixed types</option>}
                {STRUCTURE_FILTERS.filter((type): type is CanonicalElementType => type !== "all").map((type) => <option key={type} value={type} disabled={STRUCTURAL_PROMOTION_TYPES.has(type) && commonSelectedType !== type}>{labelType(type)}{STRUCTURAL_PROMOTION_TYPES.has(type) && commonSelectedType !== type ? " — not available here" : ""}</option>)}
              </select>
            </label>}
            <span className="multi-select-help">Shift/Ctrl/Cmd + click to add or remove regions.</span>
            <button disabled={!selectedIds.length} onClick={deleteSelected}>Suppress</button>
            <button disabled={!sessionOps.length} onClick={undo}>Undo</button>
            <button disabled={!redoOps.length} onClick={redo}>Redo</button>
          </div>
          <div className="sandbox-overlay-toggles">
            <label><input type="checkbox" checked={showBeforeOverlay} onChange={(event: ChangeEvent<HTMLInputElement>) => setShowBeforeOverlay(event.target.checked)} /> Before</label>
            <label><input type="checkbox" checked={showAfterOverlay} onChange={(event: ChangeEvent<HTMLInputElement>) => setShowAfterOverlay(event.target.checked)} /> After</label>
            <button className="panel-collapse-button" onClick={() => setElementsPanelCollapsed((value) => !value)}>{elementsPanelCollapsed ? "Show elements" : "Hide elements"}</button>
          </div>
        </div>}

        {editScope === "span" && <div className="span-correction-card">
          <div className="span-correction-head">
            <div>
              <span className="eyebrow">Exact Stage 3 evidence</span>
              <strong>Rebuild an element from selected text spans</strong>
              <small>Select the exact spans that belong together. The result text, bbox, and provenance are derived from those span IDs; Stage 3 remains immutable.</small>
            </div>
            <div className="correction-tools">
              <select value={spanResultType} onChange={(event: ChangeEvent<HTMLSelectElement>) => setSpanResultType(event.target.value as CanonicalElementType)} title="Semantic type for the span-built element">
                {STRUCTURE_FILTERS.filter((type): type is CanonicalElementType => type !== "all" && SAFE_SPAN_REBUILD_TYPES.has(type)).map((type) => <option key={type} value={type}>{labelType(type)}</option>)}
              </select>
              <button className="primary-button compact" disabled={!selectedSpanPayload || unsafeSpanOverlaps.length > 0} onClick={applySpanRebuild}>Apply span correction</button>
              <button disabled={!selectedSpanIds.length} onClick={() => setSelectedSpanIds([])}>Clear spans</button>
              <button disabled={!sessionOps.length} onClick={undo}>Undo</button>
              <button disabled={!redoOps.length} onClick={redo}>Redo</button>
            </div>
          </div>
          {!rawExtractionPage && <div className="warning-box">Stage 3 extraction for page {pageNumber} is unavailable, so span correction cannot be used.</div>}
          {rawExtractionPage && spanItems.length === 0 && <div className="warning-box">No text spans were extracted on this page.</div>}
          {rawExtractionPage && !hasPersistedSpanIds && <div className="info-box">Legacy Stage 3 artifact: span IDs are synthesized deterministically from block/line/span nesting. Re-running Stage 3 will persist stable line/span IDs, but it is not required for this review session.</div>}
          <div className="span-correction-summary">
            <div><span>Selected</span><strong>{selectedSpanIds.length} span{selectedSpanIds.length === 1 ? "" : "s"}</strong></div>
            <div><span>Will repartition</span><strong>{spanOverlappingElements.length} element{spanOverlappingElements.length === 1 ? "" : "s"} · {residualSourceSpanIds.length} residual span{residualSourceSpanIds.length === 1 ? "" : "s"} preserved</strong></div>
            <div><span>Derived bbox</span><code>{selectedSpanPayload ? selectedSpanPayload.bbox.map((value) => value.toFixed(1)).join(", ") : "—"}</code></div>
          </div>
          {selectedSpanPayload && <div className="span-text-preview"><span>Exact text preview</span><pre>{selectedSpanPayload.text || "(empty)"}</pre></div>}
          {spanOverlappingElements.length > 0 && <div className="span-overlap-list"><strong>Canonical elements repartitioned by this correction</strong>{spanOverlappingElements.map((element) => <code key={element.element_id}>{element.element_id} · {labelType(element.type)}</code>)}</div>}
          {unsafeSpanOverlaps.length > 0 && <div className="warning-box">The selected spans overlap record-bearing structure: {unsafeSpanOverlaps.map((element) => `${element.element_id} (${labelType(element.type)})`).join(", ")}. The generic span editor will not replace sections, clauses, tables, figures, titles, subtitles, or document metadata.</div>}
          <div className="info-box">Normal click selects one span. Shift/Ctrl/Cmd + click adds or removes spans. If the spans cover only part of an existing safe element, its unselected Stage 3 spans are preserved automatically as a residual element so text is never silently dropped.</div>
        </div>}



        {editScope === "layout" && selectedOnlyDefinitionTexts && !selectedElement && <div className="cross-page-correction-card definition-link-card simplified-definition-card bulk-definition-relation-card">
          <div className="cross-page-correction-head">
            <div>
              <span className="eyebrow">Required relation</span>
              <strong>Which definition do these {selectedDefinitionTexts.length} text elements belong to?</strong>
              <small>Apply one relationship correction to the whole selected group. The backend inherits the definition section and rebuilds membership automatically.</small>
            </div>
            <div className="correction-tools">
              <button className="primary-button compact" disabled={!(definitionSelectionId || commonSelectedDefinitionId)} onClick={assignSelectedDefinition}>Apply to {selectedDefinitionTexts.length}</button>
              <button disabled={!selectedDefinitionTexts.some((element) => Boolean(element.definition_entry_id))} onClick={unassignSelectedDefinition}>Clear relation</button>
            </div>
          </div>
          <div className="definition-entry-picker">
            <label>
              <span>Belongs to definition</span>
              <select value={definitionSelectionId || commonSelectedDefinitionId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setDefinitionSelectionId(event.target.value)}>
                <option value="">Select a DefinitionEntry…</option>
                {resolvedStructure.definitions.filter((entry) => Boolean(entry.term_element_id)).map((entry) => (
                  <option key={entry.definition_id} value={entry.definition_id}>{entry.term} · {entry.definition_id}{entry.section_id ? ` · ${entry.section_id}` : ""}</option>
                ))}
              </select>
            </label>
            <small>{selectedDefinitionTexts.length} definition text elements selected. One relationship correction will be applied to the whole group.</small>
          </div>
        </div>}

        {editScope === "layout" && comparison && <div className={`sandbox-diff ${comparison.matches ? "match" : "changed"}`}>
          <strong>{comparison.matches ? "After currently matches automatic Stage 4" : "Before and after differ"}</strong>
          <span>{comparison.unchanged} unchanged · {comparison.changed} changed · {comparison.added} added · {comparison.removed} removed</span>
        </div>}

        <div
          ref={reviewWorkspaceRef}
          className={`sandbox-edit-grid v2-review-workspace-grid ${elementsPanelCollapsed ? "elements-collapsed" : ""} compact-panel-${compactPanel ?? "none"} compact-view-${compactInspectorView}`}
        >
          {compactReview && compactPanel && <button type="button" className="v2-review-drawer-backdrop" aria-label="Close review panel" onClick={() => setCompactPanel(null)} />}
          {compactReview && compactPanel === "tree" && <button type="button" className="v2-review-panel-close tree" onClick={() => setCompactPanel(null)} aria-label="Close document tree">×</button>}
          <DocumentTree
            structure={previewStructure}
            selectedElementId={selectedElement?.element_id ?? selectedIds[0] ?? null}
            currentPage={pageNumber}
            onSelectElement={selectFromResolvedTree}
            onJumpContinuation={selectFromResolvedTree}
            title="Nearby page structure"
            subtitle={`Previous, current, and next page around p${pageNumber}; current-page nodes are emphasized.`}
            resolved
            collapsible
            scope="page-window"
          />

          <section className="sandbox-preview-card v2-review-preview-card">
            <div className="sandbox-card-head preview">
              <div><span className="eyebrow">Page {pageNumber}</span><strong>PDF + corrected overlays</strong></div>
              <div className="v2-review-preview-actions">
                <PageNav pageNumber={pageNumber} total={structure.pages.length} setPageNumber={safeSetPage} className="v2-review-page-nav" />
                <span className={showAfterOverlay ? "active" : ""}>Resolved overlay</span>
                <div className="v2-review-zoom-controls" role="group" aria-label="PDF zoom controls">
                  <button type="button" onClick={() => adjustReviewZoom(-0.15)} disabled={reviewZoomMode === "manual" && reviewZoom <= 0.5} aria-label="Zoom out">−</button>
                  <button type="button" className={reviewZoomMode === "fit" ? "active" : ""} onClick={fitReviewPage}>Fit</button>
                  {reviewZoomMode === "manual" && <output aria-live="polite">{reviewZoomPercent}%</output>}
                  <button type="button" onClick={() => adjustReviewZoom(0.15)} disabled={reviewZoomMode === "manual" && reviewZoom >= 2.5} aria-label="Zoom in">+</button>
                </div>
              </div>
            </div>
            {drawMode && <div className="draw-instruction">Draw mode: drag on empty page space to create a <strong>{labelType(drawType)}</strong> region.</div>}
            <div className="sandbox-preview-shell"><div
              className={`page-canvas ${reviewZoomMode === "manual" ? "review-zoom-manual" : "review-zoom-fit"}`}
              style={reviewZoomMode === "manual" ? { width: `${Math.round(reviewZoomBaseWidth * reviewZoom)}px`, maxWidth: "none" } : undefined}
            >
              <img src={pagePreviewUrl(document.document_id, pageNumber)} alt={`Correction sandbox page ${pageNumber}`} />
              <div className={`overlay-layer correction-layer ${drawMode ? "draw-mode" : ""}`} onPointerDown={startDraw} onPointerMove={moveDraw} onPointerUp={endDraw} onPointerCancel={cancelDraw}>
                {showBeforeOverlay && automaticPage.elements.map((element) => <SandboxOverlayBox key={`before-${element.element_id}`} item={{ id: element.element_id, type: element.type, bbox: element.bbox, text: element.text }} width={automaticPage.width} height={automaticPage.height} variant="baseline" />)}
                {showAfterOverlay && workingElements.map((element) => <EditableStructureOverlay key={`after-${element.element_id}`} element={element} width={basePage.width} height={basePage.height} selected={selectedIds.includes(element.element_id)} onSelect={(multi) => selectElement(element.element_id, multi)} onCommitBbox={(bbox) => commitBbox(element, bbox)} splitY={selectedIds.length === 1 && selectedIds[0] === element.element_id ? splitY : null} editable={editScope === "layout"} />)}
                {editScope === "span" && spanItems.map((item) => <SpanOverlayBox key={item.spanId} item={item} width={basePage.width} height={basePage.height} selected={selectedSpanIds.includes(item.spanId)} onSelect={(multi) => selectSpan(item.spanId, multi)} />)}
                {drawPreview && <div className="draw-preview" style={{ left: `${(drawPreview[0] / basePage.width) * 100}%`, top: `${(drawPreview[1] / basePage.height) * 100}%`, width: `${((drawPreview[2] - drawPreview[0]) / basePage.width) * 100}%`, height: `${((drawPreview[3] - drawPreview[1]) / basePage.height) * 100}%` }} />}
              </div>
            </div></div>
          </section>

          <aside className="v2-review-inspector-column">
            {compactReview && compactPanel === "inspector" && <button type="button" className="v2-review-panel-close inspector" onClick={() => setCompactPanel(null)} aria-label="Close correction inspector">×</button>}
        {editScope === "layout" && selectedElement && <div
          className={`selected-element-editor sandbox-selected-editor ${selectedEditorCollapsed ? "is-collapsed" : ""}`}
          onPointerDown={(event: ReactPointerEvent<HTMLDivElement>) => event.stopPropagation()}
          onClick={(event: ReactMouseEvent<HTMLDivElement>) => event.stopPropagation()}
        >
          <div className="selected-editor-head">
            <div><span className="eyebrow">Selected corrected region</span><strong>{selectedElement.element_id}</strong></div>
            <CollapseToggle collapsed={selectedEditorCollapsed} onToggle={() => setSelectedEditorCollapsed((value) => !value)} label="selected region editor" />
          </div>
          {!selectedEditorCollapsed && <>
            <label className="type-editor"><span>Semantic type</span><select value={selectedElement.type} onChange={(event: ChangeEvent<HTMLSelectElement>) => relabelSelected(event.target.value as CanonicalElementType)}>
              {STRUCTURE_FILTERS.filter((type): type is CanonicalElementType => type !== "all").map((type) => <option key={type} value={type} disabled={STRUCTURAL_PROMOTION_TYPES.has(type) && type !== selectedElement.type}>{labelType(type)}{STRUCTURAL_PROMOTION_TYPES.has(type) && type !== selectedElement.type ? " — not available here" : ""}</option>)}
            </select></label>
            {selectedElement.classification && <div className="semantic-classification-card">
              <div className="semantic-classification-head">
                <span>Automatic classification</span>
                <strong>{labelType(selectedElement.classification.selected_type)}</strong>
                <code>{Math.round(selectedElement.classification.confidence * 100)}%</code>
              </div>
              <small>Source: {selectedElement.classification.source}{selectedElement.layout_role ? ` · layout: ${selectedElement.layout_role}` : ""}</small>
              {selectedElement.classification.evidence.length > 0 && <ul>
                {selectedElement.classification.evidence.slice(0, 5).map((evidence) => <li key={evidence}>{evidence}</li>)}
              </ul>}
              {selectedElement.classification.alternatives.length > 0 && <div className="semantic-alternatives">
                <span>Alternatives</span>
                {selectedElement.classification.alternatives.slice(0, 3).map((alternative) => <code key={`${alternative.type}-${alternative.score}`}>{labelType(alternative.type)} {Math.round(alternative.score * 100)}%</code>)}
              </div>}
            </div>}
            <div className="v2-selected-text-preview"><span>Extracted text</span><p>{selectedElement.text || "(no text)"}</p></div>
            {selectedContinuationLinks.length > 0 && <div className="v2-selected-continuations">
              <span>Cross-page continuation</span>
              {selectedContinuationLinks.map(({ relation, outgoing, other }) => <button key={relation.relation_id} type="button" onClick={() => selectFromResolvedTree(other.element_id, other.page_number)}>
                {outgoing ? `Continues to page ${other.page_number} →` : `← Continued from page ${other.page_number}`}
              </button>)}
            </div>}
            <BboxEditor element={selectedElement} width={basePage.width} height={basePage.height} onApply={(bbox) => commitBbox(selectedElement, bbox)} />
            {splitY !== null && <div className="split-editor">
              <div><strong>Choose split position</strong><small>The split line is shown on the selected region. Move it until it sits between the two logical pieces.</small></div>
              <label><span>Y</span><input type="range" min={selectedElement.bbox[1] + 2} max={selectedElement.bbox[3] - 2} step="0.5" value={splitY} onChange={(event: ChangeEvent<HTMLInputElement>) => setSplitY(Number(event.target.value))} /><code>{splitY.toFixed(1)}</code></label>
              <div className="selected-editor-actions"><button className="primary-button compact" type="button" onClick={confirmSplitSelected}>Confirm split</button><button type="button" onClick={() => setSplitY(null)}>Cancel</button></div>
            </div>}
            <div className="selected-editor-actions">
              <button className="v2-suppress-region-button" type="button" onClick={deleteSelected}>Suppress region</button>
              {(selectedElement.type === "definition_term" || selectedElement.type === "definition_text") && <code>{selectedElement.definition_entry_id ?? "definition: unlinked"}</code>}
            </div>
            {selectedOnlyDefinitionTexts && <div className="selected-required-relation definition-link-card">
              <div className="selected-required-relation-head">
                <div>
                  <span className="eyebrow">Required relation</span>
                  <strong>Which definition does this text belong to?</strong>
                  <small>Select the DefinitionEntry. The backend sets <code>definition_entry_id</code>, inherits the section, and rebuilds membership automatically.</small>
                </div>
                <div className="correction-tools">
                  <button className="primary-button compact" disabled={!(definitionSelectionId || commonSelectedDefinitionId)} onClick={assignSelectedDefinition}>Apply relation</button>
                  <button disabled={!selectedDefinitionTexts.some((element) => Boolean(element.definition_entry_id))} onClick={unassignSelectedDefinition}>Clear relation</button>
                </div>
              </div>
              <div className="definition-entry-picker">
                <label>
                  <span>Belongs to definition</span>
                  <select value={definitionSelectionId || commonSelectedDefinitionId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setDefinitionSelectionId(event.target.value)}>
                    <option value="">Select a DefinitionEntry…</option>
                    {resolvedStructure.definitions.filter((entry) => Boolean(entry.term_element_id)).map((entry) => (
                      <option key={entry.definition_id} value={entry.definition_id}>{entry.term} · {entry.definition_id}{entry.section_id ? ` · ${entry.section_id}` : ""}</option>
                    ))}
                  </select>
                </label>
                <small>This relationship applies to the selected corrected region.</small>
              </div>
            </div>}
            <small>{selectedElement.type === "table" ? "Table editing is geometry-only here. Generic split, merge, draw-table, and structural promotion operations are disabled until their dedicated editors are implemented." : "Drag or resize visually, or enter exact bbox coordinates. Text is recalculated from immutable Stage 3 spans when corrections are saved. If the selected type requires a parent relation, the relevant selector appears below this region automatically."}</small>
          </>}
        </div>}

            {editScope === "layout" && !selectedElement && <div className="v2-empty-inspector">
              <span className="eyebrow">Correction inspector</span>
              <h3>Select a region</h3>
              <p>Click a PDF region or a node in the resolved document tree. Semantic type, geometry, and required relationships will appear here.</p>
            </div>}

            {(!elementsPanelCollapsed || compactReview) && <section className="sandbox-elements-card v2-review-elements-card">
              {editScope === "span" ? <>
                <div className="sandbox-card-head"><div><span className="eyebrow">Stage 3 evidence</span><strong>Text spans</strong></div><span className="count-badge">{spanItems.length}</span></div>
                <div className="inspector-list sandbox-elements-list span-list">
                  {spanItems.map((item) => <button type="button" key={item.spanId} className={`span-list-row ${selectedSpanIds.includes(item.spanId) ? "active" : ""}`} onClick={(event: ReactMouseEvent<HTMLButtonElement>) => selectSpan(item.spanId, event.shiftKey || event.ctrlKey || event.metaKey)}>
                    <span><strong>{item.text.trim() || "(whitespace)"}</strong><small>{item.spanId} · {item.font || "font ?"} · {item.size?.toFixed(1) ?? "?"} pt</small></span>
                  </button>)}
                  {spanItems.length === 0 && <p className="empty-copy">No Stage 3 text spans on this page.</p>}
                </div>
              </> : <>
                <div className="sandbox-card-head"><div><span className="eyebrow">Page elements</span><strong>Corrected regions</strong></div><span className="count-badge">{workingElements.length}</span></div>
                <div className="structure-filter-wrap"><select value={filter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setFilter(event.target.value as "all" | CanonicalElementType)}>
                  {STRUCTURE_FILTERS.map((type) => <option key={type} value={type}>{labelType(type)}</option>)}
                </select></div>
                <div className="inspector-list sandbox-elements-list">
                  {filteredWorking.map((element) => <StructureElementCard key={element.element_id} element={element} active={selectedIds.includes(element.element_id)} onClick={(event) => selectElement(element.element_id, event.shiftKey || event.ctrlKey || event.metaKey)} />)}
                  {filteredWorking.length === 0 && <p className="empty-copy">No matching corrected elements.</p>}
                </div>
              </>}
            </section>}
          </aside>
        </div>

        {compactReview && <nav className="v2-review-mobile-dock" aria-label="Review workspace panels">
          <button type="button" className={compactPanel === "tree" ? "active" : ""} onClick={() => setCompactPanel((panel) => panel === "tree" ? null : "tree")}>
            <span aria-hidden="true">☷</span><strong>Tree</strong>
          </button>
          <button type="button" className={compactPanel === null ? "active" : ""} onClick={() => setCompactPanel(null)}>
            <span aria-hidden="true">▣</span><strong>PDF</strong>
          </button>
          <button type="button" className={compactPanel === "inspector" && compactInspectorView === "correct" ? "active" : ""} disabled={!selectedElement && editScope === "layout"} onClick={() => { setCompactInspectorView("correct"); setCompactPanel("inspector"); }}>
            <span aria-hidden="true">✎</span><strong>Correct</strong>
          </button>
          <button type="button" className={compactPanel === "inspector" && compactInspectorView === "page" ? "active" : ""} onClick={() => { setCompactInspectorView("page"); setCompactPanel("inspector"); }}>
            <span aria-hidden="true">≡</span><strong>Page</strong>
          </button>
        </nav>}
      </>}

      {mode === "before" && beforePayload && <div className="before-after-json-card">
        <div className="json-explainer"><strong>Before</strong><span>Immutable automatic Stage 4 page JSON. This is never modified by human review.</span></div>
        <PageJsonPanel payload={beforePayload} filename={`${document.document_id}-stage4-before-page-${pageNumber}.json`} />
      </div>}

      {mode === "after" && afterPayload && <div className="before-after-json-card">
        <div className="json-explainer"><strong>After</strong><span>Live Stage 4.5 preview: saved corrections plus the current unsaved session. The backend performs the same safety validation and final canonical integrity reconciliation when you save.</span></div>
        <PageJsonPanel payload={afterPayload} filename={`${document.document_id}-stage45-after-page-${pageNumber}.json`} />
      </div>}

      {mode === "log" && <div className="before-after-json-card">
        <CorrectionsPanel saved={savedOperations} session={sessionOps} pageNumber={pageNumber} documentId={document.document_id} />
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
  chunking,
  embeddingStatus,
  onEmbeddingStatusChange,
  onRunExtraction,
  onRunStructure,
  onSaveCorrections,
  onResetAllCorrections,
  onGenerateChunks,
  onResetChunks,
  extracting,
  structuring,
  savingCorrections,
  generatingChunks,
}: {
  document: DocumentRecord;
  extraction: DocumentExtraction | null;
  structure: StructuredDocument | null;
  resolved: ResolvedStructureArtifact | null;
  corrections: CorrectionArtifact | null;
  layout: LayoutArtifact | null;
  chunking: ChunkingArtifact | null;
  embeddingStatus: EmbeddingStatus | null;
  onEmbeddingStatusChange: (status: EmbeddingStatus | null) => void;
  onRunExtraction: () => void;
  onRunStructure: () => void;
  onSaveCorrections: (operations: CorrectionOperation[]) => Promise<void>;
  onResetAllCorrections: () => Promise<void>;
  onGenerateChunks: (config: ChunkingConfig) => Promise<void>;
  onResetChunks: () => Promise<void>;
  extracting: boolean;
  structuring: boolean;
  savingCorrections: boolean;
  generatingChunks: boolean;
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

  const reviewDone = Boolean(resolved && resolved.integrity.status === "pass");

  return (
    <div className="workspace v2-workspace">
      <header className="workspace-header v2-workspace-header">
        <div className="v2-document-heading">
          <span className="file-label">PDF</span>
          <div>
            <h1>{document.original_filename}</h1>
            <p>{document.classification.page_count ?? availablePageCount} pages · {document.classification.pdf_type ?? "PDF"} · {document.document_id}</p>
          </div>
        </div>
        <div className="header-actions v2-header-actions">
          {resolved && <span className={`v2-integrity-pill ${resolved.integrity.status}`}>Integrity {resolved.integrity.status}</span>}
          {document.classification.document_family === "pdf" && <a className="secondary-button" href={rawFileUrl(document.document_id)} target="_blank" rel="noreferrer">Open original ↗</a>}
          <button className="secondary-button" disabled={!canExtract || extracting || structuring} onClick={onRunExtraction}>
            {extracting ? "Extracting…" : extraction ? "Re-extract document" : "Extract document"}
          </button>
          <button className="primary-button compact" disabled={!canStructure || extracting || structuring} onClick={onRunStructure}>
            {structuring ? "Structuring…" : structure ? "Rebuild structure" : "Build structure"}
          </button>
        </div>
      </header>

      <div className="v2-workflow-shell">
        <DocumentWorkflowNav
          tab={tab}
          extractionReady={Boolean(extraction)}
          structureReady={Boolean(structure)}
          reviewReady={Boolean(structure)}
          reviewDone={reviewDone}
          chunkingAvailable={Boolean(structure)}
          chunkingDone={Boolean(chunking)}
          indexAvailable={Boolean(chunking)}
          indexDone={Boolean(embeddingStatus?.complete)}
          onChange={setTab}
        />
        <div className="v2-advanced-nav" aria-label="Technical document views">
          <span>Technical</span>
          <button type="button" className={tab === "layout" ? "active" : ""} disabled={!extraction && !structure} onClick={() => setTab("layout")}>Layout details</button>
          <button type="button" className={tab === "json" ? "active" : ""} disabled={!extraction && !structure} onClick={() => setTab("json")}>Raw data</button>
        </div>
      </div>

      {!canExtract && document.validation_status === "valid" && (
        <div className="notice-bar">This build supports PDF extraction only. Other uploaded formats are stored and classified but do not enter the extraction and structure workflow.</div>
      )}
      {document.extraction_status === "completed" && !structure && (
        <div className="stage-ready-banner"><strong>Structure is ready to run.</strong><span>Stage 3 extraction is complete. Build structure to reconstruct canonical document structure.</span></div>
      )}

      <div className="workspace-body v2-workspace-body">
        {tab === "overview" && <OverviewPage document={document} extraction={extraction} structure={structure} resolved={resolved} corrections={corrections} chunking={chunking} embeddingStatus={embeddingStatus} />}
        {tab === "extraction" && extraction && <ExtractionWorkspace document={document} extraction={extraction} pageNumber={pageNumber} setPageNumber={setPageNumber} />}
        {tab === "extraction" && !extraction && <div className="v2-placeholder-page"><h2>Extraction is not available yet</h2><p>Extract document to inspect raw blocks, tables, spans, and page coordinates.</p></div>}
        {tab === "layout" && <LayoutWorkspace document={document} extraction={extraction} structure={structure} resolved={resolved} pageNumber={pageNumber} setPageNumber={setPageNumber} />}
        {tab === "structure" && structure && <StructureWorkspace
          document={document}
          automaticStructure={structure}
          resolved={resolved}
          pageNumber={pageNumber}
          setPageNumber={setPageNumber}
          onOpenCorrectionSandbox={() => setTab("review")}
        />}
        {tab === "structure" && !structure && <div className="v2-placeholder-page"><h2>Structure is not available yet</h2><p>Build structure after extraction to inspect the canonical hierarchy and document tree.</p></div>}
        {tab === "review" && <CorrectionSandbox
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
        {tab === "chunking" && <ChunkingPage
          document={document}
          resolved={resolved}
          artifact={chunking}
          generating={generatingChunks}
          onGenerate={onGenerateChunks}
          onReset={onResetChunks}
          onOpenReview={(targetPage) => { setPageNumber(targetPage); setTab("review"); }}
        />}
        {tab === "index" && <IndexPage
          document={document}
          chunking={chunking}
          status={embeddingStatus}
          onStatusChange={onEmbeddingStatusChange}
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
  const [chunking, setChunking] = useState<ChunkingArtifact | null>(null);
  const [embeddingStatus, setEmbeddingStatus] = useState<EmbeddingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [documentLoading, setDocumentLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [structuring, setStructuring] = useState(false);
  const [savingCorrections, setSavingCorrections] = useState(false);
  const [generatingChunks, setGeneratingChunks] = useState(false);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<DocumentRecord | null>(null);
  const [deletingDocument, setDeletingDocument] = useState(false);
  const viewportMode = useViewportMode();
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
    let cancelled = false;
    if (!selectedId) {
      setDocumentLoading(false);
      setSelected(null);
      setExtraction(null);
      setStructure(null);
      setResolved(null);
      setCorrections(null);
      setLayout(null);
      setChunking(null);
      setEmbeddingStatus(null);
      return () => { cancelled = true; };
    }

    setDocumentLoading(true);
    setError("");
    setSelected(null);
    setExtraction(null);
    setStructure(null);
    setResolved(null);
    setCorrections(null);
    setLayout(null);
    setChunking(null);
    setEmbeddingStatus(null);

    Promise.all([
      getDocument(selectedId),
      getExtraction(selectedId),
      getStructure(selectedId),
      getResolvedStructure(selectedId),
      getCorrections(selectedId),
      getLayout(selectedId),
      getChunks(selectedId),
    ])
      .then(([doc, raw, structured, resolvedArtifact, correctionArtifact, layoutArtifact, chunkingArtifact]) => {
        if (cancelled) return;
        setSelected(doc);
        setExtraction(raw);
        setStructure(structured);
        setResolved(resolvedArtifact);
        setCorrections(correctionArtifact);
        setLayout(layoutArtifact);
        setChunking(chunkingArtifact);
        if (chunkingArtifact) {
          getEmbeddingStatus(selectedId)
            .then((next) => { if (!cancelled) setEmbeddingStatus(next); })
            .catch(() => { if (!cancelled) setEmbeddingStatus(null); });
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load document");
      })
      .finally(() => {
        if (!cancelled) setDocumentLoading(false);
      });

    return () => { cancelled = true; };
  }, [selectedId]);

  function updateRecord(updated: DocumentRecord) {
    setSelected(updated);
    setDocuments((items) => items.map((item) => item.document_id === updated.document_id ? updated : item));
  }

  async function handleUploaded(record: DocumentRecord) {
    setDocuments((items) => [record, ...items]);
    setSelectedId(record.document_id);
  }

  async function handleConfirmDeleteDocument() {
    if (!deleteTarget || deletingDocument) return;
    const deletingId = deleteTarget.document_id;
    setDeletingDocument(true);
    setError("");
    try {
      await deleteDocument(deletingId);
      const rows = documents.filter((item) => item.document_id !== deletingId);
      setDocuments(rows);
      if (selectedId === deletingId || !rows.some((item) => item.document_id === selectedId)) {
        setSelectedId(rows[0]?.document_id ?? null);
      }
      setDeleteTarget(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deleting document failed");
    } finally {
      setDeletingDocument(false);
    }
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
      setChunking(null);
      setEmbeddingStatus(null);
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
      setChunking(null);
      setEmbeddingStatus(null);
      updateRecord(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Structure reconstruction failed");
      setStructure(null);
      setResolved(null);
      setCorrections(null);
      setLayout(null);
      setChunking(null);
      setEmbeddingStatus(null);
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
      setChunking(null);
      setEmbeddingStatus(null);
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
      setChunking(null);
      setEmbeddingStatus(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resetting corrections failed");
      throw e;
    } finally {
      setSavingCorrections(false);
    }
  }

  async function handleGenerateChunks(config: ChunkingConfig) {
    if (!selected) return;
    setGeneratingChunks(true);
    setError("");
    try {
      const artifact = await generateChunks(selected.document_id, config);
      setChunking(artifact);
      setEmbeddingStatus(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stage 5 chunking failed");
      throw e;
    } finally {
      setGeneratingChunks(false);
    }
  }

  async function handleResetChunks() {
    if (!selected) return;
    setGeneratingChunks(true);
    setError("");
    try {
      await resetChunks(selected.document_id);
      setChunking(null);
      setEmbeddingStatus(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resetting Stage 5 chunks failed");
      throw e;
    } finally {
      setGeneratingChunks(false);
    }
  }

  const effectiveSidebarCollapsed = viewportMode === "large" ? sidebarCollapsed : true;

  return (
    <div className={`app-shell ${effectiveSidebarCollapsed ? "sidebar-collapsed" : ""} viewport-${viewportMode}`} data-viewport-mode={viewportMode}>
      <V2DocumentSidebar
        documents={documents}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onUploaded={handleUploaded}
        onDelete={setDeleteTarget}
        collapsed={effectiveSidebarCollapsed}
        onToggleCollapsed={() => {
          if (viewportMode === "large") setSidebarCollapsed((value) => !value);
        }}
      />
      <main className="main-area">
        <CompactDocumentBar documents={documents} selectedId={selectedId} onSelect={setSelectedId} onUploaded={handleUploaded} onDelete={setDeleteTarget} />
        {error && <div className="global-error"><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
        {loading ? (
          <div className="empty-state"><div className="spinner" />Loading workspace…</div>
        ) : documentLoading ? (
          <div className="empty-state"><div className="spinner" />Loading selected document…</div>
        ) : selected ? (
          <Workspace
            document={selected}
            extraction={extraction}
            structure={structure}
            resolved={resolved}
            corrections={corrections}
            layout={layout}
            chunking={chunking}
            embeddingStatus={embeddingStatus}
            onEmbeddingStatusChange={setEmbeddingStatus}
            onRunExtraction={handleRunExtraction}
            onRunStructure={handleRunStructure}
            onSaveCorrections={handleSaveCorrections}
            onResetAllCorrections={handleResetAllCorrections}
            onGenerateChunks={handleGenerateChunks}
            onResetChunks={handleResetChunks}
            extracting={extracting}
            structuring={structuring}
            savingCorrections={savingCorrections}
            generatingChunks={generatingChunks}
          />
        ) : (
          <div className="welcome-state">
            <div className="welcome-mark">RW</div>
            <h1>Document Studio</h1>
            <p>Upload a PDF, review what was extracted, correct the document structure, prepare searchable knowledge, and inspect exactly what enters retrieval.</p>
          </div>
        )}
      </main>
      {deleteTarget && <div className="v2-delete-backdrop" role="presentation" onMouseDown={() => !deletingDocument && setDeleteTarget(null)}>
        <section className="v2-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-document-title" onMouseDown={(event) => event.stopPropagation()}>
          <span className="eyebrow">Permanent action</span>
          <h2 id="delete-document-title">Delete document?</h2>
          <p><strong>{deleteTarget.original_filename}</strong></p>
          <p>This removes the uploaded PDF and all runtime data owned by it:</p>
          <ul><li>Extraction, layout, structure, corrections, and resolved artifacts</li><li>Semantic chunks and embeddings</li><li>Document-specific retrieval experiment runs and generated database results</li></ul>
          <p className="v2-delete-note">Curated golden specs and DEV / HELD-OUT evaluation files are kept.</p>
          <div className="v2-delete-actions"><button type="button" disabled={deletingDocument} onClick={() => setDeleteTarget(null)}>Cancel</button><button type="button" className="primary-button danger" disabled={deletingDocument} onClick={() => void handleConfirmDeleteDocument()}>{deletingDocument ? "Deleting…" : "Delete permanently"}</button></div>
        </section>
      </div>}
    </div>
  );
}
