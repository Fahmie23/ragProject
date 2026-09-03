from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SHELL = REPO_ROOT / "frontend" / "src" / "app" / "RagWorkbenchShell.tsx"
API = REPO_ROOT / "frontend" / "src" / "api.ts"


def test_stage14_2_defaults_to_cited_answer_and_isolates_retrieval_experiments() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'useState<PlaygroundMode>("answer")' in text
    assert '>Cited answer</button>' in text
    assert '>Retrieval experiment</button>' in text
    assert "These controls are diagnostic only and do not modify the frozen production profile" in text


def test_stage14_2_primary_answer_path_uses_frozen_generation_endpoint_only() -> None:
    shell = SHELL.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    assert 'runGroundedAnswer({ document_id: documentId, question: clean })' in shell
    assert 'fetch(`${API_BASE}/api/generation/answer`' in api
    assert 'Ask with cited RAG' in shell
    assert 'The user cannot tune this profile from the playground.' in shell


def test_stage14_2_enter_submits_the_active_mode_and_stale_outputs_are_cleared() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'if (event.key !== "Enter" || event.nativeEvent.isComposing) return;' in text
    assert 'void submitCurrentMode();' in text
    assert 'setGeneratedAnswer(null);\n    setResult(null);' in text
    assert 'setResult(null);\n    setGeneratedAnswer(null);\n    setError(null);' in text


def test_stage14_2_cited_answer_markers_link_to_backend_citation_provenance() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'function CitedAnswerText' in text
    assert 'answer.split(/(\\[\\d+\\])/g)' in text
    assert 'citationByMarker.get(part)' in text
    assert 'className="rag-answer-citation-link"' in text
    assert 'title={citation.display}' in text


def test_stage14_2_source_cards_show_the_actual_evidence_text() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'const evidenceById = useMemo' in text
    assert 'const evidence = evidenceById.get(citation.evidence_id);' in text
    assert 'className="rag-source-preview">{evidence.content_text}</p>' in text
    assert 'className="rag-source-evidence-full"' in text
    assert '<p>{evidence.content_text}</p>' in text


def test_stage14_2_does_not_surface_old_mock_evaluation_metrics() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'const DATASET_ROWS' not in text
    assert 'Mock benchmark · 50 questions' not in text
    assert "['Faithfulness',94]" not in text
    assert "['Answer relevance',91]" not in text
    assert "['Citation accuracy',96]" not in text
    assert "['Citation completeness',93]" not in text
