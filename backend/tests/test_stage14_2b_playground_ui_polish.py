from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SHELL = REPO_ROOT / "frontend" / "src" / "app" / "RagWorkbenchShell.tsx"
STYLES = REPO_ROOT / "frontend" / "src" / "styles.css"


def test_stage14_2b_keeps_answer_primary_and_moves_detail_into_inspector() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'type AnswerInspectorTab = "claims" | "context" | "technical";' in text
    assert 'className="rag-answer-facts"' in text
    assert 'rag-answer-inspector' in text
    assert '>Claims</button>' in text
    assert '>Context</button>' in text
    assert '>Technical</button>' in text


def test_stage14_2b_exposes_pipeline_counts_without_quality_score_invention() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert '{generatedAnswer.claims.length}</strong><span>claims</span>' in text
    assert '{generatedAnswer.context_chunk_count}</strong><span>context chunks</span>' in text
    assert '{generatedAnswer.used_evidence_ids.length}</strong><span>used evidence</span>' in text
    assert '{generatedAnswer.citations.length}</strong><span>validated sources</span>' in text
    assert 'answer-quality probabilities' in text


def test_stage14_2b_claim_inspector_preserves_backend_owned_provenance_links() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'Generated claims retain their request-local evidence IDs and deterministic citation links.' in text
    assert 'claim.citation_ids.map((citationId)' in text
    assert 'citationById.get(citationId)' in text
    assert 'rawFileUrl(generatedAnswer.document_id)' in text


def test_stage14_2b_context_inspector_distinguishes_used_from_available_evidence() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'generatedAnswer.used_evidence_ids.includes(item.evidence_id)' in text
    assert 'rag-used-badge' in text
    assert 'rag-available-badge' in text
    assert '{used ? "USED" : "AVAILABLE"}' in text
    assert 'rag-context-row-body' in text


def test_stage14_2b_technical_inspector_uses_generation_response_metadata_only() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert '{generatedAnswer.generation_provider} · {generatedAnswer.generation_model}' in text
    assert '{generatedAnswer.retrieval_profile}' in text
    assert '{generatedAnswer.context_strategy}' in text
    assert '{generatedAnswer.citation_version}' in text
    assert '{generatedAnswer.usage?.total_tokens ?? "—"}' in text


def test_stage14_2b_styles_support_progressive_disclosure_and_responsive_layout() -> None:
    css = STYLES.read_text(encoding="utf-8")
    assert 'Stage 14.2B — progressive-disclosure playground polish' in css
    assert '.rag-answer-inspector-head' in css
    assert '.rag-context-row summary' in css
    assert '.rag-technical-grid' in css
    assert '@media (max-width: 980px)' in css
    assert '@media (max-width: 620px)' in css
