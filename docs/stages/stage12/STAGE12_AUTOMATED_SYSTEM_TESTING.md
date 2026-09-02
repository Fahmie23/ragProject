# Stage 12 — Automated & System Testing

## Status

**Candidate implementation complete; local runtime gates still required before freeze.**

Stage 12 verifies the already-frozen RAG pipeline. It does not authorize changes to Stage 4/5, Retrieval v1, reranking, Stage 8.2 context parameters, Stage 9 generation behavior, Stage 10 citations, or the Stage 11 evaluation rubric/benchmarks.

## Goals

Stage 12 closes the gap between component tests and a trustworthy system verification layer:

1. Validate API contracts and fail-closed error mapping.
2. Validate application startup/health behavior around PostgreSQL/pgvector.
3. Exercise the file pipeline across Stage 3 → Stage 4 → Stage 4.5 → Stage 5 and verify upstream invalidation removes stale downstream artifacts.
4. Verify deterministic abstention when generation receives no evidence.
5. Verify provider/config/context/output/citation failures become stable HTTP responses.
6. Reproduce the frozen Stage 11 final held-out metrics offline from the exact 18 captured responses.
7. Re-run the complete backend regression suite.
8. Require a local frontend TypeScript/Vite build.
9. Require a live local-system smoke against the running FastAPI + PostgreSQL/pgvector + real retrieval/reranker stack.

## New automated coverage

`tests/test_stage12_system_contracts.py`

- critical OpenAPI route presence
- optional vs required database health behavior
- startup refusal when required PostgreSQL is unavailable
- startup refusal when pgvector is missing
- generation runtime status secret redaction
- all retrieval endpoints fail closed without PostgreSQL
- hybrid request invariant validation
- deterministic no-evidence generation abstention
- stable HTTP mapping for generation configuration/context/output/provider failures
- fail-closed citation-source and citation-provenance errors

`tests/test_stage12_pipeline_system.py`

- upload → extraction → structure → saved resolved review → Stage 5 chunks
- raw file fetch and artifact retrieval
- Stage 3 rerun invalidates Stage 4/4.5/5 downstream artifacts
- stale Stage 5 artifact is rejected and deleted
- missing raw file fails closed
- upload-size limit returns HTTP 413 without metadata persistence

`tests/test_stage12_stage11_final_reproduction.py`

- reproduces the frozen one-time Stage 11 held-out evaluation entirely offline
- checks exact held-out response bindings and final manifest hashes
- re-runs deterministic + frozen human-semantic scoring
- verifies saved final metrics exactly
- makes zero generation-provider API calls

## Verification commands

### 1. Complete automated/offline verification

From `backend/`:

```bash
PYTHONPATH=. python scripts/run_stage12_verification.py --frontend required
```

This performs:

- frozen production baseline guard
- frozen held-out benchmark guard
- frozen Stage 11 final-evaluation reproduction
- Stage 12 system/API tests
- Python compilation
- full backend pytest regression
- frontend `npm run build`

The frontend build is intentionally required for the final local gate. `--frontend auto` may be used in restricted CI/sandbox environments, but an auto-skip is not sufficient to freeze Stage 12.

### 2. Live local-system smoke

Run the normal backend with the populated PostgreSQL/pgvector database, then:

```bash
PYTHONPATH=. python scripts/run_stage12_live_smoke.py --base-url http://localhost:8000
```

This validates:

- `/health`
- database reachability
- pgvector enabled
- migrated schema ready
- frozen source-document SHA
- Stage 5 chunk artifact available
- one real Dense + PostgreSQL FTS + RRF + BGE reranker + Stage 8.2 structural-context request
- reported frozen retrieval/citation versions

It does **not** call Groq by default. Stage 11 already verified the production generation provider through DEV and the one-time held-out run. If a provider smoke is explicitly desired, use `--include-generation`; it must not be treated as another held-out evaluation.

## Offline candidate result

In the Stage 12 build environment:

- Stage 12 tests: **24/24 passed**
- Full backend regression: **362/362 passed**
- Python compile: **PASS**
- Stage 11 production freeze: **PASS**
- Stage 11 held-out freeze: **PASS**
- Stage 11 final evaluation reproduction: **PASS**
- External generation calls during automated verification: **0**
- Frontend build: **not claimed** because dependencies could not be installed in the restricted build environment
- Live local-system smoke: **not claimed** because the user's PostgreSQL/model runtime is local

## Freeze criteria

Stage 12 may be frozen only after the user's local environment reports all of the following:

1. `run_stage12_verification.py --frontend required` → PASS.
2. Frontend build → PASS.
3. Full backend suite → 362/362 or higher if only new Stage 12 tests are added.
4. Production/Stage 11 freeze guards → PASS.
5. `run_stage12_live_smoke.py` → PASS against the populated local runtime.
6. No production RAG component was modified to make the tests pass.

Only after these gates pass should `stage12_verification_contract_v1` be marked frozen.
