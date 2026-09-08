from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "frontend" / "src" / "app" / "RagWorkbenchShell.tsx"
API = ROOT / "frontend" / "src" / "api.ts"
TYPES = ROOT / "frontend" / "src" / "types.ts"
RAG_CSS = ROOT / "frontend" / "src" / "styles" / "rag-shell.css"
DOCUMENTS_ROUTER = ROOT / "backend" / "app" / "routers" / "documents.py"


def test_search_and_ask_renders_visual_evidence_for_answers_and_retrieval() -> None:
    shell = SHELL.read_text(encoding="utf-8")
    assert "function SourceVisualEvidence" in shell
    assert "visualRefs={evidence.visual_refs}" in shell
    assert "visualRefs={hit.visual_refs}" in shell
    assert 'aria-label="Related visual evidence"' in shell
    assert "View highlighted page" in shell


def test_frontend_has_visual_reference_contract_and_preview_url() -> None:
    types = TYPES.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    assert "export interface VisualReference" in types
    assert "visual_refs?: VisualReference[]" in types
    assert "export function visualPreviewUrl" in api
    assert "/visuals/${assetType}/${encodeURIComponent(visualId)}/preview" in api


def test_visual_preview_endpoint_and_source_card_styles_exist() -> None:
    router = DOCUMENTS_ROUTER.read_text(encoding="utf-8")
    css = RAG_CSS.read_text(encoding="utf-8")
    assert '@router.get("/{document_id}/visuals/{asset_type}/{visual_id}/preview")' in router
    assert 'view: str = Query(default="crop", pattern="^(crop|page)$")' in router
    assert ".rag-source-visual-list" in css
    assert ".rag-source-visual-preview img" in css
    assert ".rag-source-visual-page-link" in css


def test_cited_answer_promotes_only_strong_related_visual_evidence_inline() -> None:
    shell = SHELL.read_text(encoding="utf-8")
    css = RAG_CSS.read_text(encoding="utf-8")
    assert "function choosePromotedAnswerVisual" in shell
    assert '"nearby_explicit_reference"' in shell
    assert 'visual.confidence >= 0.78' in shell
    assert '"figure_source"' not in shell.split("const INLINE_VISUAL_RELATIONS", 1)[1].split("]);", 1)[0]
    assert "Relevant visual from source {citation.marker}" in shell
    assert "The answer is generated from cited text; this visual is shown as related source evidence." in shell
    assert "promotedAnswerVisual && <PromotedAnswerVisualCard" in shell
    assert "visualRefs={evidence.visual_refs}" in shell  # complete source evidence remains on the right
    assert ".rag-answer-inline-visual" in css
    assert ".rag-answer-inline-visual-preview img" in css


def test_inline_visual_can_focus_its_matching_validated_source_without_opening_provenance() -> None:
    shell = SHELL.read_text(encoding="utf-8")
    assert "function focusCitationSource(citationId: string)" in shell
    assert 'document.getElementById(`rag-source-${citationId}`)' in shell
    assert 'source.focus({ preventScroll: true })' in shell
    assert "onShowSource={focusCitationSource}" in shell
    assert "tabIndex={-1}" in shell
