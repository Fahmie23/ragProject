#!/usr/bin/env python3
"""Run the formal SC AML/CFT retrieval benchmark against live FastAPI endpoints.

Default behavior evaluates ONLY the 25-question development split.
Held-out evaluation is deliberately protected and requires an explicit confirmation.

Outputs (default development run):
    retrieval_evaluation_results/<config_id>/dev/
        run_manifest.json
        all_results.json
        per_question_results.csv
        aggregate_metrics.json
        comparison_report.txt
        all_retrieval_evaluation_results.txt
        responses/
            dense/RET-001.json
            hybrid/RET-001.json
            hybrid_rerank/RET-001.json
            ...

The raw response files make runs resumable and auditable. Use --resume after an
interrupted run. Existing output is never silently overwritten.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

# Allow running from backend/ without installing the app as a package.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.retrieval_metrics import (  # noqa: E402
    DEFAULT_KS,
    HELDOUT_CONFIRMATION,
    aggregate_scored_results,
    enforce_split_policy,
    grouped_aggregates,
    score_context_assembly,
    score_ranking,
)

DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "retrieval" / "retrieval_eval_v1.json"
DEFAULT_CONFIG = BACKEND_ROOT / "evaluation" / "retrieval" / "retrieval_config_v1.json"
DEFAULT_RESULTS_ROOT = BACKEND_ROOT / "retrieval_evaluation_results"
STRATEGIES = ("dense", "hybrid", "hybrid_rerank")
ENDPOINTS = {
    "dense": "/api/retrieval/dense",
    "hybrid": "/api/retrieval/hybrid",
    "hybrid_rerank": "/api/retrieval/hybrid-rerank-context",
}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def _parse_strategies(value: str) -> list[str]:
    requested = [item.strip() for item in value.split(",") if item.strip()]
    if not requested:
        raise argparse.ArgumentTypeError("at least one strategy is required")
    invalid = [item for item in requested if item not in STRATEGIES]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"unknown strategies: {', '.join(invalid)}; choose from {', '.join(STRATEGIES)}"
        )
    # Preserve canonical ordering regardless of CLI order.
    return [strategy for strategy in STRATEGIES if strategy in requested]


def _validate_dataset_and_config(dataset: dict[str, Any], config: dict[str, Any]) -> tuple[list[int], int]:
    questions = dataset.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("dataset has no questions")
    if dataset.get("counts", {}).get("questions") != len(questions):
        raise ValueError("dataset question count metadata does not match questions array")

    eval_cfg = config.get("evaluation", {})
    ks = sorted({int(k) for k in eval_cfg.get("ks", DEFAULT_KS) if int(k) > 0})
    if not ks:
        raise ValueError("retrieval config evaluation.ks must contain a positive K")
    top_k = int(eval_cfg.get("top_k", max(ks)))
    if top_k < max(ks):
        raise ValueError("evaluation.top_k must be >= max(evaluation.ks)")

    candidate_k = int(config.get("hybrid", {}).get("candidate_k", 20))
    if candidate_k < top_k:
        raise ValueError("hybrid.candidate_k must be >= evaluation.top_k")
    if config.get("status") not in {"draft", "frozen"}:
        raise ValueError("retrieval config status must be 'draft' or 'frozen'")

    context = config.get("context_expansion", {})
    if context.get("enabled"):
        if context.get("strategy") != "structural_one_hop_v1":
            raise ValueError("unsupported context_expansion.strategy")
        if bool(context.get("recursive", False)):
            raise ValueError("Stage 8.2 context expansion must remain non-recursive")
        if not bool(context.get("same_section_required", True)):
            raise ValueError("Stage 8.2 requires same_section_required=true")
        if int(context.get("max_context_chunks", 30)) < top_k:
            raise ValueError("context_expansion.max_context_chunks must be >= evaluation.top_k")
    return ks, top_k


def _request_payload(
    *, strategy: str, question: str, document_id: str, config: dict[str, Any], top_k: int
) -> dict[str, Any]:
    embedding = config["embedding"]
    hybrid = config["hybrid"]
    base: dict[str, Any] = {
        "document_id": document_id,
        "query": question,
        "top_k": top_k,
    }
    if strategy == "dense":
        base.update({
            "embedding_model": embedding["model"],
            "embedding_device": embedding.get("device", "auto"),
        })
        return base

    base.update({
        "candidate_k": int(hybrid["candidate_k"]),
        "rrf_k": int(hybrid["rrf_k"]),
        "dense_weight": float(hybrid["dense_weight"]),
        "lexical_weight": float(hybrid["lexical_weight"]),
        "embedding_model": embedding["model"],
        "embedding_device": embedding.get("device", "auto"),
    })
    if strategy == "hybrid_rerank":
        reranker = config["reranker"]
        context = config.get("context_expansion", {})
        base.update({
            "reranker_model": reranker["model"],
            "reranker_device": reranker.get("device", "auto"),
            "reranker_batch_size": int(reranker.get("batch_size", 2)),
            "context_max_forward_neighbors_per_seed": int(context.get("max_forward_neighbors_per_seed", 2)),
            "context_max_backward_neighbors_per_seed": int(context.get("max_backward_neighbors_per_seed", 1)),
            "context_max_page_gap": int(context.get("max_page_gap", 1)),
            "context_max_chunks": int(context.get("max_context_chunks", 30)),
        })
    return base


def _preflight(
    session: requests.Session,
    base_url: str,
    *,
    include_reranker: bool,
    timeout: int,
    document_id: str,
    embedding_model: str,
    expected_chunk_count: int,
) -> dict[str, Any]:
    checks = [
        ("database", "/api/system/database", None),
        ("embeddings_runtime", "/api/system/embeddings", None),
        (
            "document_embeddings",
            f"/api/documents/{document_id}/embeddings",
            {"embedding_model": embedding_model},
        ),
    ]
    if include_reranker:
        checks.append(("reranker", "/api/system/reranker", None))

    result: dict[str, Any] = {}
    for name, endpoint, params in checks:
        url = f"{base_url.rstrip('/')}{endpoint}"
        try:
            response = session.get(url, params=params, timeout=min(timeout, 60))
            payload: Any
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            ok = response.ok
            if name == "document_embeddings" and isinstance(payload, dict) and response.ok:
                ok = (
                    bool(payload.get("complete"))
                    and int(payload.get("chunk_count", -1)) == expected_chunk_count
                    and int(payload.get("embedded_chunk_count", -1)) == expected_chunk_count
                    and str(payload.get("embedding_model")) == embedding_model
                )
            result[name] = {
                "ok": ok,
                "status_code": response.status_code,
                "response": payload,
            }
        except requests.RequestException as exc:
            result[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return result


def _validate_response(*, response: dict[str, Any], question: dict[str, Any], document_id: str, top_k: int) -> None:
    if response.get("document_id") != document_id:
        raise ValueError("response document_id mismatch")
    if str(response.get("query", "")).strip() != str(question["question"]).strip():
        raise ValueError("response query does not match evaluation question")
    hits = response.get("hits")
    if not isinstance(hits, list):
        raise ValueError("response.hits is not a list")
    if len(hits) > top_k:
        raise ValueError(f"response returned {len(hits)} hits for top_k={top_k}")
    chunk_ids = [str(hit.get("chunk_id")) for hit in hits]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("response contains duplicate chunk IDs")
    ranks = [int(hit.get("rank", -1)) for hit in hits]
    if ranks != list(range(1, len(hits) + 1)):
        raise ValueError(f"response ranks are not consecutive: {ranks}")
    if "context_chunks" in response:
        context_chunks = response.get("context_chunks")
        if not isinstance(context_chunks, list):
            raise ValueError("response.context_chunks is not a list")
        context_ids = [str(item.get("chunk_id")) for item in context_chunks]
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("response contains duplicate context chunk IDs")
        for item in context_chunks:
            source_rank = int(item.get("source_rank", -1))
            if source_rank < 1 or source_rank > top_k:
                raise ValueError(f"invalid context source_rank: {source_rank}")


def _score_response(question: dict[str, Any], response: dict[str, Any], ks: list[int]) -> dict[str, Any]:
    hits = response.get("hits", [])
    retrieved_ids = [str(hit["chunk_id"]) for hit in hits]
    gold = question["gold"]
    metrics = score_ranking(
        retrieved_chunk_ids=retrieved_ids,
        primary_chunk_ids=gold["primary_chunk_ids"],
        required_evidence_groups=gold.get("required_evidence_groups", []),
        ks=ks,
    )
    if isinstance(response.get("context_chunks"), list):
        metrics.update(score_context_assembly(
            context_chunks=response["context_chunks"],
            primary_chunk_ids=gold["primary_chunk_ids"],
            required_evidence_groups=gold.get("required_evidence_groups", []),
            ks=ks,
        ))
    return metrics


def _compact_hit(strategy: str, hit: dict[str, Any]) -> dict[str, Any]:
    result = {
        "rank": hit.get("rank"),
        "chunk_id": hit.get("chunk_id"),
        "chunk_index": hit.get("chunk_index"),
        "semantic_type": hit.get("semantic_type"),
        "pages": hit.get("pages", []),
        "section_path": hit.get("section_path", []),
    }
    if strategy == "dense":
        result.update({"score": hit.get("score"), "distance": hit.get("distance")})
    elif strategy == "hybrid":
        result.update({
            "fusion_score": hit.get("fusion_score"),
            "dense_rank": hit.get("dense_rank"),
            "dense_score": hit.get("dense_score"),
            "lexical_rank": hit.get("lexical_rank"),
            "lexical_score": hit.get("lexical_score"),
            "lexical_term_coverage": hit.get("lexical_term_coverage"),
        })
    else:
        result.update({
            "reranker_score": hit.get("reranker_score"),
            "hybrid_candidate_rank": hit.get("hybrid_candidate_rank"),
            "fusion_score": hit.get("fusion_score"),
            "dense_rank": hit.get("dense_rank"),
            "dense_score": hit.get("dense_score"),
            "lexical_rank": hit.get("lexical_rank"),
            "lexical_score": hit.get("lexical_score"),
            "lexical_term_coverage": hit.get("lexical_term_coverage"),
        })
    return result


def _compact_context_chunk(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_order": item.get("context_order"),
        "chunk_id": item.get("chunk_id"),
        "chunk_index": item.get("chunk_index"),
        "semantic_type": item.get("semantic_type"),
        "source_rank": item.get("source_rank"),
        "ranked_seed_rank": item.get("ranked_seed_rank"),
        "reasons": item.get("reasons", []),
        "attached_from_chunk_ids": item.get("attached_from_chunk_ids", []),
        "pages": item.get("pages", []),
        "section_path": item.get("section_path", []),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], ks: list[int]) -> None:
    fields = [
        "question_id", "split", "category", "difficulty", "strategy", "status",
        "first_relevant_rank", "reciprocal_rank",
    ]
    for k in ks:
        fields.extend([f"hit_at_{k}", f"recall_at_{k}", f"complete_evidence_at_{k}"])
    for k in ks:
        fields.extend([f"context_recall_at_{k}", f"context_complete_evidence_at_{k}", f"context_chunk_count_at_{k}"])
    fields.extend(["primary_gold_count", "error"])

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            metrics = row.get("metrics", {})
            out = {
                "question_id": row["question_id"],
                "split": row["split"],
                "category": row["category"],
                "difficulty": row["difficulty"],
                "strategy": row["strategy"],
                "status": row["status"],
                "first_relevant_rank": metrics.get("first_relevant_rank", ""),
                "reciprocal_rank": metrics.get("reciprocal_rank", ""),
                "primary_gold_count": metrics.get("primary_gold_count", ""),
                "error": row.get("error", ""),
            }
            for k in ks:
                out[f"hit_at_{k}"] = metrics.get(f"hit_at_{k}", "")
                out[f"recall_at_{k}"] = metrics.get(f"recall_at_{k}", "")
                out[f"complete_evidence_at_{k}"] = metrics.get(f"complete_evidence_at_{k}", "")
                out[f"context_recall_at_{k}"] = metrics.get(f"context_recall_at_{k}", "")
                out[f"context_complete_evidence_at_{k}"] = metrics.get(f"context_complete_evidence_at_{k}", "")
                out[f"context_chunk_count_at_{k}"] = metrics.get(f"context_chunk_count_at_{k}", "")
            writer.writerow(out)


def _pct(value: Any) -> str:
    return "—" if value is None else f"{100.0 * float(value):.1f}%"


def _decimal(value: Any) -> str:
    return "—" if value is None else f"{float(value):.4f}"


def _comparison_report(*, split: str, strategies: list[str], aggregate: dict[str, Any], ks: list[int], config: dict[str, Any], dataset: dict[str, Any]) -> str:
    columns = ["Metric", *strategies]
    metric_rows: list[tuple[str, list[str]]] = []
    for k in ks:
        metric_rows.append((f"Hit@{k}", [_pct(aggregate[s]["overall"].get(f"hit_at_{k}")) for s in strategies]))
    for k in ks:
        metric_rows.append((f"Recall@{k}", [_pct(aggregate[s]["overall"].get(f"recall_at_{k}")) for s in strategies]))
    metric_rows.append((f"MRR@{max(ks)}", [_decimal(aggregate[s]["overall"].get("reciprocal_rank")) for s in strategies]))
    for k in ks:
        metric_rows.append((f"CompleteEvidence@{k}", [_pct(aggregate[s]["overall"].get(f"complete_evidence_at_{k}")) for s in strategies]))

    widths = [len(x) for x in columns]
    for metric, values in metric_rows:
        widths[0] = max(widths[0], len(metric))
        for index, value in enumerate(values, start=1):
            widths[index] = max(widths[index], len(value))

    def fmt(items: Iterable[str]) -> str:
        vals = list(items)
        return " | ".join(value.ljust(widths[i]) for i, value in enumerate(vals))

    lines = [
        "FORMAL RETRIEVAL EVALUATION COMPARISON",
        "======================================",
        "",
        f"Dataset        : {dataset.get('dataset_id')}",
        f"Document ID    : {dataset.get('document', {}).get('document_id')}",
        f"Source SHA-256 : {dataset.get('document', {}).get('source_sha256')}",
        f"Split          : {split}",
        f"Questions      : {sum(1 for q in dataset['questions'] if q['split'] == split)}",
        f"Config ID      : {config.get('config_id')}",
        f"Config status  : {config.get('status')}",
        f"MRR cutoff     : {max(ks)}",
        "",
        fmt(columns),
        "-+-".join("-" * width for width in widths),
    ]
    for metric, values in metric_rows:
        lines.append(fmt([metric, *values]))

    context_strategy = aggregate.get("hybrid_rerank", {}).get("overall", {})
    if context_strategy.get("context_question_count"):
        lines.extend([
            "",
            "STRUCTURAL CONTEXT ASSEMBLY (Hybrid + Reranker only)",
            "-----------------------------------------------------",
            "Raw ranking metrics above are unchanged. Context metrics count bounded structural attachments",
            "whose source_rank is within K; expanded chunks never receive retrieval ranks.",
        ])
        for k in ks:
            lines.append(
                f"ContextRecall@{k}: {_pct(context_strategy.get(f'context_recall_at_{k}'))} | "
                f"ContextCompleteEvidence@{k}: {_pct(context_strategy.get(f'context_complete_evidence_at_{k}'))} | "
                f"avg context chunks: {_decimal(context_strategy.get(f'average_context_chunk_count_at_{k}'))}"
            )

    lines.extend([
        "",
        "Validity",
        "--------",
    ])
    for strategy in strategies:
        overall = aggregate[strategy]["overall"]
        lines.append(
            f"{strategy}: valid={overall['valid']} "
            f"successful={overall['successful_question_count']}/{overall['question_count']} "
            f"failed={overall['failed_question_count']}"
        )
    lines.extend([
        "",
        "Important: development results may be used for diagnosis. Held-out results must not be used",
        "to retune retrieval and then reported as unbiased held-out performance.",
    ])
    return "\n".join(lines) + "\n"


def _human_report(*, rows: list[dict[str, Any]], split: str, strategies: list[str], ks: list[int], comparison: str) -> str:
    by_question: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_question.setdefault(row["question_id"], []).append(row)

    lines = [comparison.rstrip(), "", "", "PER-QUESTION RESULTS", "===================="]
    for qid in sorted(by_question):
        qrows = by_question[qid]
        sample = qrows[0]
        lines.extend([
            "",
            "=" * 100,
            f"{qid} | {sample['category']} | {sample['difficulty']} | split={split}",
            "=" * 100,
            f"Question: {sample['question']}",
            f"Primary gold chunk(s): {sample['primary_chunk_ids']}",
            f"Supporting chunk(s)  : {sample['supporting_chunk_ids']}",
        ])
        strategy_map = {row["strategy"]: row for row in qrows}
        for strategy in strategies:
            row = strategy_map[strategy]
            lines.append("")
            lines.append(f"[{strategy}] status={row['status']} elapsed={row.get('elapsed_seconds', 0.0):.2f}s")
            if row["status"] != "ok":
                lines.append(f"ERROR: {row.get('error')}")
                continue
            metrics = row["metrics"]
            metric_bits = [
                f"first_relevant_rank={metrics['first_relevant_rank']}",
                f"RR={metrics['reciprocal_rank']:.4f}",
            ]
            metric_bits.extend(f"Hit@{k}={int(metrics[f'hit_at_{k}'])}" for k in ks)
            metric_bits.extend(f"Recall@{k}={metrics[f'recall_at_{k}']:.3f}" for k in ks)
            metric_bits.extend(f"Complete@{k}={int(metrics[f'complete_evidence_at_{k}'])}" for k in ks)
            lines.append(" | ".join(metric_bits))
            if row.get("context_chunks"):
                context_bits = []
                for k in ks:
                    context_bits.append(
                        f"ContextRecall@{k}={metrics[f'context_recall_at_{k}']:.3f}"
                    )
                    context_bits.append(
                        f"ContextComplete@{k}={int(metrics[f'context_complete_evidence_at_{k}'])}"
                    )
                    context_bits.append(
                        f"ContextChunks@{k}={int(metrics[f'context_chunk_count_at_{k}'])}"
                    )
                lines.append(" | ".join(context_bits))
            for hit in row["retrieved_hits"]:
                marker = "*" if hit["chunk_id"] in set(row["primary_chunk_ids"]) else " "
                score = hit.get("reranker_score", hit.get("fusion_score", hit.get("score")))
                lines.append(
                    f" {marker} #{hit['rank']:>2} chunk_index={hit.get('chunk_index')} "
                    f"score={score!r} type={hit.get('semantic_type')} pages={hit.get('pages')} "
                    f"chunk_id={hit['chunk_id']}"
                )
            if row.get("context_chunks"):
                lines.append("  Context assembly (separate from ranking):")
                ranked_ids = {hit["chunk_id"] for hit in row["retrieved_hits"]}
                for item in row["context_chunks"]:
                    if item["chunk_id"] in ranked_ids and not item.get("attached_from_chunk_ids"):
                        continue
                    marker = "*" if item["chunk_id"] in set(row["primary_chunk_ids"]) else " "
                    lines.append(
                        f"   {marker} context#{item.get('context_order')} chunk_index={item.get('chunk_index')} "
                        f"source_rank={item.get('source_rank')} seed_rank={item.get('ranked_seed_rank')} "
                        f"reasons={item.get('reasons')} pages={item.get('pages')} chunk_id={item['chunk_id']}"
                    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--split", choices=("dev", "heldout"), default="dev")
    parser.add_argument("--strategies", type=_parse_strategies, default=list(STRATEGIES), help="Comma-separated: dense,hybrid,hybrid_rerank")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true", help="Reuse saved successful raw responses and continue an interrupted run")
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing output directory before starting")
    parser.add_argument("--confirm-heldout", help=f"Required for heldout: {HELDOUT_CONFIRMATION}")
    parser.add_argument("--timeout", type=int, help="Per-request timeout in seconds; defaults to retrieval config")
    args = parser.parse_args()

    dataset_path = args.dataset.resolve()
    config_path = args.config.resolve()
    dataset = _load_json(dataset_path)
    config = _load_json(config_path)
    ks, top_k = _validate_dataset_and_config(dataset, config)

    try:
        enforce_split_policy(
            split=args.split,
            confirmation=args.confirm_heldout,
            config_status=str(config.get("status")),
        )
    except ValueError as exc:
        parser.error(str(exc))

    document_id = str(dataset["document"]["document_id"])
    questions = [q for q in dataset["questions"] if q.get("split") == args.split]
    expected_count = int(dataset.get("counts", {}).get("by_split", {}).get(args.split, len(questions)))
    if len(questions) != expected_count:
        raise SystemExit(f"Dataset split count mismatch: expected {expected_count}, got {len(questions)}")

    strategies = args.strategies
    timeout = int(args.timeout or config.get("evaluation", {}).get("timeout_seconds", 900))
    output_dir = args.output_dir or (DEFAULT_RESULTS_ROOT / str(config.get("config_id", "run")) / args.split)
    output_dir = output_dir.resolve()

    if args.resume and args.overwrite:
        parser.error("--resume and --overwrite cannot be used together")
    if output_dir.exists() and args.overwrite:
        shutil.rmtree(output_dir)
    if output_dir.exists() and not args.resume:
        parser.error(f"output directory already exists: {output_dir}; use --resume or --overwrite")
    output_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now().astimezone()
    session = requests.Session()
    preflight = _preflight(
        session,
        args.base_url,
        include_reranker="hybrid_rerank" in strategies,
        timeout=timeout,
        document_id=document_id,
        embedding_model=str(config["embedding"]["model"]),
        expected_chunk_count=int(dataset["chunk_corpus"]["chunk_count"]),
    )
    if (
        not preflight.get("database", {}).get("ok")
        or not preflight.get("embeddings_runtime", {}).get("ok")
        or not preflight.get("document_embeddings", {}).get("ok")
    ):
        _atomic_write_json(output_dir / "preflight_failure.json", preflight)
        raise SystemExit(
            "Preflight failed. Ensure FastAPI and PostgreSQL/pgvector are available and that the exact "
            f"evaluation document has complete {config['embedding']['model']} embeddings for all "
            f"{dataset['chunk_corpus']['chunk_count']} Stage 5 chunks. See {output_dir / 'preflight_failure.json'}"
        )
    if "hybrid_rerank" in strategies and not preflight.get("reranker", {}).get("ok"):
        _atomic_write_json(output_dir / "preflight_failure.json", preflight)
        raise SystemExit(f"Reranker preflight failed. See {output_dir / 'preflight_failure.json'}")

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "run_status": "running",
        "started_at": started.isoformat(),
        "finished_at": None,
        "base_url": args.base_url,
        "split": args.split,
        "strategies": strategies,
        "question_count": len(questions),
        "ks": ks,
        "top_k": top_k,
        "dataset_path": str(dataset_path),
        "dataset_sha256": _sha256_file(dataset_path),
        "dataset_id": dataset.get("dataset_id"),
        "document_id": document_id,
        "source_sha256": dataset.get("document", {}).get("source_sha256"),
        "config_path": str(config_path),
        "config_sha256": _sha256_file(config_path),
        "config_id": config.get("config_id"),
        "config_status": config.get("status"),
        "preflight": preflight,
    }
    _atomic_write_json(output_dir / "run_manifest.json", manifest)

    all_rows: list[dict[str, Any]] = []
    total_calls = len(questions) * len(strategies)
    current = 0
    print(f"Formal retrieval evaluation: split={args.split}, questions={len(questions)}, strategies={','.join(strategies)}")
    print(f"Output: {output_dir}")
    print(f"K values: {ks} | evaluation top_k={top_k}")
    print()

    for question in questions:
        qid = str(question["question_id"])
        for strategy in strategies:
            current += 1
            response_path = output_dir / "responses" / strategy / f"{qid}.json"
            print(f"[{current}/{total_calls}] {qid} [{strategy}] {question['question']}")
            started_call = time.perf_counter()
            row: dict[str, Any] = {
                "question_id": qid,
                "split": args.split,
                "category": question["category"],
                "difficulty": question["difficulty"],
                "question": question["question"],
                "strategy": strategy,
                "status": "error",
                "primary_chunk_ids": question["gold"]["primary_chunk_ids"],
                "supporting_chunk_ids": question["gold"].get("supporting_chunk_ids", []),
                "required_evidence_groups": question["gold"].get("required_evidence_groups", []),
                "source": question.get("source", {}),
                "response_file": str(response_path.relative_to(output_dir)),
                "metrics": {},
                "retrieved_hits": [],
                "context_chunks": [],
                "error": None,
            }
            try:
                response_json: dict[str, Any]
                if args.resume and response_path.exists():
                    response_json = _load_json(response_path)
                    print("  reusing saved response")
                else:
                    payload = _request_payload(
                        strategy=strategy,
                        question=question["question"],
                        document_id=document_id,
                        config=config,
                        top_k=top_k,
                    )
                    response = session.post(
                        f"{args.base_url.rstrip('/')}{ENDPOINTS[strategy]}",
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=timeout,
                    )
                    if not response.ok:
                        try:
                            detail = response.json()
                        except ValueError:
                            detail = response.text
                        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
                    response_json = response.json()
                    _atomic_write_json(response_path, response_json)

                _validate_response(
                    response=response_json,
                    question=question,
                    document_id=document_id,
                    top_k=top_k,
                )
                row["metrics"] = _score_response(question, response_json, ks)
                row["retrieved_hits"] = [_compact_hit(strategy, hit) for hit in response_json.get("hits", [])]
                if strategy == "hybrid_rerank":
                    row["context_chunks"] = [
                        _compact_context_chunk(item) for item in response_json.get("context_chunks", [])
                    ]
                row["status"] = "ok"
                rank = row["metrics"]["first_relevant_rank"]
                print(f"  OK first_relevant_rank={rank} RR={row['metrics']['reciprocal_rank']:.4f}")
            except Exception as exc:  # Save every failure; fail the overall run at the end.
                row["error"] = f"{type(exc).__name__}: {exc}"
                error_path = response_path.with_suffix(".error.json")
                _atomic_write_json(error_path, {
                    "question_id": qid,
                    "strategy": strategy,
                    "error": row["error"],
                })
                print(f"  ERROR {row['error']}")
            row["elapsed_seconds"] = time.perf_counter() - started_call
            all_rows.append(row)
            _atomic_write_json(output_dir / "all_results.partial.json", all_rows)

    aggregate: dict[str, Any] = {}
    for strategy in strategies:
        strategy_rows = [row for row in all_rows if row["strategy"] == strategy]
        aggregate[strategy] = {
            "overall": aggregate_scored_results(strategy_rows, ks=ks),
            "by_category": grouped_aggregates(strategy_rows, field="category", ks=ks),
            "by_difficulty": grouped_aggregates(strategy_rows, field="difficulty", ks=ks),
        }

    comparison = _comparison_report(
        split=args.split,
        strategies=strategies,
        aggregate=aggregate,
        ks=ks,
        config=config,
        dataset=dataset,
    )
    human = _human_report(
        rows=all_rows,
        split=args.split,
        strategies=strategies,
        ks=ks,
        comparison=comparison,
    )

    _atomic_write_json(output_dir / "all_results.json", all_rows)
    _atomic_write_json(output_dir / "aggregate_metrics.json", aggregate)
    _write_csv(output_dir / "per_question_results.csv", all_rows, ks)
    (output_dir / "comparison_report.txt").write_text(comparison, encoding="utf-8")
    (output_dir / "all_retrieval_evaluation_results.txt").write_text(human, encoding="utf-8")

    partial = output_dir / "all_results.partial.json"
    if partial.exists():
        partial.unlink()

    finished = datetime.now().astimezone()
    failures = [row for row in all_rows if row["status"] != "ok"]
    manifest.update({
        "run_status": "complete" if not failures else "failed",
        "finished_at": finished.isoformat(),
        "elapsed_seconds": (finished - started).total_seconds(),
        "failed_call_count": len(failures),
        "output_files": {
            "all_results": "all_results.json",
            "per_question_results": "per_question_results.csv",
            "aggregate_metrics": "aggregate_metrics.json",
            "comparison_report": "comparison_report.txt",
            "human_combined_report": "all_retrieval_evaluation_results.txt",
        },
    })
    _atomic_write_json(output_dir / "run_manifest.json", manifest)

    print()
    print(comparison.rstrip())
    print()
    print("Files to send back for review:")
    print(f"  {output_dir / 'all_retrieval_evaluation_results.txt'}")
    print(f"  {output_dir / 'aggregate_metrics.json'}")
    if failures:
        print(f"\nFAILED: {len(failures)} retrieval calls failed; aggregate metrics are marked invalid.")
        return 1
    print("\nPASS: every requested question/strategy completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
