# Stage 10 / 10.1 / 10.2 — Deterministic citation rendering and validation

## Scope

Stage 10 is downstream of the frozen Retrieval v1 pipeline. It does **not** modify Stage 4, Stage 5, embeddings, lexical formulation, RRF, reranking, Top-K, or Stage 8.2 context assembly.

The production path remains:

`Hybrid (BGE-M3 + PostgreSQL FTS + weighted RRF) -> BGE reranker Top-5 -> Stage 8.2 structural context -> Stage 9 grounded claims -> Stage 10 deterministic citations`

## Trust boundary

The generation model is allowed to emit only request-local evidence IDs (`E1`, `E2`, ...). It is never asked to create page numbers, clause labels, appendix names, or citation strings.

Stage 10 resolves citations through this deterministic chain:

`claim -> E-ID -> exact frozen Stage 5 chunk -> source_element_ids -> resolved canonical structure -> citation`

If any link in that chain is stale or inconsistent, the API rejects citation rendering with a 409 response instead of returning an unvalidated citation.

## Citation source validation

Before a source citation can be emitted, Stage 10 verifies that:

1. the resolved canonical structure and Stage 5 chunk artifact belong to the requested document;
2. their source SHA-256 values match;
3. the Stage 5 artifact was produced from the currently resolved structure;
4. each evidence `chunk_id` exists in the frozen Stage 5 artifact;
5. `chunk_index`, `pages`, `section_path`, and `source_element_ids` exactly match the frozen chunk;
6. every Stage 5 `source_element_id` still exists in the resolved canonical structure;
7. canonical source-element pages exactly match the frozen chunk pages;
8. every rendered locator stays within the evidence's pages and source element IDs.

## Locator precedence

Human-facing locators are built only from canonical metadata:

- appendix membership from explicit canonical provenance only: direct `CanonicalElement.appendix_id` first; otherwise Stage 10.2 walks `SectionRecord.parent_section_id` to an explicit `kind="appendix"` ancestor. If that ancestor has a matching `AppendixRecord`, its label is used; if the frozen canonical artifact has no duplicate AppendixRecord, the explicit appendix SectionRecord itself is accepted after validating its label element and page. No page-range inference is allowed;
- numbered clause and nested subclause paths from `ClauseRecord` parent links;
- definition labels from `DefinitionEntry`;
- canonical section title when no more specific clause/definition locator exists; for appendix-contained tables/figures/list items this preserves the nested heading together with the appendix label;
- PDF page as the final fallback.

Examples:

- `Clause 8.1.25 · PDF p. 38`
- `APPENDIX B · Clause 1.11(a)(i) · PDF p. 83`
- `Definition “politically exposed person (PEP)” · PDF p. 13`
- `APPENDIX I · REPORTING UPON DETERMINATION · PDF p. 107`

## Stage 10.1 and 10.2 narrow corrections

The original Stage 10 live smoke run exposed one presentation/provenance edge case: the Appendix I reporting table could render only its nested section title (`REPORTING UPON DETERMINATION · PDF p. 107`) when the table source element did not carry a direct `appendix_id`, even though the canonical section hierarchy still placed that section under `APPENDIX I`.

Stage 10.1 added a hierarchy fallback, but its first implementation made an assumption that proved too strict in the populated frozen runtime: every explicit `SectionRecord(kind="appendix")` was required to have a matching `AppendixRecord` via `label_element_id`. The live Stage 10.1 run failed closed with HTTP 409 on the positive-match question because that duplicate record was absent for the encountered appendix section.

Stage 10.2 removes only that duplicate-record requirement. It does **not** rewrite Stage 4 or Stage 5 artifacts and does not infer appendix membership from page ranges. The deterministic fallback chain is now:

`source element -> section_id -> parent_section_id... -> SectionRecord(kind="appendix")`

Then:

1. if the appendix section maps to an `AppendixRecord`, use that record's label;
2. otherwise validate the explicit appendix SectionRecord's label element and page, then use the SectionRecord title itself as the appendix label;
3. reject the citation if the explicit appendix section has a missing label element, a page mismatch, or an empty label.

For appendix-contained non-clause material, the renderer keeps both the appendix and the direct nested section heading. The expected Appendix I table citation remains:

`APPENDIX I · REPORTING UPON DETERMINATION · PDF p. 107`

The citation contract version is bumped to `deterministic_citations_v1_2` so evaluation artifacts distinguish this corrected provenance resolver from v1 and v1.1.

## Response contract

`POST /api/generation/answer` retains the Stage 9 fields and adds:

- `cited_answer` — deterministic claim text with numeric citation markers;
- `claims[].citation_ids` — citation IDs derived from each claim's validated evidence IDs;
- `citations[]` — source filename, display locator, PDF pages, source elements, structural locators, and validation state;
- `citation_version = deterministic_citations_v1_2`;
- `citation_validation` — strict validation summary.

Citation IDs use the request-local evidence ID (`CIT-E1`, `CIT-E2`, ...). Display markers (`[1]`, `[2]`, ...) are assigned by first use in claim order, not by the numeric suffix of the E-ID.

For `insufficient_evidence`, no claims or citations are emitted and `cited_answer` equals the abstention answer.

## RAG Playground

The Playground now:

- renders the cited answer;
- shows claim-level citation chips;
- displays validated source cards instead of an empty source panel after generation;
- opens the original PDF at the cited page;
- exposes the Stage 10 claim -> evidence -> source trace;
- clearly states that citation strings are backend-derived rather than LLM-generated.

## Tests

Citation tests cover:

- Stage 10.1/10.2 appendix ancestry recovery for nested appendix tables whose source element lacks a direct `appendix_id`;
- acceptance of an explicit canonical appendix SectionRecord when the duplicate AppendixRecord is absent;
- fail-closed rejection when that appendix SectionRecord points to a missing label element;

- numbered clause rendering;
- nested appendix/subclause rendering;
- definition rendering;
- page mismatch rejection;
- source-element mismatch rejection;
- stale Stage 5 artifact rejection;
- deterministic first-use marker ordering;
- abstention without citation-source access;
- Stage 10 smoke-payload validation.

Run backend tests:

```bash
cd backend
PYTHONPATH=. pytest -q
```

Run the live, rate-limit-safe Stage 10 smoke suite against a populated local backend:

```bash
cd backend
PYTHONPATH=. python scripts/test_cited_generation_behaviors.py \
  --document-id 485c4989-c300-45c8-ac06-79a59492bb5c
```

The runner uses the same five answerable questions plus one out-of-scope abstention case from Stage 9. It exits non-zero on citation/provenance invariant failures and writes `all_cited_generation_results_stage10.txt`.

## Verification status for this archive

- Original Stage 10 (`deterministic_citations_v1`) live smoke: **6/6 behaviours passed** on the populated user runtime, including five answerable questions and the Bitcoin abstention control. The uploaded result is preserved at `backend/evaluation/reports/stage10_live_smoke_v1.txt`.
- Stage 10.1 backend regression: **295 passed**, but the populated live rerun exposed one fail-closed Appendix provenance edge case: the positive designated-person question returned HTTP 409 because an explicit appendix SectionRecord had no matching AppendixRecord. That live result is preserved at `backend/evaluation/reports/stage10_1_live_smoke_appendix_record_failure.txt`.
- Stage 10.2 backend regression after removing only the duplicate-AppendixRecord requirement: **297 passed**. The captured run is stored at `backend/evaluation/reports/stage10_2_backend_pytest.txt`.
- A realistic page-107 replay using the Stage 4 diagnostic artifact, with the source table's direct `appendix_id` and the APPENDIX I AppendixRecord intentionally removed while retaining the canonical appendix SectionRecord, renders `APPENDIX I · REPORTING UPON DETERMINATION · PDF p. 107`. The replay note is stored at `backend/evaluation/reports/stage10_2_appendix_replay.txt`.
- The Stage 10.2 live Groq smoke still needs to be rerun on the populated user runtime. The runner now requires `citation_version = deterministic_citations_v1_2`.
- No frontend code changed in Stage 10.2; the existing Playground renders the backend-provided citation display string.

## Evaluation handoff

Stage 10 should be frozen before answer/citation-quality scoring. Do not use the existing Retrieval v1 held-out questions to tune retrieval.

The next evaluation milestone should separately score:

- answer status / abstention correctness;
- answer relevance;
- claim faithfulness to cited evidence;
- claim citation coverage;
- citation locator precision;
- citation locator recall/completeness against manually annotated gold source references;
- deterministic citation validity (expected to remain 100% as an engineering invariant).

A schema scaffold is provided at `backend/evaluation/generation/answer_citation_eval_schema_v1.json`; it intentionally contains no new gold answers or locator annotations yet.
