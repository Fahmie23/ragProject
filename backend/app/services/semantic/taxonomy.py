from __future__ import annotations

# The layout engine's role is evidence, not canonical semantic truth.
# These are the semantic classes that need contextual resolution because the
# same visual shape can represent different meanings in different documents.
CONTEXTUAL_TYPES = {
    "section_header",
    "group_header",
    "clause",
    "subclause",
    "paragraph",
    "list_item",
}

# Types whose vendor layout label is normally strong enough to retain unless a
# specialized Stage 4 resolver (definitions, footnotes, figures, etc.) repairs it.
DIRECT_LAYOUT_TYPES = {
    "title",
    "table",
    "figure",
    "caption",
    "page_header",
    "page_footer",
    "footnote",
    "formula",
}
