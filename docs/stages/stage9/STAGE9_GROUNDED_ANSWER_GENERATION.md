# Stage 9 — Grounded Answer Generation

## Scope

Stage 9 adds answer generation **after Retrieval v1 is frozen**. It does not modify Dense retrieval, PostgreSQL FTS, RRF, the BGE reranker, semantic chunks, embeddings, or Stage 8.2 context expansion.

Production evidence path:

```text
question
  -> Dense Top-20 + Lexical Top-20
  -> candidate union
  -> BGE cross-encoder reranker
  -> Top-5 ranked seeds
  -> Stage 8.2 bounded structural expansion
  -> evidence package (E1, E2, ...)
  -> grounded generation
```

Top-5 is intentionally fixed for generation because the frozen held-out benchmark showed better context completeness at K=5 than K=3, while K=10 did not improve context recall/completeness further.

## Provider boundary

The default is Groq through its OpenAI-compatible `chat/completions` API, but provider/model/base URL are environment settings. The RAG pipeline does not import a Groq-specific SDK.

Default environment:

```env
GENERATION_PROVIDER=groq
GENERATION_BASE_URL=https://api.groq.com/openai/v1
GENERATION_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=<secret>
GENERATION_TEMPERATURE=0
GENERATION_MAX_TOKENS=1200
GENERATION_JSON_MODE=true
GENERATION_MAX_CONTEXT_CHARS=40000
```

Never commit `.env`.

## Grounding contract

The model does **not** return free-form prose as the authoritative object. It returns a structured decision:

```json
{
  "status": "answered",
  "claims": [
    {
      "text": "One atomic claim.",
      "evidence_ids": ["E1"]
    }
  ],
  "missing_information": []
}
```

or:

```json
{
  "status": "insufficient_evidence",
  "claims": [],
  "missing_information": ["What is missing"]
}
```

The backend validates every `evidence_id`. Unknown evidence references fail the request rather than being accepted as citations. The final answer text is assembled from validated claim text; it is not a second unconstrained model field.

`E1`, `E2`, etc. are request-local evidence identifiers. They are **not yet final user-facing citations**. Stage 10 will map validated claim evidence to page/section/source provenance.

## Abstention

The system prompt explicitly forbids outside knowledge and requires `insufficient_evidence` when the supplied chunks cannot answer the question. If retrieval returns no usable evidence, the backend abstains deterministically without calling the model.

No reranker-score threshold is used because reranker scores are not calibrated answerability probabilities.

## Prompt safety

Evidence is marked as source data, not instructions. This prevents document text from overriding the generation policy if a future corpus contains prompt-like text.

## No silent truncation

Stage 9 has a `GENERATION_MAX_CONTEXT_CHARS` guard. If the prompt exceeds the guard, the endpoint returns HTTP 409 and does **not** silently cut evidence. Top-5 + bounded Stage-8.2 context is expected to remain comfortably below the default guard for this benchmark.

## API

```http
POST /api/generation/answer
```

Request:

```json
{
  "document_id": "...",
  "question": "What are the requirements for delayed verification?"
}
```

Retrieval knobs are intentionally absent from this request. The generation endpoint uses the frozen Retrieval-v1 production profile.

Runtime diagnostics:

```http
GET /api/system/generation
```

The diagnostic response reports whether a key is configured, but never returns the secret.

## Verification

```bash
cd ~/ragProject/backend
source .venv/bin/activate
python scripts/test_grounded_generation_behaviors.py
```

The smoke runner is rate-limit aware. By default it waits **30 seconds between generation cases** and, if FastAPI wraps an upstream provider `429`, it reads Groq's suggested `Please try again in ...s` delay, adds a 2-second safety buffer, and retries up to two times. This matters for token-per-minute (TPM) limits because each grounded request includes several retrieved evidence chunks.

Useful overrides:

```bash
python scripts/test_grounded_generation_behaviors.py --delay-seconds 45
python scripts/test_grounded_generation_behaviors.py --max-rate-limit-retries 3
```

Use `--delay-seconds 0` only when the provider tier can comfortably handle the smoke suite without throttling. The smoke suite contains the five prior answerable regression questions plus one explicit out-of-scope question that should abstain. These are behavior checks, not final answer-quality metrics.

Formal answer/citation evaluation comes after Stage 10 citations are implemented.
