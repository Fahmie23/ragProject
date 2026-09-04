from __future__ import annotations

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SHELL = REPO_ROOT / "frontend" / "src" / "app" / "RagWorkbenchShell.tsx"


def test_stage15_primary_navigation_hides_benchmark() -> None:
    text = SHELL.read_text(encoding="utf-8")
    header = text.split("function AppHeader", 1)[1].split("function PipelineStep", 1)[0]

    assert '{ id: "overview", label: "Overview", icon: "⌂" }' in header
    assert '{ id: "documents", label: "Documents", icon: "▤" }' in header
    assert '{ id: "playground", label: "RAG Playground", icon: "✦" }' in header
    assert 'label: "Benchmark"' not in header


def test_stage15_overview_is_product_focused_and_experiment_ready() -> None:
    text = SHELL.read_text(encoding="utf-8")
    overview = text.split("function Overview", 1)[1].split("type LiveRetrievalStrategy", 1)[0]

    assert "Primary benchmark" not in overview
    assert "Benchmark ready" not in overview
    assert "Benchmark report" not in overview
    assert "Open Benchmark" not in overview
    assert 'onChange("evaluation")' not in overview
    assert "Reference document" in overview
    assert "Pipeline ready" in overview
    assert 'label="Retrieval experiments"' in overview
    assert 'detail="Controlled comparisons against frozen Retrieval v1"' in overview
    assert 'state="next"' in overview


def test_stage15_preserves_frozen_evaluation_internally() -> None:
    text = SHELL.read_text(encoding="utf-8")

    assert 'type AppView = "overview" | "documents" | "playground" | "evaluation";' in text
    assert "function Evaluation()" in text
    assert 'fetchEvaluationJson<EvaluationSummary>("/api/evaluation/answer-citation/summary"' in text
    assert '{active === "evaluation" && <Evaluation />}' in text
