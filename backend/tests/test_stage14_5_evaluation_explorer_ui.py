from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SHELL = REPO_ROOT / "frontend" / "src" / "app" / "RagWorkbenchShell.tsx"
STYLES = REPO_ROOT / "frontend" / "src" / "styles.css"


def test_stage14_5_reads_only_backend_owned_evaluation_endpoints() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'fetchEvaluationJson<EvaluationSummary>("/api/evaluation/answer-citation/summary"' in text
    assert 'fetchEvaluationJson<EvaluationQuestionRow[]>("/api/evaluation/answer-citation/questions"' in text
    assert '`/api/evaluation/answer-citation/questions/${encodeURIComponent(questionId)}`' in text
    assert "runGroundedAnswer" not in text.split("function Evaluation()", 1)[1]
    assert "Re-run evaluation" not in text
    assert "Benchmark Report" in text
    assert "function Evaluation()" in text
    assert '{active === "evaluation" && <Evaluation />}' in text


def test_stage14_5_default_report_shows_only_four_headline_metrics() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert '{ key: "answer_status_accuracy", label: "Answer decisions"' in text
    assert '{ key: "claim_support_rate", label: "Grounding"' in text
    assert '{ key: "answer_completeness", label: "Completeness"' in text
    assert '{ key: "deterministic_citation_validity", label: "Citation provenance"' in text
    assert 'className="rag-stage14-eval-headline-grid"' in text
    assert "Four numbers to understand first" in text
    assert "The main observed gap is completeness." in text


def test_stage14_5_hides_technical_metrics_and_methodology_by_default() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert '<details className="rag-panel rag-stage14-eval-advanced">' in text
    assert '<summary><span>Advanced metrics</span><small>For deeper engineering inspection</small></summary>' in text
    assert "summary.metrics.map" in text
    assert "selectedMetric.formula" in text
    assert "selectedMetric.source_artifact" in text
    assert '<details className="rag-panel rag-stage14-eval-about">' in text
    assert '<summary><span>About this benchmark</span><small>Scope and methodology</small></summary>' in text
    assert "Cross-document robustness is not established." in text


def test_stage14_5_case_list_uses_simple_statuses_and_no_metric_wall() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert 'type EvaluationFilter = "all" | "complete" | "partial" | "issues" | "out_of_scope";' in text
    assert 'row.expected_status === "insufficient_evidence"' in text
    assert 'row.answer_status_correct ? "out_of_scope" : "issue"' in text
    assert 'semanticRates.some((value) => value != null && value < 1)' in text
    assert 'if (state === "complete") return "PASSED";' in text
    assert 'if (state === "partial") return "PARTIAL";' in text
    assert 'if (state === "issue") return "ISSUE";' in text
    assert 'className="rag-stage14-eval-question-row rag-stage14-eval-question-row-simple"' in text
    row_segment = text.split('className="rag-stage14-eval-question-row rag-stage14-eval-question-row-simple"', 1)[1].split('</button>;', 1)[0]
    assert "formatEvaluationRate(row.claim_support_rate)" not in row_segment
    assert "formatEvaluationRate(row.deterministic_citation_validity)" not in row_segment
    assert "formatEvaluationRate(row.answer_completeness)" not in row_segment


def test_stage14_5_detail_drawer_prioritizes_expected_vs_happened_then_collapses_technical_review() -> None:
    text = SHELL.read_text(encoding="utf-8")
    assert "What was expected" in text
    assert "What happened" in text
    assert "detail.semantic_review.gold_claims.map" in text
    assert 'className="rag-stage14-eval-detail-facts rag-stage14-eval-detail-facts-simple"' in text
    assert "detail.deterministic_result.semantic_metrics?.claim_support_rate" in text
    assert "detail.deterministic_result.metrics?.deterministic_citation_validity" in text
    assert "detail.deterministic_result.semantic_metrics?.answer_completeness" in text
    assert '<details className="rag-stage14-eval-technical-disclosure">' in text
    assert "Show technical evaluation" in text
    assert "detail.semantic_review.claims.map" in text
    assert "detail.semantic_review.citation_relations.map" in text
    assert "detail.frozen_response.cited_answer" in text
    assert 'event.key === "Escape"' in text


def test_stage14_5_simplified_layout_is_responsive_and_progressively_disclosed() -> None:
    css = STYLES.read_text(encoding="utf-8")
    assert ".rag-stage14-eval-headline-grid" in css
    assert ".rag-stage14-eval-takeaway" in css
    assert ".rag-stage14-eval-question-row-simple" in css
    assert ".rag-stage14-eval-advanced" in css
    assert ".rag-stage14-eval-about" in css
    assert ".rag-stage14-eval-technical-disclosure" in css
    assert ".rag-stage14-eval-drawer" in css
    drawer = css.split(".rag-stage14-eval-drawer {", 1)[1].split("}", 1)[0]
    assert "width: min(560px, calc(100vw - 32px));" in drawer
    assert "overflow-y: auto;" in drawer
    assert "@media (max-width: 720px)" in css
