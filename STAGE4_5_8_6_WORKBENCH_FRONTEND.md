# Stage 4.5.8.6 — Document Workbench Frontend

This update reorganizes the frontend around an end-to-end document-processing workbench while preserving the existing Stage 3, Stage 4, Stage 4.5, correction sandbox, and JSON artifact workflows.

## Primary navigation

The selected document now exposes a pipeline-oriented navigation bar:

```text
Document → Extraction → Layout → Structure → Review → Chunking → Retrieval → Evaluation
```

The currently implemented stages are interactive. Chunking, Retrieval, and Evaluation are visibly marked as planned and remain disabled so the frontend does not imply backend capabilities that do not exist yet.

## New Layout workspace

The Layout workspace is a dedicated extraction-QA screen. Its primary purpose is to answer:

> What does this JSON say the page looks like?

Supported sources:

- resolved Stage 4.5 JSON after saved corrections
- Stage 4 canonical page JSON (`page.elements`)
- Stage 3 extraction JSON (`page.blocks` + `page.tables`)
- manually pasted page/document JSON for local inspection

Supported views:

- **Reconstructed** — blank page rebuilt only from JSON geometry and content
- **Original PDF** — source PDF page preview
- **Compare** — original and reconstructed page side by side

The reconstructed page uses the JSON page width/height plus every element `bbox` to position content. This is intentionally independent from the source PDF preview.

## Inspection controls

The Layout workspace supports:

- bounding-box visibility
- element labels
- reading-order markers
- element-type filtering
- element selection
- selected element details
- selected/raw page JSON inspection
- table row/cell inspection
- basic JSON consistency checks

Basic checks include:

- invalid or zero-size bounding boxes
- bounding boxes outside the page
- duplicate reading-order values
- table row-count/cell-count mismatch
- table rows exceeding declared column count

These checks do not claim that the extraction matches the PDF. Visual comparison with the original PDF remains the authoritative human QA step.

## Table reconstruction limitation

The current schema stores a bounding box for the whole table and structured `cells`, but not a bounding box for each individual table cell. The reconstructed table therefore distributes internal cells evenly within the table bounding box. This is useful for semantic inspection, but it is not a pixel-perfect reproduction of the source table.

## Paste JSON support

The Layout workspace accepts page-level wrappers such as:

```json
{
  "page": {
    "page_number": 3,
    "width": 597,
    "height": 843,
    "elements": []
  }
}
```

It also accepts:

- a direct Stage 4 page object
- a full object with `pages`
- Stage 3 page objects containing `blocks` and `tables`

Pasted JSON is frontend-only and does not modify pipeline artifacts.

## Existing functionality preserved

No backend pipeline behavior was changed in this update. Stage 4.5.8.5 cross-page TOC inheritance remains unchanged.

Backend regression suite:

```text
55 passed
```

The frontend TypeScript source was syntax checked and type checked with local React type stubs because npm dependencies are not installed in the build container. A normal project checkout should still run:

```bash
cd frontend
npm install
npm run build
```
