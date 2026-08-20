# Stage 4.2 Frontend UX Patch

This patch changes only the frontend. The Stage 1–4 backend and stored JSON schemas remain unchanged.

## 1. Page-level JSON in Stage 3 and Stage 4

Both page inspection workspaces now have two inspector modes:

- **Elements** — the existing cards/filter view.
- **Page JSON** — a focused JSON payload for the currently selected page.

Stage 3 page JSON includes:

```text
stage
schema_version
document_id
source_filename
source_sha256
extractor
page
```

The `page` object is the exact Stage 3 `PageExtraction` object, including blocks, lines/spans, tables, warnings and coordinates.

Stage 4 page JSON includes:

```text
stage
schema_version
document_id
source_filename
source_sha256
document_title
document_subtitle
sections_referenced_on_page
page
```

The `page` object is the exact canonical `StructuredPage`. `sections_referenced_on_page` adds only the section records needed to understand elements on that page.

Each Page JSON view has:

- **Copy JSON**
- **Download JSON**

Downloaded names are page-specific, for example:

```text
<document-id>-stage3-page-1.json
<document-id>-stage4-page-1.json
```

### Shared page navigation

The selected page is now owned by the document workspace rather than independently by Stage 3 and Stage 4.

Example:

1. Open Stage 3 and go to page 7.
2. Switch to Structured document.
3. Stage 4 remains on page 7.

This makes raw-vs-canonical comparison much easier.

## 2. Collapsible document sidebar

The left sidebar now supports two desktop states:

### Expanded

- Brand and workspace name
- Upload panel
- Full document names and states
- Collapse button

### Collapsed

- 72 px compact rail
- R logo
- Expand button
- Add-document shortcut (expands the sidebar)
- Compact document type buttons
- Status dots
- Filename tooltips

The preference is stored in browser `localStorage` under:

```text
rag-sidebar-collapsed
```

so it persists after refresh.

On smaller screens the compact rail becomes a horizontal top strip rather than consuming page width.

## Files changed

```text
frontend/src/App.tsx
frontend/src/styles.css
frontend/package.json
```

No backend file needs to be replaced for this patch.

## Apply to an existing Stage 4.1 project

Back up first:

```bash
cd ~
cp -a ragProject ragProject_before_stage4_2
```

Copy the three changed frontend files from this package into:

```text
~/ragProject/frontend/
```

Then:

```bash
cd ~/ragProject/frontend
npm install
npm run dev
```

If dependencies are already installed, `npm run dev` is enough.

## Verification checklist

1. Collapse the sidebar and refresh the browser — it should remain collapsed.
2. Expand it again — document names and upload UI should return.
3. Open **Raw extraction**, select page 2, then choose **Page JSON**.
4. Copy/download the Stage 3 page JSON.
5. Switch to **Structured document** — it should still be on page 2.
6. Choose **Page JSON** and inspect/download the Stage 4 page JSON.
7. The existing **JSON artifacts** tab should still show full-document JSON separately.
