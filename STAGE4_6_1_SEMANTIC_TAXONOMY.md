# Stage 4.6.1 — Semantic Taxonomy Contract

The active canonical taxonomy is:

```text
title
subtitle
document_metadata
section_header
group_header
clause
subclause
definition_term
definition_text
paragraph
list_item
table
figure
caption
page_header
page_footer
footnote
formula
unknown
```

## Structural distinctions

### `section_header`
A document-outline heading whose scope extends across a section. It may create a `SectionRecord` and participates in heading-level hierarchy.

### `group_header`
A local label that organizes nearby members but does not create a document-outline section. Typical children are list items or one immediately scoped clause.

### `clause`
A numbered substantive proposition, requirement, procedure, or explanatory unit that is meaningful as a canonical clause.

### `subclause`
An enumerated child proposition with its own sentence/proposition semantics. The marker alone is insufficient; contextual and predicate evidence must support this type.

### `list_item`
An enumerated/bulleted member whose meaning depends materially on an introducing clause/group or list context. Short noun phrases and dependent verb phrases normally belong here.

### `paragraph`
Ordinary prose that is neither a structural heading nor an enumerated canonical member.

## Invariants

1. Layout role is not semantic truth.
2. `(a)`, `(i)`, `1.` or bullets do not determine semantic type by themselves.
3. `group_header` never creates a `SectionRecord`.
4. Clause hierarchy is represented by ClauseRecords + `parent_of`.
5. Local list/group dependency is represented by `introduces`.
6. Every final element carries auditable classification metadata.
7. Specialized definition/table/figure recovery may supersede early structural candidates.
8. Stage 4 must prefer `unknown`/lower confidence over unsupported semantic invention.
