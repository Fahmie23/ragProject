# Stage 14.3 — Retrieval & Context Inspector

## Goal
Expose the exact retrieval facts used by the production cited-answer request without rerunning retrieval and without changing frozen ranking behavior.

## Contract
- The production generation request still owns retrieval.
- Dense search, lexical search, weighted RRF, cross-encoder reranking, and Stage 8.2 context assembly execute once.
- `retrieval_trace_v1` copies already-computed candidate/ranking metadata from that execution.
- The trace never calls PostgreSQL, the embedding encoder, or the reranker a second time.
- React displays backend-owned trace facts only.
- Dense, lexical, RRF, and reranker scores are ranking/debugging signals, not correctness probabilities.

## Trace stages
1. Dense candidates (candidate_k)
2. Lexical candidates (candidate_k)
3. Deduplicated weighted-RRF union
4. Full reranker ordering, with Top-K context seeds marked
5. Stage 8.2 seed IDs and structural attachment IDs
6. Final generation evidence remains the existing `evidence` payload

## Safety / regression invariant
The trace reranker Top-K prefix must exactly match the production `hits` output from frozen Stage 8. This is covered by an automated contract test.

## Acceptance gates
- Stage 11 frozen baseline still passes.
- Stage 11 held-out benchmark freeze still passes.
- Stage 11 final evaluation reproduces offline.
- Stage 14.3 focused tests pass.
- Full backend regression passes.
- Frontend TypeScript/Vite build passes locally.
- Browser cited-answer response shows the Retrieval inspector from the same response payload.
- No extra retrieval HTTP request appears when opening the Retrieval tab.
