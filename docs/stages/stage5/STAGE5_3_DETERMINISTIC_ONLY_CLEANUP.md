# Stage 5.3 — Deterministic-only cleanup

The experimental model-driven refinement path has been removed from the active project. Stage 5 now has one retrieval-output path: deterministic Semantic v2, with Semantic v1 retained only as a legacy comparison strategy.

Removed from the backend:

- external model SDK dependency and environment settings;
- model provider service and diagnostics;
- model-refinement API endpoints;
- separate model-refined chunk artifacts;
- provider/refinement schemas and tests.

Removed from the frontend:

- provider configuration/status UI;
- model-run diagnostics;
- model-refinement controls and output browser;
- model-specific API/types.

The deterministic Quality Gate remains part of the Stage 5 artifact and reports structural signals and automatic repairs produced by Semantic v2.

Current Stage 5 API:

```text
POST   /api/documents/{document_id}/chunks
GET    /api/documents/{document_id}/chunks
DELETE /api/documents/{document_id}/chunks
```
