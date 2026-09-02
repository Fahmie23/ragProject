# Frontend V2 UI/UX Architecture

This frontend redesign keeps the existing Stage 1–4.5 backend contracts and correction model intact while reorganizing the user experience around the selected document.

## Primary navigation

- **Sidebar:** document upload and document selection only.
- **Document workflow:** Overview → Extraction → Structure → Review → Chunking.
- **Chunking:** available after Stage 4 exists; the page exposes the Stage 5 eligibility gate and only generates chunks from an eligible saved resolved artifact.
- **Advanced:** Layout and raw JSON remain available as developer/debug views without competing with the primary workflow.

## V1 document scope

The upload UI intentionally accepts PDF only. The current extraction path is designed for digitally generated PDFs with extractable text layers. OCR-dependent scanned/mixed PDFs remain outside this V1 UI scope.

## Screen responsibilities

### Overview

Shows document metadata, pipeline status, artifact counts, correction count, integrity state, and Stage 5 readiness using existing backend fields only.

### Extraction

Read-only inspection of Stage 3 output. The existing PDF preview, page navigation, bounding boxes, extracted elements, and page JSON remain available.

### Structure

Read-only inspection of Stage 4 interpretation. A Document Tree visualizes structural containment and semantic hierarchy. Selecting a tree node navigates to and selects the corresponding PDF element.

### Review

The primary human-in-the-loop workspace is organized as:

```
Resolved Document Tree | PDF Viewer | Correction Inspector
```

The tree uses the resolved structure plus the current page correction preview. It therefore provides visual confirmation while corrections are being prepared. Existing non-destructive Stage 4.5 operations remain the source of truth.

### Cross-page continuation

`continues` relationships are intentionally distinct from parent/child nesting. The tree renders them as continuation links (for example, `continues on page 10`) and the selected-region inspector exposes quick navigation to the counterpart element.

### Chunking

Stage 5 is implemented as four compact views: **Overview**, **Cleaning**, **Chunk Preview**, and **Chunk JSON**. Cleaning decisions are auditable, chunk settings are explicit, and the chunk inspector preserves source-page and provenance navigation. The page can be opened after Stage 4 so users can understand why Stage 5 is blocked before finalizing Review.

## Source organization

New UI responsibilities have been separated into dedicated modules:

```
src/
├── app/
│   ├── App.tsx
│   └── workspace.ts
├── components/
│   ├── layout/
│   │   ├── DocumentSidebar.tsx
│   │   └── DocumentWorkflowNav.tsx
│   └── structure/
│       └── DocumentTree.tsx
├── features/
│   └── workbench/
│       └── WorkbenchApp.tsx
├── hooks/
│   └── useViewportMode.ts
├── pages/
│   ├── OverviewPage.tsx
│   └── ChunkingPage.tsx
└── utils/
    └── documentTree.ts
```

`WorkbenchApp.tsx` is deliberately retained as a transitional feature container because it owns mature Stage 3/4/4.5 state and correction behavior. The redesign extracts new shared UI incrementally rather than rewriting the correction engine and risking regressions.

## Validation

- Backend regression suite: 125 tests passed.
- TypeScript semantic check performed with the local compiler and temporary React declarations because this execution environment does not contain the project's npm dependencies.
- A full `npm run build` should be run locally after `npm install`/`npm ci`. The current execution environment could not reach the npm registry, so the Vite production bundle could not be produced here.

## Responsive workspace contract

The UI uses four intentional viewport modes. These modes are layout-only state and must never reset document, page, selection, span, or correction-draft state.

| Mode | Width | Document navigation | Review behavior |
| --- | ---: | --- | --- |
| Large | `>= 1440px` | Expanded/collapsible sidebar | Resolved Tree + PDF + Inspector remain visible |
| Desktop | `1180–1439px` | Fixed 72px document rail | Compact three-column Review remains visible |
| Compact | `768–1179px` | Sticky document bar | PDF is primary; Tree and Inspector are drawers |
| Mobile | `< 768px` | Sticky compact document bar | PDF is primary; Tree and Inspector become full-screen task panels |

### State invariants

Responsive changes are not navigation events. Resizing the browser must preserve:

- current document
- current page
- selected canonical element(s)
- selected Stage 3 spans
- unsaved correction operations
- draft semantic/relationship correction state
- current resolved/correction preview

The responsive hook stores only the viewport mode. Review drawer state (`tree`, `inspector`, or PDF) and compact inspector view (`correct` or `page`) are separate UI-only state.

### Review desktop behavior

On Large and Desktop modes the application shell owns the viewport. The Review workspace uses the remaining vertical space and each panel scrolls independently:

```
Resolved Tree | PDF Viewer | Correction Inspector
   scroll     |   scroll   |       scroll
```

The browser page must not become a multi-screen-tall correction workspace simply because a PDF page or document tree is long.

### Review compact/mobile behavior

Tree and Inspector are overlays rather than stacked content. The bottom Review dock provides:

- **Tree** — open resolved document hierarchy
- **PDF** — return to the primary PDF canvas
- **Correct** — open selected corrected-region controls
- **Page** — inspect all corrected regions / Stage 3 spans for the page

Selecting a PDF region opens `Correct`. Selecting a tree node navigates/selects the corresponding element and returns to the PDF. Cross-page continuation navigation follows the same state-preserving page-navigation path.

### Responsive priority

When horizontal space decreases, the UI sacrifices secondary chrome before the PDF viewer:

1. Document sidebar becomes a rail.
2. Document sidebar becomes the compact document bar.
3. Document Tree becomes a drawer.
4. Correction Inspector becomes a drawer/full-screen task panel.
5. PDF remains the primary workspace.

Inspection-only pages (Extraction and Structure) may stack their inspector/tree below the viewer at compact widths because they do not require simultaneous correction interaction.

## v2.4 Review workbench polish

This revision fixes three usability defects found during real-document testing:

- Sidebar collapse control is contained inside the sidebar rather than straddling the app boundary, preventing clipping at browser zoom/device-scale combinations.
- Review Tree, PDF viewer, Inspector, Page Elements, and extracted-text areas use stable visible scrollbars with reserved scrollbar gutters.
- Selected Corrected Region is a true narrow-inspector form. Semantic type, extracted text, continuations, 2x2 bbox coordinates, suppress action, and required relationships stack vertically and cannot overlap.

Responsive layout changes remain UI-only and do not reset page, selected element, selected spans, or unsaved correction operations.
