# Stage 4.5.8.16.1 — Frontend Compile Fix

This patch fixes a TypeScript compile regression introduced when the simplified correction UI removed the legacy cross-page and definition-term source state.

`savePage`, `resetPage`, and `resetAll` still called the removed setters `setCrossPageSource` and `setDefinitionTermSource`, producing six `TS2304` errors. Those stale cleanup calls have been removed. No correction behavior or backend schema is changed.

The active Stage 4.5.8.16 workflow remains:

- Element correction
- Exact text-span correction
- Contextual DefinitionEntry selection for `definition_text`
- Deterministic backend relation maintenance
- Integrity checking

Legacy cross-page and definition-term source editor state is not restored.
