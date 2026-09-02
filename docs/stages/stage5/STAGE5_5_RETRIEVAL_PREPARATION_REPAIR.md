# Stage 5.5 — Retrieval Preparation Repair

## Status

Implemented and regression-tested against the current 109-page SC AML/CFT benchmark.

This repair does **not** redesign Stage 5. The existing deterministic semantic chunking architecture remains in place. The changes close four retrieval-preparation gaps discovered during an audit of the Stage 5 artifact generated from the accepted Stage 4 `(9).json` benchmark.

## Why this repair was needed

The previous Stage 5 artifact passed its deterministic quality report but still contained table-of-contents/navigation chunks. It also separated table captions from the tables they describe, and Stage 6 could have allowed the embedding model to silently truncate a chunk that exceeded its exact tokenizer limit.

The goal of this repair is to ensure that failures in retrieval preparation are not later misdiagnosed as embedding-model or retrieval-model failures.

## Repair 1 — Stage 4 navigation-zone signals are now respected

Stage 4 intentionally preserves TOC navigation labels for provenance and marks them with signals such as:

- `role_source = toc_navigation_suppression`
- `classification.source = document_zone_resolver`
- classification evidence indicating table-of-contents navigation

Stage 5 previously relied mainly on section ancestry such as a section literally named `Contents`. That was insufficient because TOC tables can inherit an unrelated front-matter section id.

Stage 5 now:

1. consumes explicit Stage 4 navigation signals;
2. identifies high-confidence TOC table structure;
3. extends navigation context across contiguous TOC table pages;
4. excludes navigation-only `unknown`, table, paragraph, list/group and section-header elements before semantic unit construction.

The logic is structural and does not hard-code benchmark page numbers or document-specific wording.

## Repair 2 — Independent navigation leakage quality check

The Stage 5 quality gate previously reused the same section-ancestry assumption as the cleaner. This allowed both cleaner and validator to agree on an incorrect `navigation_chunk_count = 0`.

The quality checker now independently flags a chunk when its source contains any of the following:

- an explicit Stage 4 navigation signal;
- source content on a page with an explicit navigation marker;
- a high-confidence TOC table structure;
- navigation section ancestry.

This means disabling or regressing the cleaner can no longer automatically produce a false quality PASS.

## Repair 3 — Table caption ownership

Standalone captions immediately preceding a table are now attached to that table semantic unit when:

- the caption is directly adjacent in canonical document order;
- it is on the same page;
- it is not already owned by a `FigureRecord`;
- it remains retrieval-eligible.

This fixes both observed patterns:

```text
Clause 3.5
Example 1:
[table]
```

and:

```text
Example 2:
[table]
```

The resulting chunk is:

```text
semantic_type = table
source_element_ids = [caption, table]
refinement_tags = [caption_attachment]
```

`caption` was also added as a semantic boundary so a previous clause cannot absorb a table caption.

Figure captions continue to be owned through the existing `FigureRecord` path.

## Repair 4 — Exact embedding-token compatibility contract

Stage 5 intentionally remains model-independent and continues to record:

```text
token_count_method = regex_estimate_v1
```

The regex estimate is useful for deterministic chunk construction, but it is not a safe guarantee for a transformer embedding model.

Stage 6 now performs an exact compatibility check using the selected sentence-transformer tokenizer before encoding any chunk:

```text
Stage 5 semantic chunk
        ↓
Stage 6 exact model tokenizer
        ↓
within model max_seq_length?
   ├── yes → embed
   └── no  → reject with HTTP 409
```

Stage 6 does **not** silently truncate an overlong retrieval chunk. The API response identifies the offending chunk index/id, exact model token count and model maximum sequence length so Stage 5 can be regenerated with a safer budget if necessary.

This preserves the correct architecture boundary:

- Stage 5 owns semantic chunking.
- Stage 6 owns embedding-model compatibility.

## Benchmark before/after

Source: accepted Stage 4 `(9).json`, 109 pages.

| Metric | Before repair | After repair |
|---|---:|---:|
| Retrieval chunks | 278 | 267 |
| Estimated tokens | 36,339 | 35,483 |
| Average estimated tokens/chunk | 130.72 | 132.90 |
| Minimum estimated tokens | 1 | 8 |
| Maximum estimated tokens | 683 | 683 |
| TOC/navigation chunks present | 10 | 0 |
| Navigation elements excluded | incomplete | 11 |
| `unknown` retrieval chunks | 5 | 0 |
| Table chunks | 18 | 13 |
| Table-caption attachments | 0 | 2 |
| Deterministic quality status | PASS (false navigation blind spot) | PASS |
| Orphan children | 0 | 0 |
| Dangling intros | 0 | 0 |

The reduction from 18 table chunks to 13 is expected: five TOC/navigation tables are no longer indexed. The reduction from 278 to 267 chunks consists of the removed navigation material plus caption/table consolidation.

## Benchmark caption results

### Page 74

Before:

```text
Clause 3.5 + "Example 1:"
Table without caption
```

After:

```text
Clause 3.5

Table chunk:
Example 1:
Risk Factor | Examples | Formulated Parameters
...
```

### Page 76

Before:

```text
Standalone caption chunk: "Example 2:"
Separate table chunk
```

After:

```text
Table chunk:
Example 2:
Risk Factor | Parameters determined for risk profiling | Risk Rating
...
```

## Regression tests added

Stage 5 now explicitly tests:

1. explicit Stage 4 TOC-zone suppression;
2. navigation inheritance into a continuation TOC table page;
3. independent quality detection when navigation cleaning is deliberately disabled;
4. caption ownership by a following table;
5. prevention of caption absorption by a previous clause.

Stage 6 additionally tests:

1. exact-tokenizer overflow rejection;
2. safe inputs continue to embed normally.

## Regression result

```text
232 passed
```

The existing Stage 3–6 regression suite remains green.

## Current Stage 5 acceptance status

For the benchmark document, Stage 5 retrieval preparation is now suitable to proceed to embedding compatibility validation and dense retrieval evaluation.

The remaining `max_tokens = 700` value is still a semantic/estimated-token ceiling, not a claim about any specific embedding model. The exact Stage 6 tokenizer guard is authoritative for embedding compatibility.

---

## Stage 5.6 — Final Retrieval-Quality Correction

### Scope

Stage 5.6 is a narrow follow-up to Stage 5.5. It addresses two retrieval-quality issues found in the Stage 5 JSON generated by the application after the Stage 5.5 fixes:

1. local `group_header` labels could still become standalone retrieval chunks even when the real answer lived in the following clause/table/figure;
2. a figure with no extracted visual/caption/explanation/source text could still create a retrieval chunk containing only an introduction such as `illustrated in the diagram below`.

The correction does not change definition grouping, clause hierarchy, cross-page continuation, table reconstruction, caption ownership, sibling packing, navigation filtering, or Stage 3/4 provenance.

### Group-header context attachment

Header-only `group_header` units are no longer indexed independently when answer-bearing content follows in the same document-root scope.

Instead, Stage 5 preserves the heading as retrieval context:

```text
Group: Delayed verification

8.1.24 ...
8.1.27 ...
8.1.28 ...
```

The heading IDs are stored in:

```text
context_element_ids
```

rather than being duplicated as source content. The generated chunk receives:

```text
refinement_tags = ["group_header_context", ...]
```

Consecutive local headings are represented as a compact context chain:

```text
Group: CDD requirements for individual customer and beneficial owner > Identification and Verification
```

The scope terminates when Stage 5 reaches another local-group boundary or a different top-level document root. A target unit that already contains a `group_header` source is also treated as a boundary, preventing a prior heading from bleeding through an existing canonical local group.

A genuinely header-only tail with no following body is retained rather than silently deleted.

### Intro-only figure suppression

For text-only retrieval, Stage 5 now detects a conservative figure case:

```text
figure visual text = empty
caption text       = empty
explanation text   = empty
source text        = empty
intro text         = present
```

For this case, the introductory text remains auditable in the Stage 4 figure relationship but becomes Stage 5 context-only material:

```text
action = context
reason = figure_intro_context_only
```

It is not embedded as a standalone answer-bearing chunk.

Figures that have useful captions and/or explanatory text continue to become normal `figure` chunks. This keeps the rule conservative and avoids removing useful illustration explanations.

### Metadata preservation during generic packing

Generic unit packing now preserves:

- `retrieval_context_text`;
- `context_element_ids`;
- `refinement_tags`.

This is required so local-group context is not lost if downstream generic units are packed together.

### Quality-report additions

The deterministic quality report now records:

```text
group_header_context_chunk_count
standalone_group_header_chunk_count
intro_only_figure_chunk_count
```

An intro-only figure that remains independently retrievable is treated as a hard deterministic quality issue. Standalone group headers are reported as an audit metric rather than an unconditional failure because a genuinely header-only document tail can be legitimate.

### Configuration

The default semantic-v2 configuration now includes:

```text
attach_group_headers_as_context = true
suppress_intro_only_figure_chunks = true
```

Both behaviors are explicit and testable.

### Reference replay against accepted Stage 4 `(9).json`

A deterministic replay using the accepted Stage 4 `(9).json` structure produced:

```text
chunk_count                         261
estimated_token_count              36,372
min_chunk_tokens                   8
max_chunk_tokens                   683
average_chunk_tokens               139.36
navigation_chunk_count             0
orphan_child_count                 0
dangling_intro_count               0
group_header_context_chunk_count   80
standalone_group_header_chunk_count 0
intro_only_figure_chunk_count      0
quality.status                     pass
```

The replay also verified:

```text
retrieval-eligible elements with no source/context coverage = 0
duplicate source-element ownership                        = 0
```

The application-generated resolved artifact can have a different chunk count from this reference replay because Stage 4.5 correction state can alter canonical relationships. The acceptance criteria are therefore semantic invariants, not an exact expected chunk count.

### Regression tests

Stage 5.6 adds regression coverage for:

1. consecutive local group headings attached as context;
2. local group context stopping at the next local group;
3. removal of Top-K-only heading chunks;
4. context-element provenance retention;
5. intro-only figure suppression;
6. preservation of figures with meaningful caption/explanation content;
7. local-group context crossing descendant sections while stopping at a new document root.

Full backend regression result:

```text
235 passed
```

### Freeze criterion

Stage 5 should now be frozen once the application-generated chunk artifact confirms:

- navigation chunks remain `0`;
- orphan/dangling counts remain `0`;
- `intro_only_figure_chunk_count = 0`;
- meaningful local headings appear in `context_text` / `context_element_ids` rather than as empty-answer standalone chunks;
- exact Stage 6 tokenizer validation passes for every final chunk.

If those conditions pass, further Stage 5 polishing should be deferred unless retrieval evaluation reveals a measurable failure.

---

## Stage 5.7 — final group-scope and non-explanatory-figure hardening

Stage 5.7 closes two retrieval-quality defects found by inspecting the application-generated Stage 5.6 artifact against the source PDF.

### 1. Non-explanatory figure shells

A text-only figure can still be answer-poor even when it has a generic caption and a source citation. For example:

```text
An overview of the due diligence process is set out in Illustration 1 below.

Illustration 1:

For full FATF Guidance and Source for Illustration 1:
...
```

This text points to a visual but does not contain the process shown by the visual. Stage 5.7 therefore suppresses a figure shell when all of the following hold:

```text
figure visual text = empty
explicit explanation = empty
caption = absent or generic label only
intro = absent or short referential pointer only
remaining support = source/citation text only
```

Affected elements remain auditable as:

```text
action = context
reason = figure_non_explanatory_context_only
```

The rule is conservative. A figure is retained when the visual has extracted text, when Stage 4 linked explanatory prose, when the intro itself carries substantive information, or when the caption is not merely a generic label.

The quality report adds:

```text
non_explanatory_figure_chunk_count
```

Any leaked answer-poor figure shell is a hard deterministic quality issue.

### 2. Relation-aware local-group scope

Stage 5.6 correctly moved `group_header` text into retrieval context, but its scope could be too broad. The application artifact exposed this case:

```text
2.1 The RBA entails two assessments
  Business-based Risk Assessment (BbRA)
  Relationship-based Risk Assessment (RbRA)

2.2 The RBA must be tailored ...
2.3 ...
2.4 ...
2.5 ...
```

The RbRA label was incorrectly inherited by clauses 2.2–2.5. Stage 5.7 now classifies group scope from canonical `introduces` relations:

```text
section scope
  group_header → section_header
  may cross descendant sections within the same document root

clause scope
  group_header → clause/subclause
  may cover the following clause run until the next group/document-root boundary

local scope
  group_header → paragraph/list/visual-local content
  stays in the same canonical section and stops before the next independent numbered clause
```

This preserves macro labels such as Appendix-level guidance while preventing a local label inside one clause or diagram block from leaking into later clauses.

### 3. Group headers are context, not dependency-source content

When `attach_group_headers_as_context=true`, group headers are no longer absorbed into semantic dependency groups as source text. Their provenance is carried through `context_element_ids`, and their label through `context_text`.

This keeps:

```text
content_text = answer-bearing body
context_text = local heading / scope
```

instead of mixing headings into the answer body.

### 4. Generic packing respects context boundaries

Stage 5.7 treats retrieval context as a semantic packing boundary. Two adjacent units are not packed together when their `retrieval_context_text` or `context_element_ids` differ.

This prevents a chunk such as:

```text
Group: Business-based Risk Assessment (BbRA)
Group: Relationship-based Risk Assessment (RbRA)

[body from both groups]
```

and instead produces separate BbRA and RbRA retrieval units.

### Configuration

The default semantic-v2 configuration now includes:

```text
attach_group_headers_as_context = true
suppress_intro_only_figure_chunks = true
suppress_non_explanatory_figure_shells = true
```

### Reference replay against accepted Stage 4 `(9).json`

The deterministic Stage 5.7 reference replay produced:

```text
chunk_count                           272
estimated_token_count                36,663
min_chunk_tokens                     8
max_chunk_tokens                     550
average_chunk_tokens                 134.79
figure chunks                        7
navigation_chunk_count               0
orphan_child_count                   0
dangling_intro_count                 0
standalone_group_header_chunk_count  0
intro_only_figure_chunk_count        0
non_explanatory_figure_chunk_count   0
quality.status                       pass
```

The reference replay also confirms that the page-104 source-only illustration shell is no longer a retrieval chunk, while the actual textual due-diligence requirements remain in the preceding clause chunk.

The application-generated Stage 4.5-resolved artifact may have a different exact chunk count. Acceptance is based on structural invariants, not matching the reference count byte-for-byte.

### Regression coverage

Stage 5.7 adds/updates regression tests for:

1. source/citation-only figure shells with generic captions;
2. preservation of figures whose intro or explanation contains substantive information;
3. local group labels stopping before unrelated numbered clauses;
4. macro group labels crossing explicitly scoped descendant sections;
5. group headers staying in `context_element_ids` instead of dependency-source content;
6. generic packing refusing to merge units with different group contexts.

Full backend result:

```text
237 passed
```

Python compile check:

```text
compileall: OK
```

### Final Stage 5 freeze criteria

After regenerating Stage 5 from the application's current resolved artifact, freeze Stage 5 when:

```text
quality.status                         = pass
navigation_chunk_count                 = 0
orphan_child_count                     = 0
dangling_intro_count                   = 0
standalone_group_header_chunk_count    = 0 (except a legitimate terminal heading)
intro_only_figure_chunk_count          = 0
non_explanatory_figure_chunk_count     = 0
```

Then run the Stage 6 exact tokenizer compatibility check with the selected embedding model. Only model-token overflow should reopen chunk-size handling; other Stage 5 behavior should remain frozen unless retrieval evaluation demonstrates a measurable defect.


## Stage 5.8 — Resolved-section fallback and artifact traceability

A fresh application-generated Stage 5.7 artifact from the Stage 4.5 resolved structure exposed one final edge case that did not appear in the raw Stage 4 reference replay. Two Appendix form titles (`p107-e2` and `p108-e2`) remained standalone `group_header` chunks even though the following answer-bearing content lives in child sections of the same appendix. The resolved artifact preserved the parent/child section tree but did not preserve the redundant local `group_header -> section_header` `introduces` edge used by the raw Stage 4 structure.

Stage 5.8 adds a conservative hierarchy fallback:

```text
group_header in parent section
        ↓
no explicit introduces edge survives
        ↓
next answer-bearing unit is in an immediate/indirect descendant section
        ↓
treat group header as section-scoped retrieval context
```

The fallback does **not** use page numbers, appendix names, or benchmark text. `introduces` remains the strongest signal; the canonical section tree is used only when the local edge is absent. The existing document-root boundary still prevents scope from leaking into another appendix/root.

This closes the fresh artifact issue:

```text
standalone_group_header_chunk_count: 2 -> 0
```

A regression test reproduces the resolved-artifact condition by deliberately omitting the `introduces` edge while retaining the parent/child section hierarchy.

### Strategy-version traceability

The API strategy name remains `semantic_v2` for compatibility, but the emitted artifact `strategy_version` is now:

```text
semantic-v2.1
```

This makes regenerated artifacts distinguishable from earlier semantic-v2 outputs after the retrieval-preparation repairs.

### Verification

Full backend regression result:

```text
238 passed
```

The accepted raw Stage 4 `(9).json` reference replay remains clean:

```text
strategy_version                       semantic-v2.1
chunk_count                            272
max_chunk_tokens                       550 (regex estimate)
navigation_chunk_count                 0
orphan_child_count                     0
dangling_intro_count                   0
standalone_group_header_chunk_count    0
intro_only_figure_chunk_count          0
non_explanatory_figure_chunk_count     0
quality.status                         pass
```

The next acceptance step is model-specific: run the exact `BAAI/bge-m3` tokenizer compatibility check before embedding. Stage 5's `regex_estimate_v1` remains only a deterministic estimate; Stage 6 always asks the selected embedding model for its real tokenizer count and `max_seq_length` instead of assuming a hard-coded limit.
