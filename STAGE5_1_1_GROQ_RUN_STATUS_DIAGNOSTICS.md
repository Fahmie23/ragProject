# Stage 5.1.1 — Groq Run Status & Diagnostics

This revision makes Agentic Semantic v1 observable without exposing secrets.

## Provider check

`GET /api/documents/{document_id}/chunks/agentic/provider?probe=true` performs an authenticated request to Groq's Models API. It reports whether the backend is configured, whether Groq is reachable, whether the selected model is available, HTTP status, latency, and check time. It does not run a chunk-planning inference.

## Run diagnostics

Every successful artifact-producing Stage 5.1 run includes `run_diagnostics` with:

- run ID and final status
- start/finish timestamps and total duration
- candidates available and candidates sent
- provider/planner requests and responses received
- accepted plans, retries, fallbacks, review-required and run-error counts
- provider-error and deterministic-validation-error counts
- HTTP status counts
- last safe error message
- per-attempt diagnostics

Each request diagnostic records candidate ID, attempt number, status, HTTP status when available, duration, response-received flag, deterministic validation status, optional provider request ID, and a safe message.

## UI interpretation

The Agentic tab always shows a **Groq Run Status** card. A prior successful artifact never masks a new failed rerun: while a new run is active or has failed before producing an artifact, the transient run state takes precedence.

- **Completed successfully** — provider output parsed and accepted; every applied plan passed deterministic validation.
- **Completed with fallback** — at least one candidate reverted to the deterministic baseline.
- **Completed · review required** — at least one candidate requires human approval.
- **Run failed** — the current attempt did not complete cleanly.
- **Completed · no LLM calls needed** — the quality gate found no ambiguous candidate.

The expandable **Advanced · safe provider log** intentionally excludes API keys and Authorization headers. Provider error text is redacted before it is stored.

## Safety and compatibility

Existing Stage 5.1 artifacts remain readable because `run_diagnostics` is optional on load. Existing deterministic Stage 5 behavior is unchanged. Groq still only plans membership by existing chunk IDs; final retrieval text is assembled deterministically.

# v2.20 working copy
