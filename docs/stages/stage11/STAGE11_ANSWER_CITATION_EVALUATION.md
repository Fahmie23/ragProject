# Stage 11 — Answer & Citation Evaluation

## Status

**Stage 11 is complete and frozen.** Stage 11.1 methodology/contract remains in force; the 20-question DEV benchmark calibrated `stage11_semantic_rubric_v1`, and an independent 18-question held-out benchmark was frozen before execution and consumed once on the unchanged production pipeline. The held-out semantic review is human-confirmed and bound to the exact captured response snapshots.

No automated semantic judge is enabled or authorized by rubric v1. Held-out results are final evaluation evidence, not authorization to tune Retrieval v1 or regenerate successful held-out responses. See `STAGE11_FINAL_EVALUATION.md` for the final DEV/held-out metrics and failure classification.

## Frozen production baseline

Stage 11 evaluates the existing production system. It must not tune or silently modify it.

- Stage 4 canonical structure: **FROZEN**
- Stage 5 semantic chunking `semantic-v2.1`: **FROZEN**
- Retrieval v1: **FROZEN**
  - BAAI/bge-m3
  - PostgreSQL FTS OR content-term formulation
  - weighted RRF
  - `candidate_k = 20`
  - `rrf_k = 60`
  - `dense_weight = 1.0`
  - `lexical_weight = 1.0`
  - BAAI/bge-reranker-v2-m3
  - Top-5 reranked seeds
  - `structural_one_hop_v1`, bounded and non-recursive
- Stage 9 generation: `grounded_claims_v1`
- Stage 10 citations: **FROZEN**, `deterministic_citations_v1_2`

`backend/evaluation/baselines/stage11_frozen_pipeline_manifest_v1.json` hashes the critical frozen files. Stage 11 tooling must refuse a benchmark run when this guard fails.

## Why Stage 11 is separate from retrieval evaluation

Retrieval evaluation answers: **Did the system retrieve the right evidence?**

Stage 11 answers different questions:

1. Did the system answer or abstain correctly?
2. Are generated claims actually supported by evidence?
3. Do citations support the claims they are attached to?
4. Did the answer include the required information?
5. Are citations structurally valid and complete?

A failure in Stage 11 does **not** automatically justify changing retrieval. It must first be classified as retrieval, context assembly, generation, citation, benchmark-label, or evaluator error.

## Evaluation unit

The primary semantic unit is the **generated claim**, not the whole answer.

```text
Question
  -> Answer status
  -> Generated claims C1..Cn
       -> evidence IDs
       -> deterministic citation IDs
       -> validated source locators
```

Gold labels describe required answer content and acceptable source groups. They do not prescribe exact model wording.

## Dataset split policy

The Stage 11 benchmark is independent from the existing retrieval held-out benchmark.

- `dev`: used to validate rubric wording, evaluator behavior, parsing, and reporting.
- `heldout`: used only after the Stage 11 benchmark and semantic rubric are frozen.

Held-out scoring requires:

```text
RUN_FROZEN_ANSWER_CITATION_HELDOUT_V1
```

The existing retrieval held-out questions must not be reused for Stage 11 tuning.

## Dataset contract

Schema:

`backend/evaluation/generation/answer_citation_eval_schema_v1.json`

Each question contains:

- `question_id`
- `split`
- `category`
- `difficulty`
- `question`
- `expected_status`
- `gold.required_claims`
- `gold.required_source_groups`
- `gold.answer_notes`

### Required claims

A required claim is a minimum semantic requirement for a complete answer. It is written as an evaluator instruction, not as a model-generated reference answer.

Example:

```json
{
  "claim_id": "GC1",
  "requirement": "State that verification must be completed within the permitted timeframe."
}
```

### Required source groups

Each group describes source coverage that is acceptable for the question. `any_of` allows structurally equivalent citations without forcing one exact chunk.

```json
{
  "group_id": "G1",
  "any_of": [
    {"kind": "clause", "label": "Clause 8.1.26", "pages": [38]}
  ]
}
```

This metric checks **source presence only**. It does not prove entailment.

## Stage 11.1 deterministic metrics

These are implemented now and require no semantic judge.

### AnswerStatusAccuracy

Question-level exact match between expected and actual status.

```text
1 if expected_status == actual_status else 0
```

### AbstentionPrecision / Recall / F1

Treat `insufficient_evidence` as the positive class.

- precision: when the system abstains, how often should it have abstained?
- recall: when it should abstain, how often does it abstain?

### ClaimCitationCoverage

Fraction of generated claims with at least one citation ID.

For a correct abstention with no claims, coverage is 1.0.

This measures citation attachment, not citation entailment.

### DeterministicCitationValidity

Re-checks Stage 9/10 response invariants offline:

- citation version
- Stage 10 validation summary
- claim -> citation -> evidence mapping
- used evidence ordering
- chunk ID/index agreement
- page agreement
- source-element agreement
- marker presence
- locator containment
- abstention invariants

Any invariant error makes the question score 0 for this metric.

### RequiredSourceCoverage

For each gold source group, at least one validated emitted locator must match one accepted locator by:

- locator kind
- normalized label
- optional gold page constraint

```text
satisfied required source groups / total required source groups
```

This is deliberately not called citation precision or citation correctness.

## Stage 11.2C semantic rubric — FROZEN and implemented

Frozen contract:

`backend/evaluation/generation/stage11_semantic_rubric_v1.json`

Frozen human-labelled calibration:

`backend/evaluation/generation/answer_citation_eval_dev_calibration_v1_frozen.json`

The calibration contains 9 DEV questions: ACIT-001, ACIT-003, ACIT-006, ACIT-008, ACIT-012, ACIT-014, ACIT-016, ACIT-017, and ACIT-018. ACIT-016 was deliberately added before freeze because the original eight-question subset was too clean and did not exercise a real missing-content path.

### Claim support label

Each generated claim receives exactly one label:

- `supported`: the cited evidence, considered together for the claim, fully supports every material assertion, scope, condition, and modality.
- `partially_supported`: the core claim is supported, but a material qualification, scope, condition, modality, or detail is omitted, broadened, strengthened, weakened, or slightly distorted.
- `unsupported`: the cited evidence does not establish a material part of the claim.
- `contradicted`: the cited evidence materially conflicts with the claim.

Frozen metrics:

- `ClaimSupportRate = supported / generated claims`
- `PartialSupportRate = partially_supported / generated claims`
- `UnsupportedClaimRate = unsupported / generated claims`
- `ContradictionRate = contradicted / generated claims`

### Citation entailment label

For every claim-citation relation:

- `entails`: that individual citation fully supports the complete material claim.
- `partial`: that citation supports only part of a compound claim or has a material qualification mismatch. Multiple partial citations may jointly make the claim fully supported.
- `does_not_entail`: that individual citation does not support the material claim.

Frozen metrics:

- `CitationEntailmentRate = entails / claim-citation relations`
- `CitationPartialRate = partial / claim-citation relations`
- `CitationNonEntailmentRate = does_not_entail / claim-citation relations`

This dimension is intentionally independent from Stage 10 deterministic provenance validity.

### Gold claim coverage and answer completeness

Each required gold claim is marked:

- `covered`: required content is present with material scope, conditions, and modality preserved.
- `partially_covered`: core content is present but a material qualification, scope, condition, modality, or detail is omitted or distorted.
- `missing`: required content is absent.

Frozen metrics:

- `GoldClaimCoverage = covered / required gold claims`
- `PartialGoldClaimCoverage = partially_covered / required gold claims`
- `MissingGoldClaimRate = missing / required gold claims`
- `AnswerCompleteness = (covered + 0.5 * partially_covered) / required gold claims`

The `0.5` partial-credit weight is part of rubric v1 and must not be changed without creating a new rubric version.

### Answer relevance

Question-level score:

- `2`: strong — directly answers the question and is substantially complete for the requested scope.
- `1`: acceptable but materially incomplete — directly relevant, but important requested content is missing or materially weakened.
- `0`: poor — materially off-topic, unresponsive, or wrong answer/abstention behavior.

Frozen metrics:

- `AnswerRelevanceMean` on the 0-2 scale
- `AnswerRelevanceNormalized = mean / 2`

### Aggregation and empty-unit policy

Claim, citation-relation, and gold-claim rates are **micro-averaged** across the labelled subset. Answer relevance is macro-averaged across labelled questions. A dimension with zero applicable units returns `null`; a correct abstention therefore does not manufacture synthetic claims, citations, or gold claims.

### Human-label snapshot binding

The frozen calibration stores:

- a canonical SHA-256 for the DEV dataset; and
- a canonical SHA-256 for every captured response used during human review.

`backend/evaluation/baselines/stage11_semantic_evaluation_manifest_v1.json` additionally hashes the frozen rubric, frozen calibration artifact, and semantic metric implementation. Semantic scoring refuses to proceed when that manifest fails or when the dataset/response hashes no longer match. This prevents stale human labels or silently modified metric definitions from being used.

### Confirmed calibration results

On the frozen 9-question calibration subset:

- generated claims: 20
- supported: 17 / 20 = 85.0%
- partially supported: 3 / 20 = 15.0%
- unsupported: 0 / 20
- contradicted: 0 / 20
- claim-citation relations: 22
- individual citations that fully entail the whole claim: 16 / 22 = 72.73%
- partial citation relations: 6 / 22 = 27.27%
- does-not-entail relations: 0 / 22
- required gold claims: 24
- covered: 20 / 24 = 83.33%
- partially covered: 2 / 24 = 8.33%
- missing: 2 / 24 = 8.33%
- weighted answer completeness: 87.5%
- answer relevance mean: 1.8889 / 2

`CitationEntailmentRate` is deliberately strict at the **individual citation** level. For example, ACIT-012 C3 is fully supported by two citations together while each citation is individually labelled `partial`. A lower strict entailment rate therefore does not imply unsupported claims; `CitationNonEntailmentRate` is 0% in this calibration.

## Semantic judge policy

An LLM judge, if introduced later, is an implementation of the frozen rubric—not the source of the rubric.

Before using an automated judge on held-out data:

1. Freeze the rubric and dataset labels.
2. Manually label a DEV calibration subset.
3. Compare judge labels with human labels.
4. Record agreement and disagreement cases.
5. Freeze judge model, prompt, temperature, response schema, and retry policy.
6. Only then allow held-out semantic scoring.

No judge should be allowed to modify answers, citations, retrieval, or gold labels.

## Stage 11.2 DEV benchmark

Dataset:

`backend/evaluation/generation/answer_citation_eval_dev_v1.json`

Current construction profile:

- 20 DEV questions only
- 17 expected `answered`
- 3 expected `insufficient_evidence`
- 0 held-out questions
- 33 required source groups / 34 accepted gold locators after the accepted ACIT-004 DEV gold-label correction
- categories cover cross-page definitions, direct requirements, conditional rules, multi-clause answers, appendix evidence, table evidence, and out-of-scope abstention
- 0 exact retrieval-evaluation question duplicates
- 0 token-Jaccard similarity warnings at the 0.70 audit threshold

The gold requirements are authored from the frozen canonical artifact. They state minimum semantic requirements instead of prescribing exact model wording.

### Stage 11.2 construction guards

Validate the benchmark contract:

```bash
cd backend
PYTHONPATH=. python scripts/validate_answer_citation_eval_dataset.py \
  evaluation/generation/answer_citation_eval_dev_v1.json
```

Validate every gold locator against the frozen Stage 4 canonical artifact:

```bash
PYTHONPATH=. python scripts/validate_answer_citation_eval_source.py \
  evaluation/generation/answer_citation_eval_dev_v1.json
```

Audit accidental overlap with the existing retrieval benchmark:

```bash
PYTHONPATH=. python scripts/audit_stage11_dev_question_overlap.py \
  evaluation/generation/answer_citation_eval_dev_v1.json
```

Validate the frozen production baseline:

```bash
PYTHONPATH=. python scripts/validate_stage11_frozen_baseline.py
```

### Fresh DEV capture

The capture runner is DEV-only and resumable. It validates the dataset, source locators, and frozen baseline before the first API request. Existing contract-valid response files are skipped unless `--overwrite` is supplied.

Dry run:

```bash
PYTHONPATH=. python scripts/capture_answer_citation_dev.py --dry-run
```

Live capture on the populated local environment:

```bash
PYTHONPATH=. python scripts/capture_answer_citation_dev.py \
  --base-url http://localhost:8000
```

To retry a single case:

```bash
PYTHONPATH=. python scripts/capture_answer_citation_dev.py \
  --question-id ACIT-012
```

Default raw response location:

`backend/evaluation/reports/stage11_2_dev_capture_v1/responses/ACIT-###.json`

### Deterministic DEV scoring

After all 20 fresh responses are captured:

```bash
PYTHONPATH=. python scripts/score_answer_citation_results.py \
  --dataset evaluation/generation/answer_citation_eval_dev_v1.json \
  --responses-dir evaluation/reports/stage11_2_dev_capture_v1/responses \
  --split dev \
  --output-dir evaluation/reports/stage11_2_dev_score_v1
```

Without `--semantic-calibration`, semantic metrics remain `NOT SCORED`. With the frozen human calibration supplied, the same scorer also emits semantic metrics for the 9-question calibration subset; it does not extrapolate those labels to the other 11 DEV questions.

### Manual semantic calibration subset

A fixed nine-question calibration selection is defined in:

`backend/evaluation/generation/answer_citation_eval_dev_calibration_v1.json`

It covers cross-page definition, conditional/multi-clause behavior, cross-page sanctions screening, appendix evidence, a real completeness failure (ACIT-016), table evidence, and abstention.

Prepare a blank annotation artifact only after fresh DEV responses exist:

```bash
PYTHONPATH=. python scripts/prepare_stage11_semantic_calibration.py \
  --responses-dir evaluation/reports/stage11_2_dev_capture_v1/responses \
  --output evaluation/reports/stage11_2_semantic_calibration_v1.json
```

The script never pre-fills semantic labels. It now binds the draft artifact to the frozen rubric and exact response/dataset hashes. Human review must assign claim support, citation entailment, gold-claim coverage, and answer relevance before creating a frozen calibration artifact.

## Stage 11.2C current gate

All Stage 11.2C freeze conditions pass:

- 20/20 DEV responses captured successfully
- deterministic AnswerStatusAccuracy = 100%
- ClaimCitationCoverage = 100%
- DeterministicCitationValidity = 100%
- corrected RequiredSourceCoverage = 98.5294%
- semantic rubric `stage11_semantic_rubric_v1` human-confirmed and frozen
- 9-question calibration bound to exact response snapshots
- semantic calibration validator passes
- semantic metric implementation reproduces the human-confirmed label counts
- no automated judge is enabled
- frozen production-pipeline hash guard remains mandatory

The remaining deterministic source-coverage gap is ACIT-016 and is retained as a baseline diagnostic rather than tuned away. It contains both a generation-completeness miss and a retrieval/context-coverage miss.

### Combined scoring command

```bash
cd backend
PYTHONPATH=. python scripts/score_answer_citation_results.py \
  --dataset evaluation/generation/answer_citation_eval_dev_v1.json \
  --responses-dir evaluation/reports/stage11_2_dev_capture_v1/responses \
  --split dev \
  --semantic-calibration evaluation/generation/answer_citation_eval_dev_calibration_v1_frozen.json \
  --output-dir evaluation/reports/stage11_2c_dev_score_v1
```

Validate the frozen human calibration and exact response binding:

```bash
PYTHONPATH=. python scripts/validate_stage11_semantic_calibration.py \
  --responses-dir evaluation/reports/stage11_2_dev_capture_v1/responses
```

## Stage 11.3 — frozen independent held-out benchmark

Dataset:

`backend/evaluation/generation/answer_citation_eval_heldout_v1.json`

Status: **FROZEN BEFORE FIRST LIVE RUN**.

Construction profile:

- 18 held-out questions only
- 15 expected `answered`
- 3 expected `insufficient_evidence`
- 52 minimum semantic gold claims
- 28 required source groups / 28 accepted gold locators
- 0 exact prior-question duplicates against Stage 11 DEV or the 40-question retrieval benchmark
- 0 token-Jaccard warnings at the 0.70 threshold
- 0 question-ID collisions
- 0 exact Stage 11 DEV gold-locator reuse
- all gold locators validated against the frozen Stage 4 canonical artifact

The held-out questions cover a new cross-page definition, applicability/enforcement rules, general principles, legal-arrangement CDD, digital-asset wire-transfer record controls, transaction-record contents, suspicious-transaction decision rules, compliance-officer safeguards, Appendix B former-PEP risk treatment, Appendix E beneficial-owner cascading/control guidance, Appendix G/H sanctions material, and three current-information abstention controls.

### Held-out freeze contract

The dataset is hash-frozen by:

`backend/evaluation/baselines/stage11_heldout_benchmark_manifest_v1.json`

Any modification to the dataset requires a new held-out benchmark version. The live capture and held-out scorer validate the **actual dataset file path being executed** against that frozen SHA-256; copying a modified JSON and leaving `benchmark_status=frozen` is rejected.

The Stage 11.3 validator also requires all three independent guards to pass:

1. frozen production-pipeline manifest;
2. frozen semantic-rubric/metric manifest; and
3. frozen held-out benchmark manifest.

Validate the benchmark without running it:

```bash
cd backend
PYTHONPATH=. python scripts/validate_stage11_heldout_benchmark.py
```

Audit independence explicitly:

```bash
PYTHONPATH=. python scripts/audit_stage11_heldout_independence.py \
  evaluation/generation/answer_citation_eval_heldout_v1.json \
  --output evaluation/reports/stage11_3_heldout_independence_audit.json
```

Dry-run the held-out capture guard without making generation calls:

```bash
PYTHONPATH=. python scripts/capture_answer_citation_heldout.py --dry-run
```

### First live held-out run — intentionally not executed during Stage 11.3 construction

Actual API calls require the exact explicit token:

```text
RUN_FROZEN_ANSWER_CITATION_HELDOUT_V1
```

The runner intentionally has **no overwrite flag** and **no single-question selection path**. Valid captured responses are immutable and skipped on resume. A rerun is only for resuming missing/failed requests, not regenerating successful held-out answers.

When the local freeze validation has been independently reproduced and the decision is made to consume the held-out benchmark, run:

```bash
PYTHONPATH=. python scripts/capture_answer_citation_heldout.py \
  --base-url http://localhost:8000 \
  --confirm-heldout RUN_FROZEN_ANSWER_CITATION_HELDOUT_V1
```

The default inter-question delay remains 30 seconds and provider rate-limit retry handling remains enabled.

Default response location:

`backend/evaluation/reports/stage11_3_heldout_capture_v1/responses/ACIT-###.json`

After a complete capture, deterministic held-out scoring is also confirmation-protected and verifies the held-out dataset hash:

```bash
PYTHONPATH=. python scripts/score_answer_citation_results.py \
  --dataset evaluation/generation/answer_citation_eval_heldout_v1.json \
  --responses-dir evaluation/reports/stage11_3_heldout_capture_v1/responses \
  --split heldout \
  --confirm-heldout RUN_FROZEN_ANSWER_CITATION_HELDOUT_V1 \
  --output-dir evaluation/reports/stage11_3_heldout_score_v1
```

No held-out semantic labels are created in advance. Generated held-out claims/citations must be evaluated under the already frozen `stage11_semantic_rubric_v1`; the gold answer requirements and source groups are frozen before seeing model outputs.

## Next action

Do **not** modify the frozen production RAG path, semantic rubric, or held-out dataset. Do **not** run individual held-out questions for exploration.

Stage 11.3 construction is complete when the local benchmark validator, dry-run capture guard, backend test suite, production freeze guard, and semantic freeze guard all reproduce PASS. Only after that gate should the single held-out evaluation be consumed.

No Stage 11.3 held-out generation response has been produced during benchmark construction.
## Stage 11.3B/C — held-out evaluation consumed and frozen

The independent held-out benchmark was consumed once after all freeze and independence guards passed. All 18 response snapshots were retained, deterministic scoring was completed, and the already-frozen `stage11_semantic_rubric_v1` was applied through human-confirmed labels bound to the exact response hashes.

Final held-out deterministic results:

- AnswerStatusAccuracy: **94.44%**
- ClaimCitationCoverage: **100%**
- DeterministicCitationValidity: **100%**
- RequiredSourceCoverage: **93.33%**
- AbstentionPrecision: **75.00%**
- AbstentionRecall: **100%**
- AbstentionF1: **85.71%**

Final held-out semantic results:

- ClaimSupportRate: **95.83%**
- UnsupportedClaimRate: **0%**
- ContradictionRate: **0%**
- CitationEntailmentRate: **93.88%**
- CitationNonEntailmentRate: **0%**
- GoldClaimCoverage: **78.85%**
- AnswerCompleteness: **83.65%**
- AnswerRelevanceMean: **1.7778 / 2**

The only answer-status miss was ACIT-112, classified as retrieval/context coverage: the required Appendix E Step 3 provenance did not reach the bounded context, and the model conservatively abstained. Other held-out weaknesses were primarily completeness/fidelity rather than unsupported or contradictory generation.

The frozen held-out human labels live in `backend/evaluation/generation/answer_citation_eval_heldout_calibration_v1_frozen.json`.
