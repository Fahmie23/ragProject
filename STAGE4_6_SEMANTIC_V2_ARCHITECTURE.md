# Stage 4.6 — Semantic Reconstruction v2

Stage 4 no longer treats PyMuPDF4LLM box classes as final semantic truth for ambiguous structural text.

## Pipeline

```text
Stage 3 immutable evidence
        ↓
PyMuPDF4LLM layout evidence
        ↓
initial canonical layout role
        ↓
feature extraction
        ↓
numbered-clause candidate classification
        ↓
sequence/context resolver
        ├─ list item vs subclause
        ├─ local group header
        └─ local heading before numbered clause
        ↓
existing specialized resolvers
        ├─ definitions
        ├─ figures
        ├─ footnotes
        ├─ tables
        └─ cross-page reconciliation
        ↓
hierarchy + relationships
        ↓
semantic advisory validator
        ↓
classification audit metadata
        ↓
Stage 4 canonical JSON schema 1.8
```

## Layout role vs semantic type

Every canonical element now preserves `layout_role`, e.g. `list-item` or `section-header`. The final `type` may differ after semantic resolution.

Example:

```json
{
  "layout_role": "list-item",
  "type": "list_item",
  "classification": {
    "selected_type": "list_item",
    "confidence": 0.94,
    "source": "sequence_resolver",
    "evidence": [
      "parallel alpha marker sequence contains 3 siblings",
      "nearby parent text introduces an enumeration",
      "text is phrase-like rather than an independent proposition"
    ],
    "alternatives": [
      {"type": "subclause", "score": 0.08}
    ]
  }
}
```

The vendor role is therefore evidence, not canonical semantic truth.

## `group_header`

Schema 1.8 adds `group_header` for local labels that organize a nearby list or clause without becoming a document-outline section.

Example:

```text
4.2 The inspection applies to the following equipment types:

Equipment
(a) Pumps;
(b) Valves;
(c) Sensors;
```

becomes:

```text
CLAUSE 4.2
  INTRODUCES → GROUP_HEADER Equipment
                    INTRODUCES → LIST_ITEM (a)
                    INTRODUCES → LIST_ITEM (b)
                    INTRODUCES → LIST_ITEM (c)
```

`group_header` is deliberately not a `SectionRecord`, so it cannot accidentally take ownership of the rest of the document.

## List item vs subclause

Numbering alone never determines `subclause`.

The resolver weighs generic signals:

- vendor layout role
- marker sequence consistency
- nearby list-introduction context
- punctuation
- word count
- sentence/proposition shape
- finite/modal predicate signals
- neighboring clause context

Phrase-like enumerated members are favored as `list_item`. Independently proposition-shaped members are favored as `subclause`.

## Relationships

Clause/subclause record hierarchy continues to use `parent_of` because Stage 4.5 validates it against `ClauseRecord`.

Local semantic dependencies introduced by the new resolver use `introduces`:

- clause → group header
- group header → list item
- group header → immediately scoped clause
- clause → directly introduced list item

This avoids overloading `parent_of` with relationships that are not backed by ClauseRecords and keeps Stage 4.5 integrity validation compatible.

Stage 5 Semantic v2 treats structurally compatible `introduces` edges as dependency evidence when forming retrieval units.

## Semantic validation

The new advisory validator checks semantic-v2 invariants such as orphan local group headers and low-confidence classifications. It emits Stage 4 warnings for review but does not invent repairs or replace the stricter Stage 4.5 relationship-integrity gate.

## Compatibility

The mature Stage 4 logic for definitions, logical tables, figures, appendices, footnotes, TOC handling, cross-page reconciliation, and Stage 3 provenance is retained. Those systems can still override an earlier tentative structural label. A final audit pass ensures `classification.selected_type` always matches the final canonical `type`.

## Genericity

The semantic-v2 service contains no document-specific AML/CDD/PEP vocabulary, page numbers, or fixed clause IDs. New regression fixtures use unrelated operations-manual and safety-standard examples.

The approach still depends on usable Stage 3 geometry/text and sufficiently coherent layout reading order. When contextual evidence is weak, the resolver remains conservative and exposes lower confidence rather than inventing document structure.
