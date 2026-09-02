# Stage 11 — Final Answer & Citation Evaluation

## Status

**Stage 11 is complete and frozen.** The production RAG pipeline remained unchanged throughout evaluation. The 20-question DEV benchmark was used to calibrate the semantic rubric; the independent 18-question held-out benchmark was frozen before execution and consumed once. Held-out responses were not regenerated for tuning.

Frozen semantic rubric: `stage11_semantic_rubric_v1`

Frozen held-out calibration: `answer_citation_eval_heldout_calibration_v1_frozen`
Automated semantic judge: **disabled**. Human labels are authoritative for v1.

## DEV vs held-out

| Metric | DEV | Held-out |
|---|---:|---:|
| Questions | 20 | 18 |
| Answer status accuracy | 100.00% | 94.44% |
| Claim citation coverage | 100.00% | 100.00% |
| Deterministic citation validity | 100.00% | 100.00% |
| Required source coverage | 98.53% | 93.33% |
| Abstention precision | 100.00% | 75.00% |
| Abstention recall | 100.00% | 100.00% |
| Abstention F1 | 100.00% | 85.71% |

Semantic DEV values are on the frozen 9-question calibration subset; held-out semantic values cover all 18 held-out questions.

| Semantic metric | DEV calibration | Held-out |
|---|---:|---:|
| Claim support rate | 85.00% | 95.83% |
| Partial support rate | 15.00% | 4.17% |
| Unsupported claim rate | 0.00% | 0.00% |
| Contradiction rate | 0.00% | 0.00% |
| Citation entailment rate | 72.73% | 93.88% |
| Citation non-entailment rate | 0.00% | 0.00% |
| Gold claim coverage | 83.33% | 78.85% |
| Missing gold claim rate | 8.33% | 11.54% |
| Answer completeness | 87.50% | 83.65% |
| Answer relevance | 1.8889/2 | 1.7778/2 |

## Held-out failure classification

- **ACIT-112 — retrieval/context coverage:** Appendix E Steps 1 and 2 reached context, but the required Appendix E Step 3 source did not. The model conservatively abstained. This caused the only answer-status error and the single false-positive abstention.
- **ACIT-105 — answer completeness/fidelity:** substantially correct but omitted some verification/ownership-chain qualification.
- **ACIT-108 — generation fidelity:** omitted the compliance-officer responsibility and strengthened a `should not preclude` formulation into a stronger obligation.
- **ACIT-113 — answer completeness:** examples were present but the general effective-control principle was not explicit.
- **ACIT-114 — context completeness:** one required Appendix G measure was absent from assembled context and therefore omitted.
- **ACIT-115 — generation completeness:** relevant evidence was present, but the answer omitted part of the required update/subscription rationale.

## Interpretation

The held-out system is strongest on **grounding and provenance**: claim citation coverage and deterministic citation validity are both 100%, with 0% unsupported claims, 0% contradictions, and 0% non-entailing citations under the frozen semantic review. The primary remaining weakness is **completeness**—either required evidence does not always reach the bounded context or generation omits part of evidence that is available.

These findings are evaluation results, not authorization to tune Retrieval v1. Any future retrieval/context changes must be developed as a new version and evaluated on a new benchmark.

## Frontend boundary

Stage 11 itself is backend/evaluation-only. A frontend is not required for evaluation correctness. The later RAG Playground/frontend stage may visualize these artifacts (question, retrieved evidence, answer, deterministic citations, semantic labels, and failure classification), but it should consume Stage 11 outputs rather than implement or alter scoring logic.
