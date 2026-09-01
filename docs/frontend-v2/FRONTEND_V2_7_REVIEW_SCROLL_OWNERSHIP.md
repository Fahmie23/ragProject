# Frontend V2.7 — Review scroll ownership

Desktop Review now has two deliberate scroll phases.

1. **Main page phase** — the browser scrolls through the document header, workflow navigation, review summary and correction controls.
2. **Workbench phase** — once the Review workbench reaches 12px from the top of the viewport, the main page has reached its practical maximum. The workbench fills the remaining viewport and the Resolved Tree, PDF Viewer and Correction Inspector scroll independently.

The PDF's rendered height is never allowed to determine the browser page height.

A `wheel` guard on the Review grid ensures that wheel/touchpad input over Tree/PDF/Inspector still finishes the main-page movement first. After the workbench reaches its resting position, the event is no longer intercepted and the panel under the pointer scrolls normally.

This state transition is presentation-only; selected page, selected element, unsaved corrections, Stage 3 span selection and relationship drafts are not changed.
