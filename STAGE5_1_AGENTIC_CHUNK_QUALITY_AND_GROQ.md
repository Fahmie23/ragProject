# Stage 5.1 — Chunk Quality Gate + Agentic Semantic v1 (Groq)

Stage 5.1 sits **after** the deterministic Stage 5 baseline and **before** embeddings/indexing.

It does **not** replace `semantic_v1`. The deterministic artifact remains the comparison baseline and fallback source.

```text
Resolved Stage 4.5
      │
      ▼
Stage 5 Semantic v1
      │
      ├─ data/chunks/{document_id}.json     immutable baseline
      │
      ▼
Stage 5.1 Quality Gate
      │
      ├─ navigation-only content ─────────── deterministic exclude in 5.1 view
      │
      └─ ambiguous semantic candidates
                    │
                    ▼
              Groq planner
                    │
                    ▼
              ChunkPlan JSON
                    │
                    ▼
         deterministic validator
              │             │
            valid         invalid
              │             │
              ▼             ├─ retry with validation feedback
         deterministic      └─ fallback / review after limit
            executor
              │
              ▼
 data/chunks/{document_id}.agentic.json
```

## Why this boundary exists

The LLM is **not** allowed to generate chunk text. It only plans with existing Stage 5 chunk IDs.

The backend owns:

- source text;
- canonical provenance;
- section constraints;
- hard token limits;
- plan validation;
- final text assembly;
- deterministic fallback.

This prevents the planner from silently paraphrasing, omitting, or inventing document content.

## Quality gate

`GET /api/documents/{document_id}/chunks/quality`

The quality gate is deterministic and does not require an LLM/API key.

It currently identifies:

1. **Navigation-only content**
   - e.g. chunks whose canonical section path starts with `CONTENTS` / `TABLE OF CONTENTS`.
   - These are marked for deterministic exclusion from the Stage 5.1 retrieval view because they can compete with the actual section content during retrieval.
   - The original Stage 5 chunk remains preserved.

2. **Parent / child hierarchy dependencies**
   - Uses canonical `parent_of` relations.
   - Builds one non-overlapping candidate from a root clause and its descendant subclauses/list structure.
   - This is where isolated child chunks such as `(i) Foreign PEP` can be evaluated together with the parent statement they depend on.

3. **Cross-chunk continuations**
   - Uses canonical `continues` relations when Stage 5 still produced separate retrieval units.

4. **Contextual notes / footnotes**
   - Uses canonical footnote type when available.
   - Also detects conservative paragraph-shaped numbered notes and pairs them with nearby same-section content for review.

5. **Very small low-information fragments**
   - Only selected semantic types with very low token count and no section path become candidates.
   - Tiny chunks are counted globally, but **tiny does not automatically mean bad**. Short definitions remain valid retrieval units.

No invented scalar “quality score” is produced. The UI reports concrete issue counts and candidate sets instead.

## Groq provider

Stage 5.1 supports Groq through its OpenAI-compatible Chat Completions endpoint.

Configure `backend/.env`:

```dotenv
GROQ_API_KEY=your_key_here
GROQ_MODEL=openai/gpt-oss-20b
GROQ_BASE_URL=https://api.groq.com
GROQ_TIMEOUT_SECONDS=45
```

The API key:

- is read only by the backend;
- is never sent to the React frontend;
- is never written to Stage 5/5.1 artifacts;
- is never returned by the provider-status endpoint.

### Structured output modes

For these Groq-hosted models:

```text
openai/gpt-oss-20b
openai/gpt-oss-120b
```

Stage 5.1 uses strict JSON-schema structured output.

For other Groq models, Stage 5.1 uses JSON Object Mode plus Pydantic validation and retry. This lets models such as `llama-3.3-70b-versatile` remain usable without pretending they have strict schema guarantees.

## Context packet

The planner never receives the whole Resolved JSON or the whole Stage 5 artifact.

Each request contains one bounded semantic candidate:

```json
{
  "document_context": {
    "title": "...",
    "subtitle": "...",
    "document_outline": ["..."],
    "current_section_path": ["..."]
  },
  "candidate": {
    "candidate_id": "agent-candidate-...",
    "reason_codes": ["hierarchy_dependency"],
    "chunks": [
      {
        "chunk_id": "...",
        "semantic_type": "clause",
        "token_count": 52,
        "content_text": "8.1 ... following:",
        "source_element_ids": ["..."]
      },
      {
        "chunk_id": "...",
        "semantic_type": "subclause",
        "token_count": 41,
        "content_text": "(a) ...",
        "source_element_ids": ["..."]
      }
    ],
    "relationships": [
      {
        "type": "parent_of",
        "source_chunk_id": "...",
        "target_chunk_id": "...",
        "evidence": "..."
      }
    ],
    "previous_neighbor": null,
    "next_neighbor": null
  },
  "constraints": {
    "target_tokens": 450,
    "max_tokens": 700,
    "preserve_section_context": true,
    "never_rewrite_source_text": true,
    "allowed_chunk_ids": ["..."]
  },
  "validation_feedback": []
}
```

The global document context is deliberately compact: title, subtitle, top-level outline and current section path. Local semantic evidence is much more important than dumping unrelated pages into the model context.

## Planner output

The model must return a `ChunkPlan`:

```json
{
  "candidate_id": "agent-candidate-...",
  "decision": "group",
  "groups": [
    {
      "chunk_ids": ["parent", "child-a", "child-b"],
      "context_chunk_ids": []
    },
    {
      "chunk_ids": ["child-c", "child-d"],
      "context_chunk_ids": ["parent"]
    }
  ],
  "excluded_chunk_ids": [],
  "reason": "The child items depend on the parent requirement; the second group repeats the parent because the complete hierarchy exceeds the desired retrieval size.",
  "confidence": 0.94
}
```

Allowed decisions:

- `keep`
- `group`
- `exclude`
- `needs_review`

`exclude` is validator-restricted to candidates that the deterministic gate already classified as `low_information_content`. It cannot be used to remove substantive hierarchy or continuation content.

## Deterministic plan validation

A model response is rejected when any of the following occurs:

- wrong candidate ID;
- invented chunk ID;
- missing candidate chunk;
- same primary chunk assigned twice;
- chunk both grouped and excluded;
- parent-dependent child separated without repeating parent context;
- group over `max_tokens`;
- empty retrieval text;
- illegal exclusion;
- invalid decision structure.

Validation errors are fed back to the planner for up to the configured retry count.

If the plan remains invalid:

```text
fallback_to_deterministic=true
→ preserve the original Stage 5 chunks for that candidate
```

The final Stage 5.1 summary then reports the fallback and does **not** recommend Stage 6.

## Confidence + human review

Default minimum confidence:

```text
0.80
```

If the planner returns a lower score or explicitly selects `needs_review`:

- no model plan is executed;
- deterministic Stage 5 chunks remain in the final preview;
- the decision is recorded as `needs_review`;
- `ready_for_stage6=false`.

Confidence is only a routing signal from the planner. It is not treated as proof that the plan is correct.

## Provider failures

The system is fail-safe:

- missing API key → agentic endpoint returns 503 before making requests when LLM candidates exist;
- invalid plan → retry with validator feedback;
- timeout / auth / rate-limit / provider failure → deterministic fallback when enabled;
- broad provider failures trip a simple circuit breaker so the backend does not repeat the same failed Groq call for every remaining candidate;
- stale Stage 5 / Resolved sources invalidate Stage 5.1 output.

## Stage 5.1 API

```text
GET    /api/documents/{document_id}/chunks/quality
GET    /api/documents/{document_id}/chunks/agentic/provider
POST   /api/documents/{document_id}/chunks/agentic
GET    /api/documents/{document_id}/chunks/agentic
DELETE /api/documents/{document_id}/chunks/agentic
```

### Generate request

```json
{
  "config": {
    "provider": "groq",
    "model": "openai/gpt-oss-20b",
    "minimum_confidence": 0.8,
    "max_retries": 2,
    "max_agent_candidates": 50,
    "fallback_to_deterministic": true
  }
}
```

`max_agent_candidates` exists as an explicit cost/latency guard. Candidates above that limit fall back to the deterministic baseline and Stage 6 is not marked ready. Increase it only after reviewing the quality-gate candidate count.

## Frontend workflow

The Chunking tab now exposes:

```text
Overview
Cleaning
Chunk Preview
Quality Gate
Agentic
Chunk JSON
```

### Quality Gate

Shows:

- baseline count;
- number of tiny chunks (diagnostic only);
- navigation-only chunks;
- hierarchy candidate count;
- total agent candidates;
- candidate previews + section path + pages;
- deterministic-vs-agent boundary.

### Agentic

Shows:

- Groq configuration status;
- model;
- strict-schema vs JSON+validation mode;
- confidence threshold;
- retry count;
- candidate call limit;
- fallback policy;
- agent decision audit;
- final agentic chunk browser;
- source baseline chunk IDs and Stage 3/canonical provenance;
- Stage 6 recommendation state.

## Comparison principle

The deterministic baseline remains available at all times:

```text
Semantic v1
vs
Agentic Semantic v1
```

This is intentional. Stage 6 evaluation should compare retrieval quality rather than assuming an LLM-based strategy is automatically better.
