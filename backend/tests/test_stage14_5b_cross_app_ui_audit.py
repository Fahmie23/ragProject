from __future__ import annotations

from pathlib import Path

from tests._frontend_contract_utils import read_css_bundle

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SHELL = REPO_ROOT / "frontend" / "src" / "app" / "RagWorkbenchShell.tsx"
WORKBENCH = REPO_ROOT / "frontend" / "src" / "features" / "workbench" / "WorkbenchApp.tsx"
SIDEBAR = REPO_ROOT / "frontend" / "src" / "components" / "layout" / "DocumentSidebar.tsx"
STYLES = REPO_ROOT / "frontend" / "src" / "styles.css"


def test_stage14_5b_global_navigation_exposes_current_page_semantics() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'aria-current={active === item.id ? "page" : undefined}' in text
    assert 'aria-label="RAG Document Studio"' in text


def test_stage14_5b_playground_distinguishes_document_loading_failure_from_empty_library() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert "documentsLoading" in text
    assert "documentsLoadError" in text
    assert "loadPlaygroundDocuments" in text
    assert "Retry documents" in text
    assert '!documentsLoading && !documentsLoadError && !hasDocuments' in text


def test_stage14_5b_citation_drawer_restores_focus_and_keeps_escape_close() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert "citationReturnFocusRef" in text
    assert "provenanceCloseRef.current?.focus();" in text
    assert "window.requestAnimationFrame(() => citationReturnFocusRef.current?.focus())" in text
    assert 'role="dialog" aria-modal="false"' in text
    assert 'if (event.key === "Escape") closeCitation();' in text


def test_stage14_5b_benchmark_detail_aborts_stale_requests_and_restores_focus() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert "detailRequestRef.current?.abort();" in text
    assert "const controller = new AbortController();" in text
    assert "controller.signal" in text
    assert "benchmarkReturnFocusRef" in text
    assert "benchmarkCloseRef.current?.focus();" in text
    assert "Retry benchmark" in text
    assert 'if (event.key === "Escape") closeEvaluationQuestion();' in text


def test_stage14_5b_document_switch_cannot_render_stale_document_payload() -> None:
    text = WORKBENCH.read_text(encoding="utf-8")
    assert "const [documentLoading, setDocumentLoading] = useState(false);" in text
    assert "let cancelled = false;" in text
    assert "if (cancelled) return;" in text
    assert "if (!cancelled) setEmbeddingStatus(next);" in text
    assert "return () => { cancelled = true; };" in text
    assert "Loading selected document…" in text


def test_stage14_5b_document_shell_sticky_and_upload_accessibility_are_scoped() -> None:
    css = read_css_bundle(STYLES)
    sidebar = SIDEBAR.read_text(encoding="utf-8")
    assert ".rag-documents-host .sidebar.v2-sidebar" in css
    assert "top: 68px;" in css
    assert ".rag-documents-host .v2-compact-document-bar { position: static; }" in css
    assert ".rag-documents-host .global-error" in css
    assert ".v2-upload-button input" in css
    assert "display: block;" in css.rsplit(".v2-upload-button input {", 1)[1].split("}", 1)[0]
    assert ".v2-upload-button:focus-within" in css
    assert 'disabled={documents.length === 0}' in sidebar
    assert "No documents loaded" in sidebar


def test_stage14_5b_focus_visible_is_consistent_across_shell_and_document_workbench() -> None:
    css = read_css_bundle(STYLES)
    assert '.rag-global-shell :where(button,a,input,select,textarea,summary,[tabindex]):focus-visible' in css
    assert '.rag-documents-host :where(button,a,input,select,textarea,summary,[tabindex]):focus-visible' in css
