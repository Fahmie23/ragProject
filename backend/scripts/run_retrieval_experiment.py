#!/usr/bin/env python3
"""Stage 15 controlled retrieval experiment runner.

Purpose
-------
Run a DEV-only candidate_k ablation against the frozen SC AML/CFT retrieval
pipeline without modifying production Retrieval v1.

The runner:
- loads the existing formal retrieval dataset;
- uses only questions with split == "dev";
- executes the current same-execution Hybrid + Reranker + Context endpoint;
- varies only candidate_k by default (10, 20, 40);
- validates and stores the current retrieval_trace;
- persists experiment/run/candidate snapshots in the Stage 15 tables;
- scores ranking quality against the existing DEV gold chunk labels;
- writes auditable JSON/text artifacts.

Held-out execution is intentionally unsupported by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import (  # noqa: E402
    RetrievalExperimentCandidateRow,
    RetrievalExperimentRow,
    RetrievalExperimentRunRow,
)
from app.db.session import session_scope  # noqa: E402
from app.schemas import RetrievalExperimentConfigV1  # noqa: E402
from app.services.evaluation.retrieval_metrics import (  # noqa: E402
    aggregate_scored_results,
    grouped_aggregates,
    score_ranking,
)

DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "retrieval" / "retrieval_eval_v1.json"
DEFAULT_CHUNKS_DIR = BACKEND_ROOT / "data" / "chunks"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "evaluation" / "stage15" / "experiments"

# Confirmed current Stage 8.2 endpoint. It reuses the frozen Stage-8 ranking
# path verbatim and only assembles structural context after ranking.
ENDPOINT = "/api/retrieval/hybrid-rerank-context"

BASELINE_PROFILE = "retrieval_v1_stage8_2_top5"
EXPERIMENT_KIND = "candidate_k_ablation_v1"
EXPECTED_TRACE_VERSION = "retrieval_trace_v1"
KS = [1, 3, 5, 10]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        value = result.stdout.strip()
        return value or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _parse_candidate_ks(value: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("candidate K values must be integers") from exc

    if not values:
        raise argparse.ArgumentTypeError("at least one candidate K is required")
    if len(values) != len(set(values)):
        raise argparse.ArgumentTypeError("candidate K values must be unique")
    if any(value < 1 or value > 100 for value in values):
        raise argparse.ArgumentTypeError("candidate K values must be in [1, 100]")
    return values


def _validate_dataset(dataset: dict[str, Any], *, top_k: int) -> tuple[str, str, int, list[dict[str, Any]]]:
    document = dataset.get("document")
    chunk_corpus = dataset.get("chunk_corpus")
    questions = dataset.get("questions")

    if not isinstance(document, dict):
        raise ValueError("dataset.document is missing")
    if not isinstance(chunk_corpus, dict):
        raise ValueError("dataset.chunk_corpus is missing")
    if not isinstance(questions, list):
        raise ValueError("dataset.questions is missing")

    document_id = str(document.get("document_id") or "").strip()
    source_sha = str(document.get("source_sha256") or "").strip()
    chunk_count = int(chunk_corpus.get("chunk_count") or 0)

    if not document_id:
        raise ValueError("dataset document_id is empty")
    if len(source_sha) != 64:
        raise ValueError("dataset source_sha256 is invalid")
    if chunk_count <= 0:
        raise ValueError("dataset chunk_count must be positive")
    if top_k < max(KS):
        raise ValueError(f"top_k must be >= {max(KS)} so MRR@10/Hit@10 remain measurable")

    dev_questions = [question for question in questions if question.get("split") == "dev"]
    expected_dev = int(dataset.get("counts", {}).get("by_split", {}).get("dev", len(dev_questions)))
    if len(dev_questions) != expected_dev:
        raise ValueError(f"DEV split count mismatch: expected {expected_dev}, got {len(dev_questions)}")

    # This runner is intentionally DEV-only. No held-out flag exists.
    return document_id, source_sha, chunk_count, dev_questions


def _build_configs(candidate_ks: list[int], *, top_k: int) -> list[tuple[str, RetrievalExperimentConfigV1]]:
    variants: list[tuple[str, RetrievalExperimentConfigV1]] = []
    for candidate_k in candidate_ks:
        config = RetrievalExperimentConfigV1(
            strategy="hybrid_reranker",
            top_k=top_k,
            candidate_k=candidate_k,
            rrf_k=60,
            dense_weight=1.0,
            lexical_weight=1.0,
        )
        variants.append((f"k{candidate_k}", config))
    return variants


def _preflight(
    session: requests.Session,
    *,
    base_url: str,
    timeout: int,
    document_id: str,
    expected_chunk_count: int,
    embedding_model: str,
) -> dict[str, Any]:
    checks: list[tuple[str, str, dict[str, Any] | None]] = [
        ("database", "/api/system/database", None),
        ("embeddings_runtime", "/api/system/embeddings", None),
        (
            "document_embeddings",
            f"/api/documents/{document_id}/embeddings",
            {"embedding_model": embedding_model},
        ),
        ("reranker", "/api/system/reranker", None),
    ]

    result: dict[str, Any] = {}
    for name, endpoint, params in checks:
        try:
            response = session.get(
                f"{base_url.rstrip('/')}{endpoint}",
                params=params,
                timeout=min(timeout, 60),
            )
            try:
                payload: Any = response.json()
            except ValueError:
                payload = response.text

            ok = response.ok
            if name == "document_embeddings" and response.ok and isinstance(payload, dict):
                ok = (
                    bool(payload.get("complete"))
                    and int(payload.get("chunk_count", -1)) == expected_chunk_count
                    and int(payload.get("embedded_chunk_count", -1)) == expected_chunk_count
                    and str(payload.get("embedding_model")) == embedding_model
                )

            result[name] = {
                "ok": bool(ok),
                "status_code": response.status_code,
                "response": payload,
            }
        except requests.RequestException as exc:
            result[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return result


def _request_payload(
    *,
    document_id: str,
    question: str,
    config: RetrievalExperimentConfigV1,
) -> dict[str, Any]:
    locked = config.locked_components
    return {
        "document_id": document_id,
        "query": question,
        "top_k": config.top_k,
        "candidate_k": config.candidate_k,
        "rrf_k": config.rrf_k,
        "dense_weight": config.dense_weight,
        "lexical_weight": config.lexical_weight,
        "embedding_model": locked.embedding_model,
        "embedding_device": "auto",
        "reranker_model": locked.reranker_model,
        "reranker_device": "auto",
        # Runtime parameter, not a retrieval-quality variable.
        "reranker_batch_size": 2,
        # Frozen Stage 8.2 context settings. Ranking is finalized before these
        # settings are used by the endpoint.
        "context_max_forward_neighbors_per_seed": 2,
        "context_max_backward_neighbors_per_seed": 1,
        "context_max_page_gap": 1,
        "context_max_chunks": 30,
    }


def _validate_response(
    response: dict[str, Any],
    *,
    question: dict[str, Any],
    document_id: str,
    config: RetrievalExperimentConfigV1,
) -> dict[str, Any]:
    if response.get("document_id") != document_id:
        raise ValueError("response document_id mismatch")
    if str(response.get("query", "")).strip() != str(question["question"]).strip():
        raise ValueError("response query mismatch")
    if int(response.get("top_k", -1)) != int(config.top_k):
        raise ValueError("response top_k mismatch")
    if int(response.get("candidate_k", -1)) != int(config.candidate_k or -1):
        raise ValueError("response candidate_k mismatch")
    if int(response.get("rrf_k", -1)) != int(config.rrf_k or -1):
        raise ValueError("response rrf_k mismatch")
    if float(response.get("dense_weight", -1.0)) != float(config.dense_weight or 0.0):
        raise ValueError("response dense_weight mismatch")
    if float(response.get("lexical_weight", -1.0)) != float(config.lexical_weight or 0.0):
        raise ValueError("response lexical_weight mismatch")

    hits = response.get("hits")
    if not isinstance(hits, list):
        raise ValueError("response.hits is not a list")
    if len(hits) > config.top_k:
        raise ValueError(f"response returned {len(hits)} hits for top_k={config.top_k}")

    hit_ids = [str(hit.get("chunk_id")) for hit in hits]
    if len(hit_ids) != len(set(hit_ids)):
        raise ValueError("response contains duplicate hit chunk IDs")
    hit_ranks = [int(hit.get("rank", -1)) for hit in hits]
    if hit_ranks != list(range(1, len(hits) + 1)):
        raise ValueError(f"response hit ranks are not consecutive: {hit_ranks}")

    trace = response.get("retrieval_trace")
    if not isinstance(trace, dict):
        raise ValueError("current retrieval response did not return retrieval_trace")
    if trace.get("trace_version") != EXPECTED_TRACE_VERSION:
        raise ValueError(
            f"unexpected retrieval trace version: {trace.get('trace_version')!r}"
        )
    if trace.get("same_execution") is not True:
        raise ValueError("retrieval_trace.same_execution must be true")

    for field in (
        "dense_candidates",
        "lexical_candidates",
        "fused_candidates",
        "reranked_candidates",
    ):
        if not isinstance(trace.get(field), list):
            raise ValueError(f"retrieval_trace.{field} is not a list")

    return trace


def _score(question: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    retrieved_ids = [str(hit["chunk_id"]) for hit in response.get("hits", [])]
    gold = question["gold"]
    return score_ranking(
        retrieved_chunk_ids=retrieved_ids,
        primary_chunk_ids=gold["primary_chunk_ids"],
        required_evidence_groups=gold.get("required_evidence_groups", []),
        ks=KS,
    )


def _merge_candidate_trace(
    trace: dict[str, Any],
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge same-execution trace stages into one historical candidate snapshot."""

    merged: dict[str, dict[str, Any]] = {}

    def ensure(item: dict[str, Any]) -> dict[str, Any]:
        chunk_id = str(item["chunk_id"])
        row = merged.setdefault(
            chunk_id,
            {
                "chunk_id": chunk_id,
                "chunk_index": int(item.get("chunk_index", -1)),
                "semantic_type": str(item.get("semantic_type") or "unknown"),
                "pages": list(item.get("pages", [])),
                "section_path": list(item.get("section_path", [])),
                "dense_rank": None,
                "dense_score": None,
                "lexical_rank": None,
                "lexical_score": None,
                "lexical_matched_term_count": None,
                "lexical_term_coverage": None,
                "rrf_rank": None,
                "rrf_score": None,
                "reranker_rank": None,
                "reranker_score": None,
                "final_rank": None,
                "selected_top_k": False,
            },
        )
        if row["chunk_index"] < 0 and item.get("chunk_index") is not None:
            row["chunk_index"] = int(item["chunk_index"])
        if row["semantic_type"] == "unknown" and item.get("semantic_type"):
            row["semantic_type"] = str(item["semantic_type"])
        if not row["pages"] and item.get("pages"):
            row["pages"] = list(item["pages"])
        if not row["section_path"] and item.get("section_path"):
            row["section_path"] = list(item["section_path"])
        return row

    for item in trace.get("dense_candidates", []):
        row = ensure(item)
        row["dense_rank"] = int(item["rank"])
        row["dense_score"] = float(item["score"])

    for item in trace.get("lexical_candidates", []):
        row = ensure(item)
        row["lexical_rank"] = int(item["rank"])
        row["lexical_score"] = float(item["score"])
        row["lexical_matched_term_count"] = int(item.get("matched_term_count", 0))
        row["lexical_term_coverage"] = float(item.get("term_coverage", 0.0))

    for item in trace.get("fused_candidates", []):
        row = ensure(item)
        row["rrf_rank"] = int(item["rank"])
        row["rrf_score"] = float(item["fusion_score"])

    for item in trace.get("reranked_candidates", []):
        row = ensure(item)
        reranker_rank = int(item["reranker_rank"])
        row["reranker_rank"] = reranker_rank
        row["reranker_score"] = float(item["reranker_score"])
        # The reranker ordering is the final ranking before top_k selection.
        row["final_rank"] = reranker_rank

    authoritative_hits = {str(hit["chunk_id"]): int(hit["rank"]) for hit in hits}
    for item in hits:
        row = ensure(item)
        row["selected_top_k"] = True
        # Final response rank is authoritative for selected results.
        row["final_rank"] = int(item["rank"])

    # Trace candidates should have real chunk metadata.
    invalid = [
        row["chunk_id"]
        for row in merged.values()
        if int(row["chunk_index"]) < 0
    ]
    if invalid:
        raise ValueError(f"candidate trace missing chunk_index for: {invalid[:5]}")

    return sorted(
        merged.values(),
        key=lambda row: (
            row["final_rank"] is None,
            row["final_rank"] if row["final_rank"] is not None else 10**9,
            row["rrf_rank"] if row["rrf_rank"] is not None else 10**9,
            row["dense_rank"] if row["dense_rank"] is not None else 10**9,
            row["lexical_rank"] if row["lexical_rank"] is not None else 10**9,
            row["chunk_index"],
        ),
    )


def _prepare_experiment(
    *,
    experiment_id: str,
    configs: list[tuple[str, RetrievalExperimentConfigV1]],
    dataset: dict[str, Any],
    overwrite: bool,
) -> None:
    draft_config = {
        "experiment_kind": EXPERIMENT_KIND,
        "dataset_id": dataset.get("dataset_id"),
        "split": "dev",
        "variants": {
            variant: config.model_dump(mode="json")
            for variant, config in configs
        },
    }

    with session_scope() as db:
        existing = db.get(RetrievalExperimentRow, experiment_id)
        if existing is not None:
            if not overwrite:
                raise RuntimeError(
                    f"experiment_id already exists in database: {experiment_id}; "
                    "use --overwrite to replace it explicitly"
                )
            db.delete(existing)
            db.flush()

        db.add(
            RetrievalExperimentRow(
                experiment_id=experiment_id,
                name="Stage 15 candidate_k ablation",
                description=(
                    "DEV-only controlled Hybrid + Reranker experiment varying candidate_k "
                    "while keeping Retrieval v1 model, lexical, RRF and reranker identities locked."
                ),
                baseline_profile=BASELINE_PROFILE,
                draft_config=draft_config,
            )
        )


def _persist_run(
    *,
    experiment_id: str,
    run_id: str,
    document_id: str,
    source_sha: str,
    question_text: str,
    config: RetrievalExperimentConfigV1,
    chunking_version: str,
    chunk_fingerprint: str,
    app_commit_sha: str | None,
    started_at: datetime,
    completed_at: datetime,
    duration_ms: int,
    status: str,
    error_message: str | None,
    trace_version: str | None,
    candidates: list[dict[str, Any]],
) -> None:
    with session_scope() as db:
        run = RetrievalExperimentRunRow(
            run_id=run_id,
            experiment_id=experiment_id,
            document_id=document_id,
            document_sha256=source_sha,
            question=question_text,
            status=status,
            baseline_profile=BASELINE_PROFILE,
            config_snapshot=config.model_dump(mode="json"),
            chunking_version=chunking_version,
            chunk_artifact_fingerprint=chunk_fingerprint,
            retrieval_trace_version=trace_version,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            app_commit_sha=app_commit_sha,
            error_message=error_message,
        )
        db.add(run)
        db.flush()

        for item in candidates:
            db.add(
                RetrievalExperimentCandidateRow(
                    run_id=run_id,
                    chunk_id=item["chunk_id"],
                    chunk_index=item["chunk_index"],
                    semantic_type=item["semantic_type"],
                    pages=item["pages"],
                    section_path=item["section_path"],
                    dense_rank=item["dense_rank"],
                    dense_score=item["dense_score"],
                    lexical_rank=item["lexical_rank"],
                    lexical_score=item["lexical_score"],
                    lexical_matched_term_count=item["lexical_matched_term_count"],
                    lexical_term_coverage=item["lexical_term_coverage"],
                    rrf_rank=item["rrf_rank"],
                    rrf_score=item["rrf_score"],
                    reranker_rank=item["reranker_rank"],
                    reranker_score=item["reranker_score"],
                    final_rank=item["final_rank"],
                    selected_top_k=bool(item["selected_top_k"]),
                )
            )


def _comparison_report(
    *,
    experiment_id: str,
    aggregates: dict[str, Any],
    configs: dict[str, dict[str, Any]],
) -> str:
    header = (
        "Variant",
        "candidate_k",
        "Hit@1",
        "Hit@5",
        "Recall@5",
        "MRR@10",
        "Complete@5",
        "Avg ms",
        "Avg union",
    )
    rows: list[tuple[str, ...]] = []

    for variant, result in aggregates.items():
        overall = result["overall"]
        cfg = configs[variant]
        rows.append(
            (
                variant,
                str(cfg["candidate_k"]),
                f"{100 * float(overall.get('hit_at_1', 0.0)):.1f}%",
                f"{100 * float(overall.get('hit_at_5', 0.0)):.1f}%",
                f"{100 * float(overall.get('recall_at_5', 0.0)):.1f}%",
                f"{float(overall.get('reciprocal_rank', 0.0)):.4f}",
                f"{100 * float(overall.get('complete_evidence_at_5', 0.0)):.1f}%",
                f"{float(result.get('average_duration_ms', 0.0)):.1f}",
                f"{float(result.get('average_candidate_union_count', 0.0)):.1f}",
            )
        )

    widths = [len(value) for value in header]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def fmt(row: tuple[str, ...]) -> str:
        return " | ".join(
            value.ljust(widths[index]) if index < len(row) - 1 else value
            for index, value in enumerate(row)
        )

    lines = [
        "STAGE 15 CONTROLLED RETRIEVAL EXPERIMENT",
        "========================================",
        "",
        f"Experiment ID : {experiment_id}",
        "Split         : dev only",
        "Strategy      : hybrid_reranker",
        "Variable      : candidate_k only",
        "Frozen        : BGE-M3, PostgreSQL FTS, OR content terms v1, RRF k=60,",
        "                dense weight=1.0, lexical weight=1.0, BGE reranker v2-m3",
        "Production    : Retrieval v1 remains unchanged regardless of this result.",
        "",
        fmt(header),
        "-+-".join("-" * width for width in widths),
    ]
    lines.extend(fmt(row) for row in rows)
    lines.extend(
        [
            "",
            "Interpretation rule:",
            "- Compare retrieval quality and candidate/runtime cost together.",
            "- Do not select or modify production settings from held-out data.",
            "- A larger candidate_k is not preferable when quality is effectively unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--experiment-id", default="stage15-candidate-k-v1")
    parser.add_argument("--candidate-ks", type=_parse_candidate_ks, default=[10, 20, 40])
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--limit", type=int, default=0, help="DEV question limit; 0 means all 25")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Execute and score without writing Stage 15 experiment tables.",
    )
    args = parser.parse_args()

    dataset_path = args.dataset.resolve()
    dataset = _load_json(dataset_path)
    document_id, source_sha, expected_chunk_count, questions = _validate_dataset(
        dataset,
        top_k=args.top_k,
    )

    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.limit:
        questions = questions[: args.limit]

    configs = _build_configs(args.candidate_ks, top_k=args.top_k)
    config_map = {
        variant: config.model_dump(mode="json")
        for variant, config in configs
    }

    chunks_path = DEFAULT_CHUNKS_DIR / f"{document_id}.json"
    if not chunks_path.exists():
        raise SystemExit(f"Frozen Stage 5 chunk artifact not found: {chunks_path}")
    chunk_fingerprint = _sha256_file(chunks_path)
    chunking_version = str(dataset["chunk_corpus"].get("stage5_strategy_version") or "")
    app_commit_sha = _git_commit_sha()

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (DEFAULT_OUTPUT_ROOT / args.experiment_id).resolve()
    )
    if output_dir.exists():
        if not args.overwrite:
            parser.error(f"output directory exists: {output_dir}; use --overwrite")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    embedding_model = configs[0][1].locked_components.embedding_model
    preflight = _preflight(
        session,
        base_url=args.base_url,
        timeout=args.timeout,
        document_id=document_id,
        expected_chunk_count=expected_chunk_count,
        embedding_model=embedding_model,
    )
    _atomic_write_json(output_dir / "preflight.json", preflight)

    required_checks = ("database", "embeddings_runtime", "document_embeddings", "reranker")
    failed_checks = [name for name in required_checks if not preflight.get(name, {}).get("ok")]
    if failed_checks:
        raise SystemExit(
            f"Preflight failed: {', '.join(failed_checks)}. "
            f"See {output_dir / 'preflight.json'}"
        )

    if not args.no_persist:
        _prepare_experiment(
            experiment_id=args.experiment_id,
            configs=configs,
            dataset=dataset,
            overwrite=args.overwrite,
        )

    manifest: dict[str, Any] = {
        "schema_version": "stage15_retrieval_experiment_run_v1",
        "experiment_id": args.experiment_id,
        "experiment_kind": EXPERIMENT_KIND,
        "status": "running",
        "started_at": datetime.now().astimezone().isoformat(),
        "finished_at": None,
        "dataset_id": dataset.get("dataset_id"),
        "dataset_path": str(dataset_path),
        "dataset_sha256": _sha256_file(dataset_path),
        "split": "dev",
        "question_count": len(questions),
        "document_id": document_id,
        "document_sha256": source_sha,
        "chunking_version": chunking_version,
        "chunk_artifact_path": str(chunks_path),
        "chunk_artifact_fingerprint": chunk_fingerprint,
        "app_commit_sha": app_commit_sha,
        "endpoint": ENDPOINT,
        "variants": config_map,
        "persist_database": not args.no_persist,
        "preflight": preflight,
    }
    _atomic_write_json(output_dir / "manifest.json", manifest)

    all_rows: list[dict[str, Any]] = []
    total = len(questions) * len(configs)
    current = 0

    print(
        f"Stage 15 retrieval experiment: {args.experiment_id} | "
        f"DEV questions={len(questions)} | variants={','.join(v for v, _ in configs)}"
    )
    print(f"Output: {output_dir}")
    print()

    for variant, config in configs:
        for question in questions:
            current += 1
            qid = str(question["question_id"])
            run_id = f"{args.experiment_id}-{variant}-{qid}"
            response_path = output_dir / "responses" / variant / f"{qid}.json"
            response_path.parent.mkdir(parents=True, exist_ok=True)

            print(
                f"[{current}/{total}] {variant} {qid} "
                f"candidate_k={config.candidate_k}: {question['question']}"
            )

            started_at = datetime.now().astimezone()
            timer = time.perf_counter()
            status = "failed"
            error_message: str | None = None
            trace_version: str | None = None
            candidates: list[dict[str, Any]] = []

            row: dict[str, Any] = {
                "variant": variant,
                "candidate_k": config.candidate_k,
                "question_id": qid,
                "category": question["category"],
                "difficulty": question["difficulty"],
                "question": question["question"],
                "status": "error",
                "metrics": {},
                "candidate_union_count": None,
                "duration_ms": None,
                "response_file": str(response_path.relative_to(output_dir)),
                "error": None,
            }

            try:
                payload = _request_payload(
                    document_id=document_id,
                    question=question["question"],
                    config=config,
                )
                response = session.post(
                    f"{args.base_url.rstrip('/')}{ENDPOINT}",
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=args.timeout,
                )
                if not response.ok:
                    try:
                        detail: Any = response.json()
                    except ValueError:
                        detail = response.text
                    raise RuntimeError(f"HTTP {response.status_code}: {detail}")

                response_json = response.json()
                _atomic_write_json(response_path, response_json)

                trace = _validate_response(
                    response_json,
                    question=question,
                    document_id=document_id,
                    config=config,
                )
                trace_version = str(trace["trace_version"])
                candidates = _merge_candidate_trace(trace, response_json.get("hits", []))
                row["metrics"] = _score(question, response_json)
                row["candidate_union_count"] = int(response_json.get("candidate_union_count", 0))
                row["status"] = "ok"
                status = "completed"

                print(
                    "  OK "
                    f"rank={row['metrics']['first_relevant_rank']} "
                    f"RR={row['metrics']['reciprocal_rank']:.4f} "
                    f"union={row['candidate_union_count']}"
                )
            except Exception as exc:
                error_message = f"{type(exc).__name__}: {exc}"
                row["error"] = error_message
                print(f"  ERROR {error_message}")

            duration_ms = int(round((time.perf_counter() - timer) * 1000.0))
            completed_at = datetime.now().astimezone()
            row["duration_ms"] = duration_ms
            all_rows.append(row)

            if not args.no_persist:
                _persist_run(
                    experiment_id=args.experiment_id,
                    run_id=run_id,
                    document_id=document_id,
                    source_sha=source_sha,
                    question_text=question["question"],
                    config=config,
                    chunking_version=chunking_version,
                    chunk_fingerprint=chunk_fingerprint,
                    app_commit_sha=app_commit_sha,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    status=status,
                    error_message=error_message,
                    trace_version=trace_version,
                    candidates=candidates,
                )

            _atomic_write_json(output_dir / "all_results.partial.json", all_rows)

    aggregates: dict[str, Any] = {}
    for variant, _config in configs:
        rows = [row for row in all_rows if row["variant"] == variant]
        successful = [row for row in rows if row["status"] == "ok"]
        durations = [float(row["duration_ms"]) for row in successful]
        unions = [
            float(row["candidate_union_count"])
            for row in successful
            if row["candidate_union_count"] is not None
        ]

        aggregates[variant] = {
            "config": config_map[variant],
            "overall": aggregate_scored_results(rows, ks=KS),
            "by_category": grouped_aggregates(rows, field="category", ks=KS),
            "by_difficulty": grouped_aggregates(rows, field="difficulty", ks=KS),
            "average_duration_ms": mean(durations) if durations else None,
            "average_candidate_union_count": mean(unions) if unions else None,
        }

    comparison = _comparison_report(
        experiment_id=args.experiment_id,
        aggregates=aggregates,
        configs=config_map,
    )

    _atomic_write_json(output_dir / "all_results.json", all_rows)
    _atomic_write_json(output_dir / "aggregate_metrics.json", aggregates)
    (output_dir / "comparison_report.txt").write_text(comparison, encoding="utf-8")

    partial = output_dir / "all_results.partial.json"
    if partial.exists():
        partial.unlink()

    failures = [row for row in all_rows if row["status"] != "ok"]
    manifest.update(
        {
            "status": "complete" if not failures else "failed",
            "finished_at": datetime.now().astimezone().isoformat(),
            "failed_run_count": len(failures),
            "output_files": {
                "all_results": "all_results.json",
                "aggregate_metrics": "aggregate_metrics.json",
                "comparison_report": "comparison_report.txt",
            },
        }
    )
    _atomic_write_json(output_dir / "manifest.json", manifest)

    print()
    print(comparison)
    print(f"Manifest: {output_dir / 'manifest.json'}")
    print(f"Metrics : {output_dir / 'aggregate_metrics.json'}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
