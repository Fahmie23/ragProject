# Stage 4.13 — Independent PDF/JSON Audit Repair

This repair pass addresses residual canonical-structure defects found by manually cross-checking the generated Stage 4 JSON against the 109-page source PDF.

## Fixed defect families

1. **Alphanumeric clause suffix parsing**
   - Preserves clause identifiers such as `11.6A`.
   - Repairs the conservative layout artifact `11.6 A  A ...` to `11.6A A ...`.
   - Does not consume the first prose letter in strings such as `3.1Unless ...` or `6 A.1 A ...`.

2. **Repeated document-title suppression**
   - Repeated cover titles near the top of early revision/history pages are demoted to `page_header`.
   - They no longer create persistent body `SectionRecord`s.

3. **Definition row serialization**
   - Two-column glossary rows are ordered semantically as `definition_term -> definition_text`.
   - Cross-page continuation-only definition text remains supported.

4. **Definition row-boundary spill repair**
   - Detects a right-column definition box that crosses into the next term row.
   - Moves the overflow definition-introducer text to the next definition entry.
   - Covers the observed UNSCR/VASP boundary contamination without hard-coding those terms.

5. **TOC secondary-table repair**
   - Once a page is proven to be TOC navigation, additional TOC-shaped tables containing a merged major outline label (`PART`, `CHAPTER`, `BOOK`, `DIVISION`) are repaired.
   - Arbitrary uppercase/group tables remain untouched.

6. **Embedded caption splitting**
   - Splits `Example N:` from the first table-header cell when merged by the layout engine.
   - Splits standalone `Illustration/Figure/Diagram/Chart N` lines from adjacent prose when a nearby figure confirms caption context.

## Regression coverage

Six new regression tests were added to `backend/tests/test_stage4_canonical.py` covering:

- clause suffix preservation and prose-initial safety;
- repeated-title suppression;
- definition row ordering;
- definition boundary spill repair;
- embedded Example/Illustration captions;
- secondary TOC major-heading repair while protecting unrelated group tables.

## Verification

Backend test suite after the repair:

```text
222 passed
```

No existing backend regression test was removed or weakened.

## Expected impact on the audited PDF

The new deterministic rules directly target the previously confirmed residual pages:

- page 2 — repeated title false section;
- page 4 — merged TOC PART rows;
- pages 9 and 13 — definition row ordering;
- page 15 — UNSCR/VASP definition boundary contamination;
- page 56 — `11.6A` clause-number parsing;
- page 74 — `Example 1:` table caption;
- pages 99 and 104 — embedded `Illustration 1` captions.

The rules are pattern/geometry based and do not contain page-number or term-specific exceptions.
