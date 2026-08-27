import { useEffect, useMemo, useState } from "react";
import type { StructuredDocument } from "../../types";
import { buildDocumentTree, filterDocumentTreeForPage, filterDocumentTreeForPageWindow, type DocumentTreeNode } from "../../utils/documentTree";

function labelType(value: string) {
  return value.replace(/_/g, " ");
}

function TreeNode({
  node,
  depth,
  selectedElementId,
  currentPage,
  onSelectElement,
  onJumpContinuation,
}: {
  node: DocumentTreeNode;
  depth: number;
  selectedElementId: string | null;
  currentPage: number;
  onSelectElement: (elementId: string, pageNumber: number) => void;
  onJumpContinuation: (elementId: string, pageNumber: number) => void;
}) {
  const hasChildren = node.children.length > 0;
  const [open, setOpen] = useState(depth < 2 || Boolean(node.children.some((child) => child.id === selectedElementId)));
  const active = node.id === selectedElementId;
  const onCurrentPage = node.pageNumber === currentPage;
  const contextOnly = Boolean(node.contextOnly);

  useEffect(() => {
    if (active || node.children.some((child) => child.id === selectedElementId)) setOpen(true);
  }, [active, selectedElementId, node.children]);

  if (node.kind === "document") {
    return (
      <div className="document-tree-root">
        {node.children.map((child) => (
          <TreeNode
            key={child.id}
            node={child}
            depth={0}
            selectedElementId={selectedElementId}
            currentPage={currentPage}
            onSelectElement={onSelectElement}
            onJumpContinuation={onJumpContinuation}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="document-tree-node">
      <div className={`document-tree-row ${active ? "active" : ""} ${onCurrentPage ? "on-page" : ""} ${contextOnly ? "context-only" : ""}`} style={{ paddingLeft: 10 + depth * 15 }}>
        <button
          type="button"
          className="document-tree-caret"
          onClick={() => hasChildren && setOpen((value) => !value)}
          disabled={!hasChildren}
          aria-label={hasChildren ? `${open ? "Collapse" : "Expand"} ${node.label}` : undefined}
        >
          {hasChildren ? (open ? "▾" : "▸") : "·"}
        </button>
        <button
          type="button"
          className="document-tree-select"
          onClick={() => node.pageNumber && onSelectElement(node.id, node.pageNumber)}
          title={node.element?.text || node.label}
        >
          <span className="document-tree-label">{node.label}</span>
          <span className="document-tree-meta"><em>{contextOnly ? `${labelType(node.type)} · context` : labelType(node.type)}</em>{node.pageNumber ? <b>p{node.pageNumber}</b> : null}</span>
        </button>
      </div>

      {node.continuations.map((continuation) => (
        <div key={`${node.id}-${continuation.relationId}-${continuation.direction}`} className="document-tree-continuation" style={{ marginLeft: 30 + depth * 15 }}>
          <span className="document-tree-page-break"><i /> page break <i /></span>
          <button type="button" onClick={() => onJumpContinuation(continuation.elementId, continuation.pageNumber)}>
            <span aria-hidden="true">{continuation.direction === "outgoing" ? "↳" : "↰"}</span>
            {continuation.direction === "outgoing" ? `continues on page ${continuation.pageNumber}` : `continued from page ${continuation.pageNumber}`}
            <strong>{continuation.direction === "outgoing" ? "→" : "←"}</strong>
          </button>
        </div>
      ))}

      {open && hasChildren && (
        <div className="document-tree-children">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedElementId={selectedElementId}
              currentPage={currentPage}
              onSelectElement={onSelectElement}
              onJumpContinuation={onJumpContinuation}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function DocumentTree({
  structure,
  selectedElementId,
  currentPage,
  onSelectElement,
  onJumpContinuation,
  title = "Document tree",
  subtitle,
  resolved = false,
  collapsible = false,
  scope = "document",
  scopeToggle,
}: {
  structure: StructuredDocument;
  selectedElementId: string | null;
  currentPage: number;
  onSelectElement: (elementId: string, pageNumber: number) => void;
  onJumpContinuation: (elementId: string, pageNumber: number) => void;
  title?: string;
  subtitle?: string;
  resolved?: boolean;
  collapsible?: boolean;
  scope?: "document" | "page" | "page-window";
  scopeToggle?: {
    value: "document" | "page-window";
    onChange: (value: "document" | "page-window") => void;
  };
}) {
  const fullTree = useMemo(() => buildDocumentTree(structure), [structure]);
  const tree = useMemo(() => {
    if (scope === "page") return filterDocumentTreeForPage(fullTree, currentPage);
    if (scope === "page-window") return filterDocumentTreeForPageWindow(fullTree, currentPage);
    return fullTree;
  }, [fullTree, currentPage, scope]);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <section className={`document-tree-panel ${resolved ? "resolved" : "automatic"} ${collapsed ? "collapsed" : ""}`}>
      <div className="document-tree-head">
        <div>
          <span className="eyebrow">{resolved ? "Resolved structure" : "Canonical structure"}</span>
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="document-tree-head-actions">
          {scopeToggle && !collapsed && <div className="document-tree-scope-toggle" role="group" aria-label="Document tree scope">
            <button type="button" className={scopeToggle.value === "page-window" ? "active" : ""} onClick={() => scopeToggle.onChange("page-window")}>Nearby</button>
            <button type="button" className={scopeToggle.value === "document" ? "active" : ""} onClick={() => scopeToggle.onChange("document")}>Full</button>
          </div>}
          {collapsible && <button type="button" className="document-tree-collapse" onClick={() => setCollapsed((value) => !value)}>{collapsed ? "→" : "←"}</button>}
        </div>
      </div>
      {!collapsed && scope === "page-window" && <div className="document-tree-window-note">
        <span>{currentPage > 1 ? `p${currentPage - 1}` : "start"}</span>
        <strong>p{currentPage} current</strong>
        <span>{currentPage < structure.pages.length ? `p${currentPage + 1}` : "end"}</span>
      </div>}
      {!collapsed && <div className="document-tree-scroll">{scope !== "document" && tree.children.length === 0 ? <p className="document-tree-empty">No canonical elements around page {currentPage}.</p> : <TreeNode node={tree} depth={0} selectedElementId={selectedElementId} currentPage={currentPage} onSelectElement={onSelectElement} onJumpContinuation={onJumpContinuation} />}</div>}
    </section>
  );
}
