# Stage 4.5.8.16.2.1 — Frontend Compile Fix

This patch removes two stale `setApprovedIssueIds([])` calls left in `addSessionOperation()` and `addSessionOperations()` after the old relationship-approval UI state was removed in Stage 4.5.8.16.2.

No correction, resolver, validation, or Stage 5 gating behavior is changed.
