from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
import re
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from app.config import settings
from app.schemas import (
    AgentChunkPlan,
    AgentDecisionRecord,
    AgentProviderStatus,
    AgentRequestDiagnostic,
    AgentRunDiagnostics,
    AgenticChunkingArtifact,
    AgenticChunkingConfig,
    AgenticChunkingSummary,
    AgenticRetrievalChunk,
    ChunkAgentCandidate,
    ChunkQualityReport,
    ChunkingArtifact,
    ResolvedStructureArtifact,
    RetrievalChunk,
)
from app.services.chunk_quality import analyze_chunk_quality
from app.services.chunking import estimate_tokens


class AgentProviderNotConfiguredError(RuntimeError):
    pass


class AgentProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str = "provider_error",
        http_status: int | None = None,
        duration_ms: int = 0,
        response_received: bool = False,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.http_status = http_status
        self.duration_ms = max(0, int(duration_ms))
        self.response_received = response_received
        self.provider_request_id = provider_request_id


_STRICT_GROQ_MODELS = {
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
}

# Manual schema keeps Groq strict-mode requirements explicit: every field is
# required and every object rejects additional properties.
_CHUNK_PLAN_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "decision": {"type": "string", "enum": ["keep", "group", "exclude", "needs_review"]},
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_ids": {"type": "array", "items": {"type": "string"}},
                    "context_chunk_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["chunk_ids", "context_chunk_ids"],
                "additionalProperties": False,
            },
        },
        "excluded_chunk_ids": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["candidate_id", "decision", "groups", "excluded_chunk_ids", "reason", "confidence"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """You are the semantic chunk-planning agent for a retrieval pipeline.

Your job is ONLY to decide how the supplied existing retrieval chunks should be grouped, kept, or (only when explicitly permitted by the candidate reason) excluded. You do not rewrite source text.

Objectives, in priority order:
1. Each retrieval unit should be independently understandable enough to answer a user query.
2. Preserve semantic hierarchy and necessary parent context.
3. Keep continuation text and strongly dependent list/subclause content together when possible.
4. Prefer semantic boundaries over arbitrary token boundaries.
5. Stay under the hard maximum token limit supplied in the context packet.
6. Preserve source provenance by referencing only supplied chunk IDs.

Hard constraints:
- Never invent a chunk ID.
- Never create or rewrite source text.
- Never move content across unrelated section boundaries.
- Every candidate chunk must be accounted for exactly once as primary content in a group or in excluded_chunk_ids.
- context_chunk_ids may repeat a supplied parent chunk as context, but they do not replace primary coverage.
- If a dependent child is separated from its parent, include the parent chunk in context_chunk_ids.
- Use decision=needs_review when the evidence is genuinely ambiguous.
- excluded_chunk_ids is allowed only for low-information content; never exclude substantive clauses, definitions, continuations, or hierarchy content.
- Return a short user-facing reason, not hidden reasoning or a chain of thought.

Examples:
A) Parent clause ending with ':' plus four short list items under the hard maximum -> one group containing parent + all four list item chunk IDs.
B) Parent clause plus many children above the hard maximum -> create multiple groups. Put the parent in the first group as primary content; for later child groups, repeat the parent ID in context_chunk_ids.
C) A short explanatory note tied to the previous definition -> group the definition chunk and note when the combined unit remains semantically coherent and under the hard maximum.
D) A tiny decorative/low-information fragment with reason low_information_content -> it may be excluded if it does not carry retrieval value.
"""


@dataclass(frozen=True)
class _AgentRunContext:
    model: str
    structured_output_mode: str


@dataclass(frozen=True)
class _GroqPlanResult:
    plan: AgentChunkPlan
    http_status: int
    duration_ms: int
    provider_request_id: str | None = None


def _output_mode(model: str) -> str:
    return "strict_json_schema" if model in _STRICT_GROQ_MODELS else "json_object"


def _is_global_provider_failure(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "http 401",
            "http 403",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "request failed",
            "timed out",
        )
    )


def _safe_provider_message(message: str) -> str:
    safe = message or ""
    api_key = (settings.groq_api_key or "").strip()
    if api_key:
        safe = safe.replace(api_key, "[REDACTED]")
    safe = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", safe, flags=re.IGNORECASE)
    return safe[:1600]


def _installed_groq_sdk_version() -> str | None:
    """Return the installed Groq SDK version without making it a hard import dependency at module import time.

    The project declares groq==1.7.0 in requirements.txt. Keeping this import lazy lets the
    rest of the document pipeline and tests start even when optional runtime dependencies
    have not yet been installed; provider calls then return an explicit configuration error.
    """
    try:
        sdk = importlib.import_module("groq")
    except ModuleNotFoundError:
        return None
    return str(getattr(sdk, "__version__", "unknown"))


def _load_groq_sdk() -> Any:
    try:
        return importlib.import_module("groq")
    except ModuleNotFoundError as exc:
        raise AgentProviderError(
            "Groq Python SDK is not installed. Install backend requirements (groq==1.7.0) and restart the API.",
            category="sdk_missing",
            response_received=False,
        ) from exc


def _groq_sdk_base_url() -> str:
    """Return the root URL expected by the official Groq Python SDK.

    The Groq SDK resource methods already include the `/openai/v1/...` API prefix.
    Older revisions of this project passed `https://api.groq.com/openai/v1` as the
    SDK base URL, which produced duplicated paths such as
    `/openai/v1/openai/v1/models`.  Keep backward compatibility with existing
    `.env` files by stripping one trailing `/openai/v1` segment.
    """
    raw = (settings.groq_base_url or "https://api.groq.com").strip().rstrip("/")
    suffix = "/openai/v1"
    if raw.lower().endswith(suffix):
        raw = raw[: -len(suffix)].rstrip("/")
    return raw or "https://api.groq.com"


def _groq_client() -> tuple[Any, Any]:
    api_key = (settings.groq_api_key or "").strip()
    if not api_key:
        raise AgentProviderNotConfiguredError(
            "GROQ_API_KEY is not configured. Add it to backend/.env before running Agentic Semantic v1."
        )
    sdk = _load_groq_sdk()
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": float(settings.groq_timeout_seconds),
        # Stage 5.1 owns retries so every retry is visible in the diagnostics panel.
        # The Groq SDK otherwise retries selected network/429/5xx failures internally.
        "max_retries": 0,
    }
    sdk_base_url = _groq_sdk_base_url()
    # Prefer Groq's built-in production endpoint when using the official host.
    # Only pass base_url for a custom gateway/proxy.
    if sdk_base_url.rstrip("/").lower() != "https://api.groq.com":
        kwargs["base_url"] = sdk_base_url
    client = sdk.Groq(**kwargs)
    return sdk, client


def _sdk_request_id_from_response(response: Any) -> str | None:
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is not None and hasattr(headers, "get"):
        return headers.get("x-request-id") or headers.get("x-groq-request-id")
    return None


def _sdk_request_id_from_completion(completion: Any) -> str | None:
    direct = getattr(completion, "_request_id", None)
    if direct:
        return str(direct)
    x_groq = getattr(completion, "x_groq", None)
    if x_groq is None:
        return None
    if isinstance(x_groq, dict):
        value = x_groq.get("id")
    else:
        value = getattr(x_groq, "id", None)
    return str(value) if value else None


def _is_cloudflare_browser_signature_block(detail: str) -> bool:
    lowered = (detail or "").lower()
    return (
        "browser_signature_banned" in lowered
        or "error 1010" in lowered
        or '"error_code":1010' in lowered.replace(" ", "")
    )


def _http_error_message(prefix: str, status_code: int | None, detail: str) -> str:
    lowered = (detail or "").lower()
    if status_code == 404 and "/openai/v1/openai/v1/" in lowered:
        return (
            f"{prefix} HTTP 404 because the Groq API prefix was duplicated. "
            "The official Groq SDK already adds /openai/v1 to resource requests. "
            "This build normalizes legacy GROQ_BASE_URL values automatically. "
            "Restart the backend and confirm the diagnostics panel shows SDK root https://api.groq.com. "
            f"Provider detail: {detail}"
        )
    if status_code == 403 and _is_cloudflare_browser_signature_block(detail):
        return (
            f"{prefix} HTTP 403 (Cloudflare Error 1010: browser signature blocked). "
            "This build uses the official Groq Python SDK transport instead of urllib. "
            "Confirm the diagnostics panel shows groq-python 1.7.0 and restart the backend after installing requirements. "
            "If Error 1010 still occurs with the SDK, check VPN/proxy/security middleware or try the same key/network from Groq's official SDK example. "
            f"Provider detail: {detail}"
        )
    return f"{prefix} HTTP {status_code}. {detail}".strip()


def _sdk_error_detail(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if body:
        try:
            return json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
        except Exception:
            return str(body)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            response_text = getattr(response, "text", "")
            if response_text:
                return str(response_text)
        except Exception:
            pass
    return str(exc)


def get_agent_provider_status(model: str | None = None, *, probe: bool = False) -> AgentProviderStatus:
    selected_model = model or settings.groq_model
    configured = bool(settings.groq_api_key and settings.groq_api_key.strip())
    base_url = _groq_sdk_base_url()
    sdk_version = _installed_groq_sdk_version()
    base = AgentProviderStatus(
        configured=configured,
        model=selected_model,
        base_url=base_url,
        structured_output_mode=_output_mode(selected_model),
        sdk_version=sdk_version,
        reachable=False if probe and not configured else None,
        model_available=None,
        checked_at=datetime.now(timezone.utc) if probe else None,
        message=("GROQ_API_KEY is not configured." if probe and not configured else ""),
    )
    if not probe or not configured:
        return base

    started = perf_counter()
    checked_at = datetime.now(timezone.utc)
    try:
        sdk, client = _groq_client()
        models_response = client.models.list()
        latency_ms = round((perf_counter() - started) * 1000)
        models = {
            str(getattr(item, "id", ""))
            for item in getattr(models_response, "data", [])
            if getattr(item, "id", None)
        }
        model_available = selected_model in models
        version = str(getattr(sdk, "__version__", sdk_version or "unknown"))
        message = (
            f"Groq is reachable through groq-python {version} and the selected model is available."
            if model_available
            else f"Groq is reachable through groq-python {version}, but the selected model was not returned by the Models API."
        )
        return AgentProviderStatus(
            configured=True,
            model=selected_model,
            base_url=base_url,
            structured_output_mode=_output_mode(selected_model),
            sdk_version=version,
            reachable=True,
            model_available=model_available,
            checked_at=checked_at,
            http_status=200,
            latency_ms=latency_ms,
            message=message,
        )
    except AgentProviderNotConfiguredError as exc:
        return AgentProviderStatus(
            configured=False,
            model=selected_model,
            base_url=base_url,
            structured_output_mode=_output_mode(selected_model),
            sdk_version=sdk_version,
            reachable=False,
            model_available=None,
            checked_at=checked_at,
            http_status=None,
            latency_ms=round((perf_counter() - started) * 1000),
            message=_safe_provider_message(str(exc)),
        )
    except AgentProviderError as exc:
        return AgentProviderStatus(
            configured=True,
            model=selected_model,
            base_url=base_url,
            structured_output_mode=_output_mode(selected_model),
            sdk_version=sdk_version,
            reachable=False,
            model_available=None,
            checked_at=checked_at,
            http_status=exc.http_status,
            latency_ms=exc.duration_ms or round((perf_counter() - started) * 1000),
            message=_safe_provider_message(str(exc)),
        )
    except Exception as exc:
        # SDK exception classes are loaded lazily because the SDK itself is a runtime dependency.
        try:
            sdk = importlib.import_module("groq")
        except ModuleNotFoundError:
            sdk = None
        duration_ms = round((perf_counter() - started) * 1000)
        if sdk is not None and isinstance(exc, getattr(sdk, "APIStatusError", ())):
            status_code = getattr(exc, "status_code", None)
            request_id = _sdk_request_id_from_response(getattr(exc, "response", None))
            detail = _sdk_error_detail(exc)
            suffix = f" Request ID: {request_id}." if request_id else ""
            message = _http_error_message("Groq connectivity check returned", status_code, detail) + suffix
            return AgentProviderStatus(
                configured=True,
                model=selected_model,
                base_url=base_url,
                structured_output_mode=_output_mode(selected_model),
                sdk_version=str(getattr(sdk, "__version__", sdk_version or "unknown")),
                reachable=False,
                model_available=None,
                checked_at=checked_at,
                http_status=status_code,
                latency_ms=duration_ms,
                message=_safe_provider_message(message),
            )
        if sdk is not None and isinstance(exc, (getattr(sdk, "APIConnectionError", ()), getattr(sdk, "APITimeoutError", ()))):
            return AgentProviderStatus(
                configured=True,
                model=selected_model,
                base_url=base_url,
                structured_output_mode=_output_mode(selected_model),
                sdk_version=str(getattr(sdk, "__version__", sdk_version or "unknown")),
                reachable=False,
                model_available=None,
                checked_at=checked_at,
                http_status=None,
                latency_ms=duration_ms,
                message=_safe_provider_message(f"Groq connectivity check failed: {exc}"),
            )
        return AgentProviderStatus(
            configured=True,
            model=selected_model,
            base_url=base_url,
            structured_output_mode=_output_mode(selected_model),
            sdk_version=sdk_version,
            reachable=False,
            model_available=None,
            checked_at=checked_at,
            http_status=None,
            latency_ms=duration_ms,
            message=_safe_provider_message(f"Groq connectivity check failed: {exc}"),
        )


def _compact_outline(resolved: ResolvedStructureArtifact, current_path: list[str]) -> list[str]:
    top_level = []
    for section in resolved.structure.sections:
        if section.parent_section_id is None:
            title = " ".join(section.title.split())
            if title and title not in top_level:
                top_level.append(title)
        if len(top_level) >= 30:
            break
    # Always retain the current path even when it is nested and not part of the
    # top-level outline sample.
    for title in current_path:
        normalized = " ".join(title.split())
        if normalized and normalized not in top_level:
            top_level.append(normalized)
    return top_level


def _candidate_packet(
    *,
    candidate: ChunkAgentCandidate,
    baseline: ChunkingArtifact,
    resolved: ResolvedStructureArtifact,
    validation_errors: list[str] | None = None,
) -> dict:
    chunk_by_id = {chunk.chunk_id: chunk for chunk in baseline.chunks}
    candidate_chunks = [chunk_by_id[chunk_id] for chunk_id in candidate.chunk_ids if chunk_id in chunk_by_id]
    candidate_ids = set(candidate.chunk_ids)
    chunk_by_element = {
        element_id: chunk.chunk_id
        for chunk in baseline.chunks
        for element_id in chunk.source_element_ids
    }
    relationships = []
    for relation in resolved.structure.relationships:
        source_chunk = chunk_by_element.get(relation.source_element_id)
        target_chunk = chunk_by_element.get(relation.target_element_id)
        if not source_chunk or not target_chunk:
            continue
        if source_chunk in candidate_ids or target_chunk in candidate_ids:
            relationships.append({
                "type": relation.type,
                "source_chunk_id": source_chunk,
                "target_chunk_id": target_chunk,
                "evidence": relation.evidence,
            })
        if len(relationships) >= 80:
            break

    def neighbor(chunk_id: str | None) -> dict | None:
        if not chunk_id:
            return None
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            return None
        return {
            "chunk_id": chunk.chunk_id,
            "semantic_type": chunk.semantic_type,
            "token_count": chunk.token_count,
            "pages": chunk.pages,
            "section_path": chunk.section_path,
            "content_text": chunk.content_text,
        }

    return {
        "document_context": {
            "title": resolved.structure.title,
            "subtitle": resolved.structure.subtitle,
            "document_outline": _compact_outline(resolved, candidate.section_path),
            "current_section_path": candidate.section_path,
        },
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "reason_codes": candidate.reason_codes,
            "severity": candidate.severity,
            "estimated_tokens": candidate.estimated_tokens,
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "semantic_type": chunk.semantic_type,
                    "token_count": chunk.token_count,
                    "pages": chunk.pages,
                    "section_path": chunk.section_path,
                    "content_text": chunk.content_text,
                    "source_element_ids": chunk.source_element_ids,
                }
                for chunk in candidate_chunks
            ],
            "relationships": relationships,
            "previous_neighbor": neighbor(candidate.previous_chunk_id),
            "next_neighbor": neighbor(candidate.next_chunk_id),
        },
        "constraints": {
            "target_tokens": baseline.config.target_tokens,
            "max_tokens": baseline.config.max_tokens,
            "preserve_section_context": baseline.config.preserve_section_context,
            "never_rewrite_source_text": True,
            "allowed_chunk_ids": candidate.chunk_ids,
        },
        "validation_feedback": validation_errors or [],
        "required_output": {
            "candidate_id": "must exactly match candidate.candidate_id",
            "decision": "keep | group | exclude | needs_review",
            "groups": [{"chunk_ids": ["..."], "context_chunk_ids": ["..."]}],
            "excluded_chunk_ids": [],
            "reason": "concise user-facing rationale",
            "confidence": "number from 0 to 1",
        },
    }


def _groq_plan_request(packet: dict, *, model: str) -> _GroqPlanResult:
    mode = _output_mode(model)
    if mode == "strict_json_schema":
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "chunk_plan",
                "strict": True,
                "schema": _CHUNK_PLAN_JSON_SCHEMA,
            },
        }
    else:
        response_format = {"type": "json_object"}

    request_params: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Return only the ChunkPlan JSON object for this context packet.\n\n"
                    + json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ],
        "temperature": 0.1,
        "response_format": response_format,
    }
    # GPT-OSS exposes reasoning separately. We do not persist or need chain-of-thought
    # for chunk planning, so ask Groq not to include it in the API response.
    if model in _STRICT_GROQ_MODELS:
        request_params["include_reasoning"] = False

    started = perf_counter()
    try:
        sdk, client = _groq_client()
        completion = client.chat.completions.create(**request_params)
    except AgentProviderNotConfiguredError:
        raise
    except AgentProviderError:
        raise
    except Exception as exc:
        duration_ms = round((perf_counter() - started) * 1000)
        try:
            sdk = importlib.import_module("groq")
        except ModuleNotFoundError:
            raise AgentProviderError(
                "Groq Python SDK is not installed. Install backend requirements (groq==1.7.0) and restart the API.",
                category="sdk_missing",
                duration_ms=duration_ms,
                response_received=False,
            ) from exc

        if isinstance(exc, getattr(sdk, "APIStatusError", ())):
            status_code = getattr(exc, "status_code", None)
            response = getattr(exc, "response", None)
            request_id = _sdk_request_id_from_response(response)
            detail = _sdk_error_detail(exc)
            raise AgentProviderError(
                _safe_provider_message(_http_error_message("Groq returned", status_code, detail)),
                category="http_error",
                http_status=status_code,
                duration_ms=duration_ms,
                response_received=True,
                provider_request_id=request_id,
            ) from exc
        if isinstance(exc, getattr(sdk, "APITimeoutError", ())):
            raise AgentProviderError(
                _safe_provider_message(f"Groq request timed out: {exc}"),
                category="timeout_error",
                http_status=None,
                duration_ms=duration_ms,
                response_received=False,
            ) from exc
        if isinstance(exc, getattr(sdk, "APIConnectionError", ())):
            raise AgentProviderError(
                _safe_provider_message(f"Groq request failed: {exc}"),
                category="network_error",
                http_status=None,
                duration_ms=duration_ms,
                response_received=False,
            ) from exc
        if isinstance(exc, getattr(sdk, "APIError", ())):
            raise AgentProviderError(
                _safe_provider_message(f"Groq SDK error: {exc}"),
                category="provider_error",
                http_status=None,
                duration_ms=duration_ms,
                response_received=False,
            ) from exc
        raise AgentProviderError(
            _safe_provider_message(f"Unexpected Groq SDK error: {exc}"),
            category="provider_error",
            http_status=None,
            duration_ms=duration_ms,
            response_received=False,
        ) from exc

    duration_ms = round((perf_counter() - started) * 1000)
    try:
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("Groq returned an empty assistant message")
        decoded = json.loads(content)
        plan = AgentChunkPlan.model_validate(decoded)
        return _GroqPlanResult(
            plan=plan,
            http_status=200,
            duration_ms=duration_ms,
            provider_request_id=_sdk_request_id_from_completion(completion),
        )
    except (IndexError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        raise AgentProviderError(
            _safe_provider_message(f"Groq returned an invalid ChunkPlan payload: {exc}"),
            category="parse_error",
            http_status=200,
            duration_ms=duration_ms,
            response_received=True,
            provider_request_id=_sdk_request_id_from_completion(completion),
        ) from exc


def _section_context(chunk: RetrievalChunk, baseline: ChunkingArtifact) -> str:
    if not baseline.config.preserve_section_context or not chunk.section_path:
        return ""
    return f"Section: {' > '.join(chunk.section_path)}"


def _compose_group_text(
    *,
    primary_ids: list[str],
    context_ids: list[str],
    chunk_by_id: dict[str, RetrievalChunk],
    baseline: ChunkingArtifact,
) -> tuple[str, str, str, list[RetrievalChunk]]:
    primary = [chunk_by_id[chunk_id] for chunk_id in primary_ids if chunk_id in chunk_by_id]
    context = [chunk_by_id[chunk_id] for chunk_id in context_ids if chunk_id in chunk_by_id]
    if not primary:
        return "", "", "", []

    content_text = "\n\n".join(chunk.content_text.strip() for chunk in primary if chunk.content_text.strip())
    context_parts: list[str] = []
    section = _section_context(primary[0], baseline)
    if section:
        context_parts.append(section)
    if context:
        parent_text = "\n\n".join(chunk.content_text.strip() for chunk in context if chunk.content_text.strip())
        if parent_text:
            context_parts.append(f"Parent context:\n{parent_text}")
    context_text = "\n\n".join(context_parts)
    text = f"{context_text}\n\n{content_text}".strip() if context_text else content_text.strip()
    return text, content_text, context_text, [*primary, *context]


def _parent_chunk_pairs(
    candidate: ChunkAgentCandidate,
    baseline: ChunkingArtifact,
    resolved: ResolvedStructureArtifact,
) -> set[tuple[str, str]]:
    chunk_by_element = {
        element_id: chunk.chunk_id
        for chunk in baseline.chunks
        for element_id in chunk.source_element_ids
    }
    allowed = set(candidate.chunk_ids)
    pairs: set[tuple[str, str]] = set()
    for relation in resolved.structure.relationships:
        if relation.type != "parent_of":
            continue
        parent = chunk_by_element.get(relation.source_element_id)
        child = chunk_by_element.get(relation.target_element_id)
        if parent in allowed and child in allowed and parent != child:
            pairs.add((parent, child))
    return pairs


def validate_agent_plan(
    *,
    plan: AgentChunkPlan,
    candidate: ChunkAgentCandidate,
    baseline: ChunkingArtifact,
    resolved: ResolvedStructureArtifact,
) -> list[str]:
    errors: list[str] = []
    allowed = set(candidate.chunk_ids)
    chunk_by_id = {chunk.chunk_id: chunk for chunk in baseline.chunks}

    if plan.candidate_id != candidate.candidate_id:
        errors.append("candidate_id does not match the supplied candidate")

    if plan.decision == "needs_review":
        if plan.groups or plan.excluded_chunk_ids:
            errors.append("needs_review must return empty groups and excluded_chunk_ids")
        return errors

    primary_ids: list[str] = []
    for group_index, group in enumerate(plan.groups, start=1):
        if not group.chunk_ids:
            errors.append(f"group {group_index} has no primary chunk_ids")
        unknown = (set(group.chunk_ids) | set(group.context_chunk_ids)) - allowed
        if unknown:
            errors.append(f"group {group_index} references unknown chunk IDs: {sorted(unknown)}")
        if set(group.chunk_ids) & set(group.context_chunk_ids):
            errors.append(f"group {group_index} repeats a chunk as both primary and context")
        primary_ids.extend(group.chunk_ids)

    unknown_excluded = set(plan.excluded_chunk_ids) - allowed
    if unknown_excluded:
        errors.append(f"excluded_chunk_ids contains unknown chunk IDs: {sorted(unknown_excluded)}")

    if len(primary_ids) != len(set(primary_ids)):
        errors.append("a candidate chunk appears as primary content in more than one group")
    if set(primary_ids) & set(plan.excluded_chunk_ids):
        errors.append("a chunk cannot be both primary content and excluded")

    covered = set(primary_ids) | set(plan.excluded_chunk_ids)
    if covered != allowed:
        missing = sorted(allowed - covered)
        extra = sorted(covered - allowed)
        if missing:
            errors.append(f"candidate chunks are missing from the plan: {missing}")
        if extra:
            errors.append(f"plan contains chunks outside the candidate: {extra}")

    if plan.decision == "keep":
        if plan.excluded_chunk_ids:
            errors.append("keep cannot exclude chunks")
        if any(len(group.chunk_ids) != 1 or group.context_chunk_ids for group in plan.groups):
            errors.append("keep must preserve each candidate chunk as a singleton without repeated context")
    elif plan.decision == "group":
        if plan.excluded_chunk_ids:
            errors.append("group cannot exclude chunks")
        if not plan.groups:
            errors.append("group requires at least one output group")
    elif plan.decision == "exclude":
        if set(candidate.reason_codes) != {"low_information_content"}:
            errors.append("exclude is allowed only for low_information_content candidates")
        if plan.groups:
            errors.append("exclude must not return output groups")
        if set(plan.excluded_chunk_ids) != allowed:
            errors.append("exclude must explicitly exclude every candidate chunk")

    parent_pairs = _parent_chunk_pairs(candidate, baseline, resolved)
    group_by_primary: dict[str, int] = {}
    context_by_group: dict[int, set[str]] = {}
    for index, group in enumerate(plan.groups):
        context_by_group[index] = set(group.context_chunk_ids)
        for chunk_id in group.chunk_ids:
            group_by_primary[chunk_id] = index
    for parent, child in parent_pairs:
        child_group = group_by_primary.get(child)
        parent_group = group_by_primary.get(parent)
        if child_group is None or parent_group is None:
            continue
        if child_group != parent_group and parent not in context_by_group.get(child_group, set()):
            errors.append(
                f"dependent child {child} is separated from parent {parent} without repeating the parent in context_chunk_ids"
            )

    for index, group in enumerate(plan.groups, start=1):
        text, _, _, _ = _compose_group_text(
            primary_ids=group.chunk_ids,
            context_ids=group.context_chunk_ids,
            chunk_by_id=chunk_by_id,
            baseline=baseline,
        )
        token_count = estimate_tokens(text)
        if token_count <= 0:
            errors.append(f"group {index} produces empty retrieval text")
        if token_count > baseline.config.max_tokens:
            errors.append(
                f"group {index} exceeds max_tokens ({token_count} > {baseline.config.max_tokens})"
            )

    return errors


def _agent_chunk_id(document_id: str, index: int, text: str, source_chunk_ids: list[str]) -> str:
    digest = sha256("\n".join([*source_chunk_ids, text]).encode("utf-8")).hexdigest()[:10]
    return f"{document_id}-a{index:04d}-{digest}"


def _copy_baseline_chunk(
    chunk: RetrievalChunk,
    *,
    candidate_id: str | None = None,
) -> dict:
    return {
        "semantic_type": chunk.semantic_type,
        "text": chunk.text,
        "content_text": chunk.content_text,
        "context_text": chunk.context_text,
        "token_count": chunk.token_count,
        "pages": chunk.pages,
        "section_path": chunk.section_path,
        "source_element_ids": chunk.source_element_ids,
        "source_span_ids": chunk.source_span_ids,
        "source_block_ids": chunk.source_block_ids,
        "source_table_ids": chunk.source_table_ids,
        "relationship_ids": chunk.relationship_ids,
        "split_part": chunk.split_part,
        "split_total": chunk.split_total,
        "source_chunk_ids": [chunk.chunk_id],
        "agent_modified": False,
        "agent_candidate_id": candidate_id,
    }


def _group_draft(
    *,
    group,
    candidate: ChunkAgentCandidate,
    baseline: ChunkingArtifact,
) -> dict:
    chunk_by_id = {chunk.chunk_id: chunk for chunk in baseline.chunks}
    text, content_text, context_text, source_chunks = _compose_group_text(
        primary_ids=group.chunk_ids,
        context_ids=group.context_chunk_ids,
        chunk_by_id=chunk_by_id,
        baseline=baseline,
    )
    source_chunk_ids = list(dict.fromkeys([*group.chunk_ids, *group.context_chunk_ids]))
    semantic_types = {chunk.semantic_type for chunk in source_chunks if chunk.chunk_id in group.chunk_ids}
    semantic_type = next(iter(semantic_types)) if len(semantic_types) == 1 else "mixed"
    pages = sorted({page for chunk in source_chunks for page in chunk.pages})
    section_path = source_chunks[0].section_path if source_chunks and all(chunk.section_path == source_chunks[0].section_path for chunk in source_chunks) else candidate.section_path
    return {
        "semantic_type": semantic_type,
        "text": text,
        "content_text": content_text,
        "context_text": context_text,
        "token_count": estimate_tokens(text),
        "pages": pages,
        "section_path": section_path,
        "source_element_ids": list(dict.fromkeys(element_id for chunk in source_chunks for element_id in chunk.source_element_ids)),
        "source_span_ids": list(dict.fromkeys(span_id for chunk in source_chunks for span_id in chunk.source_span_ids)),
        "source_block_ids": list(dict.fromkeys(block_id for chunk in source_chunks for block_id in chunk.source_block_ids)),
        "source_table_ids": list(dict.fromkeys(table_id for chunk in source_chunks for table_id in chunk.source_table_ids)),
        "relationship_ids": list(dict.fromkeys(relation_id for chunk in source_chunks for relation_id in chunk.relationship_ids)),
        "split_part": None,
        "split_total": None,
        "source_chunk_ids": source_chunk_ids,
        "agent_modified": len(group.chunk_ids) > 1 or bool(group.context_chunk_ids),
        "agent_candidate_id": candidate.candidate_id,
    }


def build_agentic_chunking_artifact(
    *,
    baseline: ChunkingArtifact,
    resolved: ResolvedStructureArtifact,
    config: AgenticChunkingConfig | None = None,
    planner: Callable[[dict, str], AgentChunkPlan] | None = None,
) -> AgenticChunkingArtifact:
    run_started_at = datetime.now(timezone.utc)
    run_started_clock = perf_counter()
    run_id = f"agentic-{uuid4().hex[:12]}"

    config = config or AgenticChunkingConfig()
    model = config.model or settings.groq_model
    run_context = _AgentRunContext(model=model, structured_output_mode=_output_mode(model))
    quality = analyze_chunk_quality(baseline=baseline, resolved=resolved)
    if planner is None and quality.agent_candidates and not get_agent_provider_status(model).configured:
        raise AgentProviderNotConfiguredError(
            "GROQ_API_KEY is not configured. Add it to backend/.env before running Agentic Semantic v1."
        )

    chunk_by_id = {chunk.chunk_id: chunk for chunk in baseline.chunks}
    candidate_by_chunk = {
        chunk_id: candidate
        for candidate in quality.agent_candidates
        for chunk_id in candidate.chunk_ids
    }
    first_index_by_candidate = {
        candidate.candidate_id: min(chunk_by_id[chunk_id].chunk_index for chunk_id in candidate.chunk_ids)
        for candidate in quality.agent_candidates
        if candidate.chunk_ids
    }

    decisions: list[AgentDecisionRecord] = []
    accepted_plans: dict[str, AgentChunkPlan] = {}
    processed_candidates = 0
    provider_blocked_message: str | None = None
    run_request_diagnostics: list[AgentRequestDiagnostic] = []
    unique_candidates_sent: set[str] = set()

    for candidate_number, candidate in enumerate(quality.agent_candidates):
        if candidate_number >= config.max_agent_candidates:
            decisions.append(AgentDecisionRecord(
                candidate_id=candidate.candidate_id,
                reason_codes=candidate.reason_codes,
                provider="groq",
                model=model,
                structured_output_mode=run_context.structured_output_mode,
                attempts=0,
                status="fallback",
                validation_errors=[],
                request_diagnostics=[],
                message="Agent candidate limit reached; deterministic baseline chunks were preserved for this candidate.",
            ))
            continue

        if provider_blocked_message and planner is None:
            decisions.append(AgentDecisionRecord(
                candidate_id=candidate.candidate_id,
                reason_codes=candidate.reason_codes,
                provider="groq",
                model=model,
                structured_output_mode=run_context.structured_output_mode,
                attempts=0,
                status="fallback" if config.fallback_to_deterministic else "error",
                validation_errors=[provider_blocked_message],
                request_diagnostics=[],
                message="Groq was unavailable for an earlier candidate, so additional API calls were skipped and the deterministic baseline was preserved.",
            ))
            continue

        processed_candidates += 1
        unique_candidates_sent.add(candidate.candidate_id)
        validation_feedback: list[str] = []
        plan: AgentChunkPlan | None = None
        attempts = 0
        provider_error: str | None = None
        candidate_request_diagnostics: list[AgentRequestDiagnostic] = []

        for attempt in range(config.max_retries + 1):
            attempts = attempt + 1
            packet = _candidate_packet(
                candidate=candidate,
                baseline=baseline,
                resolved=resolved,
                validation_errors=validation_feedback,
            )
            attempt_started = perf_counter()
            http_status: int | None = None
            response_received = False
            provider_request_id: str | None = None
            request_duration_ms = 0

            try:
                if planner is not None:
                    proposed = planner(packet, model)
                    request_duration_ms = round((perf_counter() - attempt_started) * 1000)
                    response_received = True
                    plan = proposed if isinstance(proposed, AgentChunkPlan) else AgentChunkPlan.model_validate(proposed)
                else:
                    groq_result = _groq_plan_request(packet, model=model)
                    if isinstance(groq_result, _GroqPlanResult):
                        plan = groq_result.plan
                        http_status = groq_result.http_status
                        request_duration_ms = groq_result.duration_ms
                        provider_request_id = groq_result.provider_request_id
                        response_received = True
                    else:
                        # Backward-compatible test/mocking path: callers that monkeypatch
                        # _groq_plan_request may still return AgentChunkPlan directly.
                        request_duration_ms = round((perf_counter() - attempt_started) * 1000)
                        response_received = True
                        plan = groq_result if isinstance(groq_result, AgentChunkPlan) else AgentChunkPlan.model_validate(groq_result)
            except AgentProviderNotConfiguredError as exc:
                provider_error = _safe_provider_message(str(exc))
                validation_feedback = [provider_error]
                plan = None
                request_duration_ms = round((perf_counter() - attempt_started) * 1000)
                diagnostic = AgentRequestDiagnostic(
                    candidate_id=candidate.candidate_id,
                    attempt=attempts,
                    status="provider_error",
                    http_status=None,
                    duration_ms=request_duration_ms,
                    response_received=False,
                    validation_status="not_run",
                    message=provider_error,
                )
                candidate_request_diagnostics.append(diagnostic)
                run_request_diagnostics.append(diagnostic)
                continue
            except AgentProviderError as exc:
                provider_error = _safe_provider_message(str(exc))
                validation_feedback = [provider_error]
                plan = None
                diagnostic = AgentRequestDiagnostic(
                    candidate_id=candidate.candidate_id,
                    attempt=attempts,
                    status="parse_error" if exc.category == "parse_error" else "provider_error",
                    http_status=exc.http_status,
                    duration_ms=exc.duration_ms or round((perf_counter() - attempt_started) * 1000),
                    response_received=exc.response_received,
                    validation_status="not_run",
                    provider_request_id=exc.provider_request_id,
                    message=provider_error,
                )
                candidate_request_diagnostics.append(diagnostic)
                run_request_diagnostics.append(diagnostic)
                continue
            except (ValidationError, ValueError) as exc:
                provider_error = _safe_provider_message(str(exc))
                validation_feedback = [provider_error]
                plan = None
                request_duration_ms = round((perf_counter() - attempt_started) * 1000)
                diagnostic = AgentRequestDiagnostic(
                    candidate_id=candidate.candidate_id,
                    attempt=attempts,
                    status="parse_error",
                    http_status=http_status,
                    duration_ms=request_duration_ms,
                    response_received=response_received,
                    validation_status="not_run",
                    provider_request_id=provider_request_id,
                    message=provider_error,
                )
                candidate_request_diagnostics.append(diagnostic)
                run_request_diagnostics.append(diagnostic)
                continue

            validation_feedback = validate_agent_plan(
                plan=plan,
                candidate=candidate,
                baseline=baseline,
                resolved=resolved,
            )
            if validation_feedback:
                diagnostic = AgentRequestDiagnostic(
                    candidate_id=candidate.candidate_id,
                    attempt=attempts,
                    status="validation_error",
                    http_status=http_status,
                    duration_ms=request_duration_ms,
                    response_received=response_received,
                    validation_status="failed",
                    provider_request_id=provider_request_id,
                    message="; ".join(validation_feedback)[:1600],
                )
                candidate_request_diagnostics.append(diagnostic)
                run_request_diagnostics.append(diagnostic)
                continue

            diagnostic = AgentRequestDiagnostic(
                candidate_id=candidate.candidate_id,
                attempt=attempts,
                status="success",
                http_status=http_status,
                duration_ms=request_duration_ms,
                response_received=response_received,
                validation_status="passed",
                provider_request_id=provider_request_id,
                message="ChunkPlan parsed and passed deterministic validation.",
            )
            candidate_request_diagnostics.append(diagnostic)
            run_request_diagnostics.append(diagnostic)
            break

        if plan is None or validation_feedback:
            status = "fallback" if config.fallback_to_deterministic else "error"
            if provider_error and _is_global_provider_failure(provider_error):
                provider_blocked_message = provider_error
            decisions.append(AgentDecisionRecord(
                candidate_id=candidate.candidate_id,
                reason_codes=candidate.reason_codes,
                provider="groq",
                model=model,
                structured_output_mode=run_context.structured_output_mode,
                attempts=attempts,
                status=status,
                plan=plan,
                validation_errors=validation_feedback,
                request_diagnostics=candidate_request_diagnostics,
                message=(provider_error or "The agent plan remained invalid after retries. Deterministic chunks were preserved.") if status == "fallback" else (provider_error or "The agent plan remained invalid after retries."),
            ))
            continue

        if plan.decision == "needs_review" or plan.confidence < config.minimum_confidence:
            decisions.append(AgentDecisionRecord(
                candidate_id=candidate.candidate_id,
                reason_codes=candidate.reason_codes,
                provider="groq",
                model=model,
                structured_output_mode=run_context.structured_output_mode,
                attempts=attempts,
                status="needs_review",
                plan=plan,
                validation_errors=[],
                request_diagnostics=candidate_request_diagnostics,
                message=(
                    "The planner requested human review."
                    if plan.decision == "needs_review"
                    else f"Planner confidence {plan.confidence:.2f} is below the configured threshold {config.minimum_confidence:.2f}."
                ),
            ))
            continue

        accepted_plans[candidate.candidate_id] = plan
        decisions.append(AgentDecisionRecord(
            candidate_id=candidate.candidate_id,
            reason_codes=candidate.reason_codes,
            provider="groq",
            model=model,
            structured_output_mode=run_context.structured_output_mode,
            attempts=attempts,
            status="accepted",
            plan=plan,
            validation_errors=[],
            request_diagnostics=candidate_request_diagnostics,
            message=plan.reason,
        ))

    deterministic_exclusions = set(quality.deterministic_exclusion_chunk_ids)
    decision_by_candidate = {decision.candidate_id: decision for decision in decisions}
    drafts: list[dict] = []
    emitted_candidates: set[str] = set()

    for chunk in sorted(baseline.chunks, key=lambda item: item.chunk_index):
        if chunk.chunk_id in deterministic_exclusions:
            continue
        candidate = candidate_by_chunk.get(chunk.chunk_id)
        if candidate is None:
            drafts.append(_copy_baseline_chunk(chunk))
            continue
        if candidate.candidate_id in emitted_candidates:
            continue
        if chunk.chunk_index != first_index_by_candidate[candidate.candidate_id]:
            continue
        emitted_candidates.add(candidate.candidate_id)

        plan = accepted_plans.get(candidate.candidate_id)
        decision = decision_by_candidate.get(candidate.candidate_id)
        if plan is None or decision is None or decision.status != "accepted":
            for candidate_chunk_id in candidate.chunk_ids:
                baseline_chunk = chunk_by_id[candidate_chunk_id]
                drafts.append(_copy_baseline_chunk(baseline_chunk, candidate_id=candidate.candidate_id))
            continue

        if plan.decision == "exclude":
            continue
        for group in plan.groups:
            drafts.append(_group_draft(group=group, candidate=candidate, baseline=baseline))

    final_chunks: list[AgenticRetrievalChunk] = []
    for index, draft in enumerate(drafts):
        text = draft["text"]
        if not text.strip():
            continue
        token_count = estimate_tokens(text)
        if token_count > baseline.config.max_tokens:
            raise ValueError(
                f"Agentic chunk generation exceeded max_tokens ({token_count} > {baseline.config.max_tokens})."
            )
        final_chunks.append(AgenticRetrievalChunk(
            chunk_id=_agent_chunk_id(baseline.document_id, index, text, draft["source_chunk_ids"]),
            chunk_index=index,
            semantic_type=draft["semantic_type"],
            text=text,
            content_text=draft["content_text"],
            context_text=draft["context_text"],
            token_count=token_count,
            pages=draft["pages"],
            section_path=draft["section_path"],
            source_element_ids=draft["source_element_ids"],
            source_span_ids=draft["source_span_ids"],
            source_block_ids=draft["source_block_ids"],
            source_table_ids=draft["source_table_ids"],
            relationship_ids=draft["relationship_ids"],
            split_part=draft["split_part"],
            split_total=draft["split_total"],
            source_chunk_ids=draft["source_chunk_ids"],
            agent_modified=draft["agent_modified"],
            agent_candidate_id=draft["agent_candidate_id"],
        ))

    accepted_count = sum(decision.status == "accepted" for decision in decisions)
    fallback_count = sum(decision.status == "fallback" for decision in decisions)
    review_required_count = sum(decision.status == "needs_review" for decision in decisions)
    error_count = sum(decision.status == "error" for decision in decisions)
    token_counts = [chunk.token_count for chunk in final_chunks]
    modified_count = sum(chunk.agent_modified for chunk in final_chunks)
    ready_for_stage6 = fallback_count == 0 and review_required_count == 0 and error_count == 0

    warnings: list[str] = []
    if quality.deterministic_exclusion_chunk_ids:
        warnings.append(
            f"Stage 5.1 excluded {len(quality.deterministic_exclusion_chunk_ids)} navigation-only baseline chunks from the agentic retrieval view."
        )
    if fallback_count:
        warnings.append(
            f"{fallback_count} agent candidates fell back to deterministic baseline chunks; review before Stage 6."
        )
    if review_required_count:
        warnings.append(
            f"{review_required_count} agent candidates require human review before Stage 6 is recommended."
        )
    warnings.append(
        "The LLM plans chunk membership only. Source text is assembled deterministically from existing Stage 5 chunks and is never rewritten by the model."
    )

    summary = AgenticChunkingSummary(
        baseline_chunk_count=len(baseline.chunks),
        final_chunk_count=len(final_chunks),
        deterministic_excluded_count=len(quality.deterministic_exclusion_chunk_ids),
        agent_candidate_count=len(quality.agent_candidates),
        agent_processed_count=processed_candidates,
        accepted_count=accepted_count,
        fallback_count=fallback_count,
        review_required_count=review_required_count,
        error_count=error_count,
        modified_chunk_count=modified_count,
        estimated_token_count=sum(token_counts),
        average_chunk_tokens=round(sum(token_counts) / len(token_counts), 2) if token_counts else 0.0,
        max_chunk_tokens=max(token_counts, default=0),
        ready_for_stage6=ready_for_stage6,
    )

    provider_error_count = sum(item.status in {"provider_error", "parse_error"} for item in run_request_diagnostics)
    validation_error_count = sum(item.status == "validation_error" for item in run_request_diagnostics)
    responses_received = sum(item.response_received for item in run_request_diagnostics)
    retries_total = sum(max(0, decision.attempts - 1) for decision in decisions)
    skipped_count = sum(decision.attempts == 0 for decision in decisions)
    http_status_counts: dict[str, int] = {}
    for item in run_request_diagnostics:
        if item.http_status is not None:
            key = str(item.http_status)
            http_status_counts[key] = http_status_counts.get(key, 0) + 1

    if not quality.agent_candidates:
        run_status = "no_candidates"
    elif error_count:
        run_status = "failed"
    elif fallback_count:
        run_status = "completed_with_fallback"
    elif review_required_count:
        run_status = "needs_review"
    else:
        run_status = "success"

    last_error = next(
        (
            item.message
            for item in reversed(run_request_diagnostics)
            if item.status in {"provider_error", "parse_error", "validation_error"} and item.message
        ),
        None,
    )
    run_finished_at = datetime.now(timezone.utc)
    run_diagnostics = AgentRunDiagnostics(
        run_id=run_id,
        status=run_status,
        provider="groq",
        model=model,
        structured_output_mode=run_context.structured_output_mode,
        sdk_version=_installed_groq_sdk_version(),
        started_at=run_started_at,
        finished_at=run_finished_at,
        duration_ms=round((perf_counter() - run_started_clock) * 1000),
        candidates_available=len(quality.agent_candidates),
        candidates_sent=len(unique_candidates_sent),
        requests_sent=len(run_request_diagnostics),
        responses_received=responses_received,
        accepted_count=accepted_count,
        retries_total=retries_total,
        fallback_count=fallback_count,
        review_required_count=review_required_count,
        error_count=error_count,
        skipped_count=skipped_count,
        provider_error_count=provider_error_count,
        validation_error_count=validation_error_count,
        http_status_counts=http_status_counts,
        last_error=last_error,
        request_diagnostics=run_request_diagnostics,
    )

    return AgenticChunkingArtifact(
        document_id=baseline.document_id,
        source_sha256=baseline.source_sha256,
        source_resolved_at=resolved.resolved_at,
        source_chunking_generated_at=baseline.generated_at,
        source_chunking_strategy_version=baseline.strategy_version,
        token_count_method=baseline.token_count_method,
        provider="groq",
        model=model,
        structured_output_mode=run_context.structured_output_mode,
        config=config,
        quality=quality,
        decisions=decisions,
        run_diagnostics=run_diagnostics,
        summary=summary,
        chunks=final_chunks,
        warnings=warnings,
        generated_at=run_finished_at,
    )

