# Stage 14.5B — Cross-App UI/UX Audit

## Scope
Stage 14.5B is a frontend robustness and consistency pass. It must not change retrieval, reranking, context assembly, generation, citation construction, frozen Stage 11 metrics, benchmark artifacts, database schema, or Docker/GPU behavior.

## Audit findings addressed
1. **Document-switch stale state** — a newly selected document could briefly leave the previous document actionable until asynchronous artifacts finished loading. The workbench now clears document-specific state, shows a selected-document loading state, and ignores stale asynchronous completions.
2. **Benchmark-detail request race** — rapidly opening benchmark cases could allow an older detail request to overwrite the newer case. Detail requests are now aborted/replaced and also abort when the drawer closes.
3. **Drawer keyboard focus** — citation and benchmark drawers now move focus to their close control when opened, close on Escape, and restore focus to the invoking control.
4. **Playground document-load ambiguity** — API failure is now distinct from a genuinely empty document library and exposes an explicit retry action.
5. **Nested sticky chrome** — the document workbench is scoped below the global RAG header on desktop; compact/mobile document bars no longer compete with the global sticky header.
6. **Upload keyboard access** — the native file input remains focusable while visually hidden, with visible focus treatment.
7. **Navigation semantics** — the active global destination exposes `aria-current=page`, and focus-visible styling is consistent across the shell.

## Acceptance gates
- Stage 14 focused tests + Stage 14.5B audit tests pass.
- Full backend regression passes.
- Stage 11 frozen baseline, held-out benchmark, and final evaluation reproduction remain PASS.
- Local `npm run build` passes.
- Docker rebuild/smoke passes.
- Browser checks cover document switching, drawer focus/Escape, benchmark rapid-case switching, API error/retry, and compact/mobile document chrome.
