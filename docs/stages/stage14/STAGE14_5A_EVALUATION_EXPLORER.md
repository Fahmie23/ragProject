# Stage 14.5A — Document-Specific Benchmark Report

## Status
Candidate until local TypeScript/Vite build and browser acceptance pass.

## Purpose
Stage 14.5A presents the frozen Stage 11 answer/citation evaluation as a **document-specific Benchmark Report**. It is engineering evidence for the controlled SC AML/CFT PDF benchmark, not a live quality score for arbitrary uploaded PDFs.

The frontend does not recalculate aggregate metrics and does not rerun retrieval, generation, scoring, or semantic judging.

## Data sources
The report consumes only the Stage 14.1 read APIs:
- `GET /api/evaluation/answer-citation/summary`
- `GET /api/evaluation/answer-citation/questions`
- `GET /api/evaluation/answer-citation/questions/{question_id}`

The read adapter exposes only facts already stored in frozen Stage 11 artifacts. The summary additionally exposes the frozen source filename/page count, held-out policy flags, and existing abstention precision/recall/F1 values; no Stage 11 metric is recomputed or changed.

## Information hierarchy
1. **Benchmark identity** — source PDF, dataset, held-out counts, page count, and explicit frozen/read-only scope.
2. **Answer behaviour** — answer-status accuracy plus abstention precision, recall, and F1.
3. **Grounding & citations** — claim support, citation entailment, claim-citation coverage, deterministic citation validity, and required-source coverage.
4. **Answer quality** — completeness and relevance.
5. **How to read the report** — explicit reminder that supported/valid claims can still omit benchmark-required information.
6. **Benchmark cases** — Complete / Partial / Issues / Out-of-scope filters plus search.
7. **Question detail drawer** — gold requirements, generated-claim review, citation-entailment review, reviewer notes, and optional frozen response.
8. **Evaluation scope** — document ID, evaluation type, human-review policy, automated-judge status, held-out tuning policy, external-call count, and frozen artifact references.

## Semantics boundary
- Aggregate display values are backend-owned Stage 11 values.
- Percentage formatting for per-question backend values is presentation only.
- `deterministic_citation_validity` means the deterministic provenance chain resolves correctly; it is not semantic entailment.
- Claim-support and citation-entailment labels shown in the report come only from the frozen human semantic review.
- `Complete`, `Partial`, `Issues`, and `Out of scope` are UI case filters derived from already-returned benchmark status/completeness/failure fields; they do not rescore the response.
- The benchmark is scoped to `answer_citation_eval_heldout_v1`. Cross-document robustness is explicitly not claimed.

## Explicit non-goals
- no `Re-run evaluation` action;
- no generation-provider call;
- no automated semantic judge;
- no benchmark mutation;
- no held-out retrieval tuning;
- no frontend-derived aggregate score;
- no claim that these values generalize to arbitrary PDFs.

## Acceptance gates
- Stage 14 focused tests pass.
- Full backend regression passes.
- Stage 11 freeze/evaluation guards pass.
- Local `npm run build` passes.
- Browser shows the frozen source PDF identity plus 18 held-out questions, 15 answerable, and 3 out-of-scope.
- Answer behaviour includes the already-frozen abstention precision/recall/F1 metrics.
- Metric definitions use backend formula/scope/artifact fields.
- ACIT-105 appears as a partial-completeness case and shows GC1 partially covered with GC2/GC3 covered.
- Opening/closing the question drawer invokes only the frozen question-detail GET endpoint.
- Evaluation scope states that held-out tuning was not authorized and cross-document robustness is not established.
- Escape closes the detail drawer and narrow layout remains within the viewport.

## Simplified benchmark-report UX

The default Benchmark page intentionally shows only four headline results: answer decisions, claim grounding, answer completeness, and deterministic citation provenance. It then explains the main observed weakness in plain language and lists benchmark questions using simple `PASSED`, `PARTIAL`, `ISSUE`, and `OUT OF SCOPE` states.

All other Stage 11 metrics remain available under `Advanced metrics`. Dataset identity, methodology, human-review status, held-out tuning policy, external-call count, and frozen artifact references remain under `About this benchmark`. Per-question generated-claim review, citation-entailment review, reviewer notes, failure flags, and the frozen response are hidden behind `Show technical evaluation` inside the question drawer.

This is progressive disclosure only. No evaluation score, benchmark label, frozen artifact, retrieval behavior, generation behavior, or citation behavior is changed.
