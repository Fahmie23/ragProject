# Answer and Citation Evaluation

## Status

Stage 11 is complete and frozen. The production pipeline remained unchanged while the final benchmark was consumed.

The evaluation is intentionally separate from retrieval benchmarking.

## Datasets

```text
DEV
  20 questions
  used to build/calibrate the frozen semantic rubric

Independent held-out
  18 questions
  ├─ 15 answerable
  └─ 3 out-of-scope / abstention controls
  frozen before execution and consumed once
```

Held-out responses are hash-bound snapshots and were not regenerated for tuning.

## Deterministic metrics

The evaluation measures:

- answer-status accuracy;
- abstention precision/recall/F1;
- claim citation coverage;
- deterministic citation validity;
- required source coverage.

## Human semantic review

`stage11_semantic_rubric_v1` uses frozen human labels rather than an automated semantic judge. Semantic review covers:

- fully/partially/unsupported/contradicted claims;
- citation entailment;
- gold-claim coverage;
- answer completeness;
- answer relevance.

An LLM judge is not authorized for the frozen v1 result.

## Final held-out results

| Deterministic metric | Held-out |
|---|---:|
| Questions | 18 |
| Answer status accuracy | **94.44%** |
| Claim citation coverage | **100.00%** |
| Deterministic citation validity | **100.00%** |
| Required source coverage | **93.33%** |
| Abstention precision | 75.00% |
| Abstention recall | **100.00%** |
| Abstention F1 | 85.71% |

| Semantic metric | Held-out |
|---|---:|
| Fully supported claim rate | **95.83%** |
| Partial support rate | 4.17% |
| Unsupported claim rate | **0.00%** |
| Contradiction rate | **0.00%** |
| Citation entailment | **93.88%** |
| Citation non-entailment | **0.00%** |
| Gold claim coverage | 78.85% |
| Answer completeness | **83.65%** |
| Answer relevance | 1.7778 / 2 |

## Interpretation

The strongest result is **grounding and provenance**: every generated claim was cited, deterministic citation validity was 100%, and the frozen human review found no unsupported or contradicted claims.

The main weakness is **completeness**. Missing information came from both evidence-assembly gaps and generation omitting part of evidence that was available.

Representative failures include:

- `ACIT-112`: required Appendix E Step 3 did not reach context, so the model conservatively abstained.
- `ACIT-105`: substantially correct ownership/trust answer omitted some verification/chain-of-control qualification.
- `ACIT-108`, `ACIT-113`, `ACIT-115`: generation omitted or strengthened part of the required meaning.
- `ACIT-114`: one required Appendix G measure was absent from assembled context.

The benchmark supports the distinction **grounded ≠ complete**.

## Reproducibility

Stage 12 can reproduce the final deterministic + frozen-human metric outputs offline from the exact captured response snapshots with zero provider calls. The held-out benchmark is evaluation evidence, not authorization to tune Retrieval v1.
