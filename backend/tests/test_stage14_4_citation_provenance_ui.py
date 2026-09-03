from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SHELL = REPO_ROOT / "frontend" / "src" / "app" / "RagWorkbenchShell.tsx"
STYLES = REPO_ROOT / "frontend" / "src" / "styles.css"


def test_stage14_4_contract_keeps_live_provenance_backend_owned_and_nonsemantic() -> None:
    payload = TestClient(app).get("/api/playground/contract").json()
    inspection = payload["citation_inspection"]
    assert inspection["stage"] == "Stage 14.4"
    assert inspection["additional_backend_call_required"] is False
    assert inspection["deterministic_validation_available_live"] is True
    assert inspection["semantic_entailment_available_live"] is False
    assert inspection["semantic_entailment_scope"] == "Frozen Stage 11 Evaluation view only."


def test_stage14_4_inline_citation_is_primary_provenance_entrypoint() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert "activeCitationId" in text
    assert "onCitationSelect(citation.citation_id, event.currentTarget)" in text
    assert 'className="rag-answer-citation-link"' in text
    assert 'data-active={activeCitationId === citation.citation_id ? "true" : "false"}' in text
    assert 'onCitationSelect={openCitation}' in text
    assert 'className="rag-provenance-drawer"' in text


def test_stage14_4_validated_source_does_not_duplicate_provenance_action() -> None:
    text = SHELL.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    assert "Inspect provenance" not in text
    assert 'className="rag-source-evidence-disclosure"' in text
    assert "Show full evidence" in text
    assert "Open source PDF →" in text
    assert "rag-source-actions" not in text
    assert ".rag-provenance-open" not in css


def test_stage14_4_drawer_uses_existing_claim_evidence_locator_and_pdf_facts() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert "const selectedCitationEvidence = selectedCitation ? evidenceById.get(selectedCitation.evidence_id)" in text
    assert "claim.citation_ids.includes(selectedCitation.citation_id)" in text
    assert "selectedCitation.locators.map((locator" in text
    assert "locator.source_element_ids.map((elementId)" in text
    assert "selectedCitationEvidence.content_text" in text
    assert "rawFileUrl(generatedAnswer.document_id)" in text


def test_stage14_4_deep_provenance_is_progressively_disclosed() -> None:
    text = SHELL.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    assert 'className="rag-provenance-chain-disclosure"' in text
    assert "Show provenance chain" in text
    assert "Frozen Stage 5 chunk" in text
    assert "Canonical locators" in text
    assert ".rag-provenance-chain-disclosure > summary" in css
    assert '.rag-provenance-chain-disclosure[open] > summary::after' in css


def test_stage14_4_live_ui_explicitly_does_not_claim_semantic_entailment() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert "It is not a live semantic-entailment score." in text
    assert "Human semantic-entailment labels are shown only in the frozen Stage 11 Evaluation view." in text
    assert "✓ Deterministic citation valid" in text


def test_stage14_4_provenance_can_close_by_button_or_escape_and_resets_with_outputs() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'if (event.key === "Escape") closeCitation();' in text
    assert 'ref={provenanceCloseRef}' in text
    assert 'aria-label="Close citation provenance"' in text
    assert "setSelectedCitationId(null);" in text
    assert "Citation details" in text


def test_stage14_4_drawer_is_bounded_responsive_and_keeps_main_answer_visible() -> None:
    css = STYLES.read_text(encoding="utf-8")
    assert "Stage 14.4 — deterministic citation provenance drawer" in css
    drawer = css.split(".rag-provenance-drawer {", 1)[1].split("}", 1)[0]
    assert "position: fixed;" in drawer
    assert "overflow-y: auto;" in drawer
    assert "overscroll-behavior: contain;" in drawer
    assert "width: min(450px, calc(100vw - 32px));" in drawer
    assert ".rag-provenance-drawer-head" in css
    assert ".rag-provenance-chain" in css
    assert ".rag-provenance-locator-list" in css
    assert "@media (max-width: 620px)" in css
