# UI/UX v2.9 — Page Elements and Tree Context

## Review Page Elements

The Review `Page Elements` panel is a navigation list, not a second inspector.
Each row now shows only:

- semantic type
- element ID
- a maximum two-line text preview

Detailed source metadata, bbox coordinates, relationships, and correction controls remain in the Correction Inspector.

## Document Tree Scope

### Review

Review uses a three-page context window:

- previous page
- current page
- next page

The current page is visually emphasized. Neighboring-page nodes and inherited ancestors are retained as context. Cross-page `continues` relationships remain clickable.

### Structure

Structure defaults to the same nearby three-page context because it is easier to inspect alongside the PDF. A `Nearby / Full` toggle keeps the complete canonical document hierarchy available when document-wide inspection is needed.

This preserves the distinction:

- Structure = inspect local context or the full document hierarchy
- Review = correct the current page with immediate neighboring context
