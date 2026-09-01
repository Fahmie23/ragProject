# Stage 5.1.2 — Groq Official SDK Transport Fix

## Why this revision exists

The previous Stage 5.1 implementation called Groq with Python's `urllib.request` directly. On some environments Cloudflare rejected that transport before Groq API authentication/processing with HTTP 403 / Error 1010 (`browser_signature_banned`).

Stage 5.1.2 removes the raw `urllib` transport and uses Groq's official Python SDK for both connectivity checks and chat-completion planning.

## Runtime dependency

`backend/requirements.txt` now pins:

```text
groq==1.7.0
```

This was the current PyPI release when this revision was produced (2026-08-27).

After extracting/updating the project, reinstall backend dependencies and restart the API:

```bash
cd backend
source .venv/bin/activate
python -m pip install -r requirements.txt
python -c "import groq; print(groq.__version__)"
uvicorn app.main:app --reload
```

The version check should print `1.7.0`.

## Provider probe

The provider check now uses:

```python
from groq import Groq

client = Groq(...)
client.models.list()
```

rather than manually issuing `GET /models` with `urllib.request`.

The Agentic UI now also displays the detected Groq Python SDK version.

## Agent request

The chunk planner now uses:

```python
client.chat.completions.create(...)
```

The existing JSON-schema response format and Pydantic validation remain in place.

For GPT-OSS 20B/120B, reasoning output is disabled because Stage 5.1 only needs the structured `ChunkPlan`; hidden reasoning is neither required nor persisted.

## Retry ownership

The Groq SDK normally retries selected failures automatically. Stage 5.1 configures:

```python
max_retries=0
```

because the Stage 5.1 orchestrator already owns retries. This keeps the Run Status diagnostics accurate: every retry shown in the UI corresponds to an actual planner attempt.

## Error handling

SDK-native exceptions are mapped into the existing diagnostics model:

- `APIStatusError` → HTTP/provider error with status code
- `APITimeoutError` → timeout error
- `APIConnectionError` → network error
- other `APIError` → provider error

Cloudflare Error 1010 is recognized explicitly and returns an actionable message. If Error 1010 still occurs while the diagnostics panel reports `groq-python 1.7.0`, investigate VPN/proxy/security middleware or compare the same key/network with Groq's official SDK example.

No API keys or Authorization headers are persisted in diagnostics.

## Validation

Regression suite after this change:

```text
146 passed
```

Additional checks cover:

- official SDK client construction
- `client.models.list()` provider probe
- `client.chat.completions.create()` planning request
- strict JSON-schema request configuration
- SDK version pin
- Cloudflare Error 1010 diagnostic message
- secret redaction

Frontend focused TypeScript transpilation and CSS brace checks also pass.
