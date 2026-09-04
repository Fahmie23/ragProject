from __future__ import annotations

from pathlib import Path

from app.db.models import (
    RetrievalExperimentCandidateRow,
    RetrievalExperimentRow,
    RetrievalExperimentRunRow,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND_DIR / "alembic" / "versions" / "0003_stage15_retrieval_experiments.py"


def _foreign_key_target(table, column_name: str) -> tuple[str, str | None]:
    fk = next(iter(table.c[column_name].foreign_keys))
    return fk.target_fullname, fk.ondelete


def test_stage15_1b_experiment_storage_tables_are_distinct_from_evaluation_tables() -> None:
    assert RetrievalExperimentRow.__tablename__ == "retrieval_experiments"
    assert RetrievalExperimentRunRow.__tablename__ == "retrieval_experiment_runs"
    assert RetrievalExperimentCandidateRow.__tablename__ == "retrieval_experiment_candidates"


def test_stage15_1b_run_references_experiment_and_protects_document_history() -> None:
    table = RetrievalExperimentRunRow.__table__

    target, ondelete = _foreign_key_target(table, "experiment_id")
    assert target == "retrieval_experiments.experiment_id"
    assert ondelete == "CASCADE"

    target, ondelete = _foreign_key_target(table, "document_id")
    assert target == "documents.document_id"
    assert ondelete is None

    assert table.c.document_sha256.nullable is False
    assert table.c.question.nullable is False
    assert table.c.config_snapshot.nullable is False


def test_stage15_1b_candidates_keep_historical_chunk_identity_without_live_chunk_fk() -> None:
    table = RetrievalExperimentCandidateRow.__table__

    run_target, ondelete = _foreign_key_target(table, "run_id")
    assert run_target == "retrieval_experiment_runs.run_id"
    assert ondelete == "CASCADE"

    assert not table.c.chunk_id.foreign_keys
    assert table.c.chunk_index.nullable is False
    assert table.c.semantic_type.nullable is False

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    assert "uq_retrieval_experiment_candidates_run_chunk" in unique_names


def test_stage15_1b_candidate_trace_preserves_all_current_retrieval_stage_fields() -> None:
    columns = set(RetrievalExperimentCandidateRow.__table__.c.keys())
    assert {
        "dense_rank",
        "dense_score",
        "lexical_rank",
        "lexical_score",
        "lexical_matched_term_count",
        "lexical_term_coverage",
        "rrf_rank",
        "rrf_score",
        "reranker_rank",
        "reranker_score",
        "final_rank",
        "selected_top_k",
    }.issubset(columns)


def test_stage15_1b_migration_is_linear_and_reversible() -> None:
    text = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0003_stage15_experiments"' in text
    assert 'down_revision: Union[str, None] = "0002_stage6_dense_baseline"' in text
    assert 'op.create_table(\n        "retrieval_experiments"' in text
    assert 'op.create_table(\n        "retrieval_experiment_runs"' in text
    assert 'op.create_table(\n        "retrieval_experiment_candidates"' in text
    assert 'sa.ForeignKey("documents.document_id")' in text
    assert 'sa.ForeignKey("chunks.chunk_id"' not in text
    assert 'op.drop_table("retrieval_experiment_candidates")' in text
    assert 'op.drop_table("retrieval_experiment_runs")' in text
    assert 'op.drop_table("retrieval_experiments")' in text
