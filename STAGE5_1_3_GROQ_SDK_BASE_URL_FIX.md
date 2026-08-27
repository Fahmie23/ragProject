# Stage 5.1.3 — Groq SDK Base URL Normalization

## Problem

The official Groq Python SDK already owns the `/openai/v1/...` resource prefix. v2.20 passed `GROQ_BASE_URL=https://api.groq.com/openai/v1` directly into `Groq(base_url=...)`, which could produce duplicated URLs such as:

```text
https://api.groq.com/openai/v1/openai/v1/models
```

and Groq correctly returned HTTP 404 `unknown_url`.

## Fix

- The project default is now `GROQ_BASE_URL=https://api.groq.com`.
- Existing `.env` values ending in `/openai/v1` remain supported. The backend strips one trailing `/openai/v1` before constructing the SDK client.
- For the official Groq host, `base_url` is omitted entirely so the SDK uses its built-in production endpoint.
- Custom proxy/gateway roots are still supported; a legacy custom value ending in `/openai/v1` is normalized to its root.
- Provider diagnostics show the normalized SDK root.

## Correct request ownership

```text
SDK root:       https://api.groq.com
SDK resource:   /openai/v1/models
Final request:  https://api.groq.com/openai/v1/models
```

The application must never assemble `/openai/v1/models` manually when using `client.models.list()`.
