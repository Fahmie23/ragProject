# Stage 4.6.2 — Semantic v2.1: Scope, Continuation, Confidence, and Validation

Stage 4 Semantic v2.1 strengthens the deterministic semantic layer introduced in Stage 4.6. It does **not** change Stage 5 and does not add an LLM.

## Why this iteration exists

Semantic v2 correctly separated layout roles from semantic roles and fixed common list-vs-subclause errors. A real-page review then exposed four higher-level weaknesses:

1. a second local group with only one member could remain a `section_header`;
2. consecutive headings could create an empty sibling section when one was only a local scope label;
3. page-edge geometry could falsely connect a previous block to a fresh numbered clause;
4. classification alternatives could look probabilistic while exceeding 100% when combined with the selected confidence.

Semantic v2.1 addresses those issues with generic structural invariants.

## Updated deterministic flow

```text
layout evidence
  -> feature extraction
  -> numbered-clause candidate classification
  -> enumerated sequence resolution
  -> parallel local-group propagation
  -> heading scope resolution
  -> specialized definition/table/figure repair
  -> section/clause/group relationship construction
  -> semantic continuation guard
  -> hierarchy-aware confidence calibration
  -> advisory semantic validation
```

## 1. Parallel local-group propagation

A local group is no longer required to have multiple children when a previous sibling group has already established the shared introductory scope.

Example:

```text
4.2 Supported device categories include the following:

Desktop devices
(a) Workstations;
(b) Laptops;

Mobile devices
(a) Tablets
```

Target structure:

```text
CLAUSE 4.2
├── GROUP_HEADER Desktop devices
│   ├── LIST_ITEM (a)
│   └── LIST_ITEM (b)
└── GROUP_HEADER Mobile devices
    └── LIST_ITEM (a)
```

The resolver requires a preceding resolved `group_header`, compatible horizontal/typographic geometry, and a shared earlier list introducer. It does not use domain vocabulary.

## 2. Heading scope resolution

TOC and typography are now treated as evidence with different strengths rather than independent final decisions.

A conservative high-value rule handles consecutive headings with no body content between them:

- weak typography-only heading -> strong TOC/numbering heading: the weak heading becomes `group_header`;
- strong outline heading -> weak short label -> numbered clause: the weak short label can become `group_header`;
- strong/strong and weak/weak ambiguity is preserved for review.

This avoids empty sibling sections without discarding strong PDF outline evidence.

## 3. Semantic continuation guard

The generic cross-page open-block reconciler still uses page-edge geometry, column overlap, section continuity, marker relationships, text completeness, and font compatibility. Semantic v2.1 adds a veto layer before accepting a relation.

A target that starts a fresh semantic unit is a hard boundary. In particular:

```text
previous page: 2.4 ...
next page:     2.5 ...
```

must not produce:

```text
2.4 -> continues -> 2.5
```

A fresh numbered canonical `clause` now blocks the generic continuation relation even when geometry aligns strongly.

## 4. Confidence normalization

`classification.confidence` remains deterministic support for the selected type, not a statistically calibrated probability. However, when alternatives are present their scores are normalized into the remaining support mass.

Example:

```text
selected List item: 70%
alternative Subclause: 30%
```

instead of an incoherent display such as 70% + 44%.

## 5. Hierarchy-aware confidence calibration

Text shape alone is not enough for high confidence. After sections and relationships are built, Stage 4 lowers confidence when structural ownership is unresolved, without changing the selected type.

Examples:

- sequence-resolved enumerated `list_item` with no `introduces`/`parent_of` relation;
- `group_header` with no incoming or outgoing semantic dependency;
- section heading with no direct content and no child sections.

This makes Review confidence reflect the final reconstructed graph, not only the element classifier.

## 6. Advisory semantic validation

The automatic validator now reports review warnings for:

- low-confidence classifications;
- orphan local group headers;
- enumerated list items with no semantic owner;
- empty leaf section scopes;
- any remaining `continues` relation whose target is a fresh numbered clause.

These are diagnostics. Blocking correction integrity remains Stage 4.5's responsibility.

## Genericity contract

Production rules do not contain document-specific legal, AML, CDD, PEP, equipment, employee, or policy terminology. Decisions are based on:

- canonical semantic type;
- vendor layout role;
- numbering and marker families;
- punctuation and proposition shape;
- adjacency and sequence;
- geometry and font compatibility;
- TOC/numbering/font-rank heading evidence;
- resolved semantic relationships.

## Regression coverage

Semantic v2.1 adds generic fixtures for:

- a parallel group with one member;
- weak local heading before a strong outline heading;
- a fresh numbered clause across a page break;
- normalized alternative support;
- empty leaf section scope warnings;
- unowned sequence list-item warnings.

The existing real continuation test remains in place to ensure the semantic guard does not suppress genuine prose continuation.
