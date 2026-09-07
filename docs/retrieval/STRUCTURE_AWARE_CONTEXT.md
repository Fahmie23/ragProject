# Structure-Aware Context Assembly

## Purpose

Retrieval ranking and evidence assembly solve different problems. A top-ranked chunk may be correct but incomplete when part of its meaning lives in a canonical continuation, introduced list member or directly attached table.

Stage 8.2 therefore adds deterministic context **after** reranking.

```text
Hybrid + reranker
      ↓
Top-K seed chunks
      ↓
structural_one_hop_v1
      ↓
seed evidence + bounded attached evidence
      ↓
grounded generation
```

## Frozen policy

The held-out Retrieval v1 report records the production policy as:

- policy: `structural_one_hop_v1`;
- same-section structural checks;
- non-recursive expansion;
- page gap bounded to at most one page where applicable;
- top-5 reranked seeds for the generation evidence budget.

The exact implementation owns the relationship compatibility rules; the key product invariant is that expansion is bounded and does not recursively walk the full document graph.

## Ranking boundary

Attached context is not a new retrieval score and does not alter the seed ranking. Retrieval metrics and context metrics are therefore reported separately.

## Held-out context results

On the frozen 15-question retrieval held-out split, Hybrid + Reranker plus Stage 8.2 achieved:

| Metric | Result |
|---|---:|
| ContextRecall@3 | 83.3% |
| ContextCompleteEvidence@3 | 80.0% |
| ContextRecall@5 | **90.0%** |
| ContextCompleteEvidence@5 | **86.7%** |
| Average context chunks at K=5 | **5.27** |

## Known boundary

One-hop expansion can still miss evidence when the required item is neither retained by the candidate/reranker path nor reachable by the permitted structural edge. The frozen held-out set intentionally preserves such failures rather than patching Retrieval v1 against them.

The Stage 11 answer/citation evaluation confirms that **completeness**, not unsupported hallucination, remains the primary downstream weakness.
