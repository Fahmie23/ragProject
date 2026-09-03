# Stage 14.2B — Playground UI/UX Restructuring

Status: candidate until local TypeScript/Vite build and browser smoke pass.

## Goal

Keep the Stage 14.2 production Q&A behavior unchanged while improving information hierarchy and readability.

## Design changes

- The answer remains the primary surface.
- Validated sources remain visible beside the answer.
- Claims, context evidence, and runtime metadata move into a progressive-disclosure **Answer inspector**.
- Context evidence is labelled **USED** vs **AVAILABLE** so retrieved/context evidence is not confused with evidence explicitly referenced by generated claims.
- Production configuration is available on demand rather than occupying the main answer header.
- Pipeline counts (claims, context chunks, used evidence, validated sources) are displayed as observable backend facts, not quality scores.
- No evaluation metric is calculated by React.

## Non-goals

- No Stage 6–11 behavior changes.
- No retrieval trace additions.
- No evaluation dashboard implementation.
- No new API calls.
- No benchmark or prompt changes.

## Acceptance gates

1. Existing Stage 14.1 + 14.2 contract tests continue to pass.
2. Stage 14.2B UI architecture tests pass.
3. Full backend regression passes.
4. `npm run build` passes.
5. Docker frontend rebuild succeeds.
6. Browser smoke confirms:
   - answer and sources are readable without opening inspectors;
   - Claims tab shows claim → evidence/citation mapping;
   - Context tab shows all context chunks and visually distinguishes USED vs AVAILABLE;
   - Technical tab shows runtime/configuration metadata only;
   - inline citations still open the correct PDF page;
   - abstention still renders without fabricated citations;
   - retrieval experiment mode remains isolated.
