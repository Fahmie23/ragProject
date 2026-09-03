from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.evaluation_explorer import (
    EvaluationExplorerError,
    build_answer_citation_summary,
    get_answer_citation_question,
    list_answer_citation_questions,
)


router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


def _translate_error(exc: EvaluationExplorerError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "evaluation_artifact_unavailable", "message": str(exc)},
    )


@router.get("/answer-citation/summary")
def answer_citation_summary() -> dict:
    """Read-only Stage 11 held-out answer/citation evaluation summary.

    This endpoint reads frozen artifacts only. It never calls retrieval, generation,
    Groq, or an automated semantic judge.
    """

    try:
        return build_answer_citation_summary()
    except EvaluationExplorerError as exc:
        raise _translate_error(exc) from exc


@router.get("/answer-citation/questions")
def answer_citation_questions(
    category: str | None = Query(default=None),
    difficulty: str | None = Query(default=None),
    failure_only: bool = Query(default=False),
) -> list[dict]:
    try:
        rows = list_answer_citation_questions()
    except EvaluationExplorerError as exc:
        raise _translate_error(exc) from exc

    if category:
        rows = [row for row in rows if str(row.get("category")) == category]
    if difficulty:
        rows = [row for row in rows if str(row.get("difficulty")) == difficulty]
    if failure_only:
        rows = [row for row in rows if row.get("failure_flags")]
    return rows


@router.get("/answer-citation/questions/{question_id}")
def answer_citation_question(question_id: str) -> dict:
    try:
        payload = get_answer_citation_question(question_id)
    except EvaluationExplorerError as exc:
        raise _translate_error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Frozen evaluation question not found.")
    return payload
