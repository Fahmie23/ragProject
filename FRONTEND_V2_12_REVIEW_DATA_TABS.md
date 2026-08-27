# Frontend V2.12 — Advanced Review Data tabs

The Stage 4.5 review-data navigation is now one compact segmented tab group beneath a dedicated `Advanced review data` label. This replaces the previous CSS pseudo-element inside a four-column grid, which created five grid items and forced `Correction Log` onto a second row.

The Correction Log view also no longer renders a second duplicate `PageJsonPanel`; `CorrectionsPanel` remains the single owner of its `Operations` and `Correction JSON` tabs.
