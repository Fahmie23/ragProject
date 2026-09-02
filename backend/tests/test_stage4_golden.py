from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.schemas import (
    AppendixRecord,
    CanonicalElement,
    CanonicalSourceTrace,
    ClauseRecord,
    DefinitionEntry,
    FigureRecord,
    LayoutEngineInfo,
    LogicalTable,
    SectionRecord,
    StructuralRelation,
    StructuredDocument,
    StructuredPage,
    StructureSummary,
)
from app.services.evaluation.stage4_golden import (
    evaluate_stage4_golden,
    load_golden_spec,
    validate_golden_spec,
)


def _element(element_id: str, page: int, text: str, semantic_type: str, **kwargs) -> CanonicalElement:
    return CanonicalElement(
        element_id=element_id,
        type=semantic_type,
        page_number=page,
        reading_order=kwargs.pop("reading_order", 0),
        document_order=kwargs.pop("document_order", 0),
        bbox=[10.0, 10.0, 200.0, 30.0],
        text=text,
        source=CanonicalSourceTrace(layout_box_index=0, layout_box_class="text"),
        **kwargs,
    )


def _structure() -> StructuredDocument:
    heading = _element("e-heading", 1, "1. TEST SECTION", "section_header", heading_level=1)
    clause = _element("e-clause", 1, "1.1 The system shall provide:", "clause", clause_number="1.1", clause_id="c1")
    group = _element("e-group", 1, "Supported devices", "group_header")
    item = _element("e-item", 1, "(a) Workstations;", "list_item")
    pages = [StructuredPage(page_number=1, width=600, height=800, elements=[heading, clause, group, item], body_text="")]
    sections = [
        SectionRecord(
            section_id="s1",
            title="1. TEST SECTION",
            level=1,
            page_number=1,
            element_id="e-heading",
            content_element_ids=["e-clause", "e-group", "e-item"],
        )
    ]
    return StructuredDocument(
        document_id="golden-test",
        source_filename="test.pdf",
        source_sha256="abc",
        source_extraction_schema_version="1.1",
        layout_engine=LayoutEngineInfo(name="test", version="1"),
        title="Test",
        title_source="test",
        summary=StructureSummary(
            page_count=1,
            element_count=4,
            body_text_char_count=0,
            section_count=1,
            definition_count=1,
            clause_count=1,
            appendix_count=1,
            logical_table_count=1,
            figure_count=1,
            relation_count=2,
            element_counts={"section_header": 1, "clause": 1, "group_header": 1, "list_item": 1},
        ),
        sections=sections,
        definitions=[
            DefinitionEntry(
                definition_id="d1",
                term="sample term",
                definition_text="means a sample value",
                start_page=1,
                end_page=1,
            )
        ],
        clauses=[ClauseRecord(clause_id="c1", number="1.1", kind="clause", element_id="e-clause", page_number=1, section_id="s1")],
        appendices=[AppendixRecord(appendix_id="appendix-a", label="APPENDIX A", label_element_id="e-heading", title="Test Appendix", start_page=1, end_page=1)],
        tables=[LogicalTable(logical_table_id="t1", fragment_element_ids=["e-item"], start_page=1, end_page=1, spans_multiple_pages=False, row_count=3, col_count=2)],
        figures=[FigureRecord(figure_id="f1", element_id="e-item", page_number=1)],
        relationships=[
            StructuralRelation(relation_id="r1", type="introduces", source_element_id="e-clause", target_element_id="e-group", evidence="test"),
            StructuralRelation(relation_id="r2", type="introduces", source_element_id="e-group", target_element_id="e-item", evidence="test"),
        ],
        pages=pages,
        body_text="",
        structured_at=datetime.now(timezone.utc),
    )


def test_golden_evaluator_checks_elements_relations_records_and_negative_edges():
    spec = {
        "spec_version": "test",
        "benchmark_id": "test-benchmark",
        "source": {"sha256": "abc", "page_count": 1},
        "element_assertions": [
            {"id": "heading", "page": 1, "match": {"exact": "1. TEST SECTION"}, "expect": {"type": "section_header", "section_record": True}},
            {"id": "clause", "page": 1, "match": {"starts_with": "1.1 The system"}, "expect": {"type": "clause", "clause_number": "1.1"}},
            {"id": "group", "page": 1, "match": {"exact": "Supported devices"}, "expect": {"type": "group_header", "section_record": False}},
            {"id": "item", "page": 1, "match": {"exact": "(a) Workstations;"}, "expect": {"type": "list_item"}},
        ],
        "relation_assertions": [
            {"id": "r-group", "source": "clause", "type": "introduces", "target": "group"},
            {"id": "r-item", "source": "group", "type": "introduces", "target": "item"},
            {"id": "r-no-continue", "source": "clause", "type": "continues", "target": "item", "present": False},
        ],
        "definition_assertions": [
            {"id": "d", "term": "sample term", "expect": {"start_page": 1, "end_page": 1, "spans_multiple_pages": False, "definition_contains": "sample value"}}
        ],
        "appendix_assertions": [
            {"id": "a", "label": "APPENDIX A", "expect": {"start_page": 1, "end_page": 1, "title_contains": "Test"}}
        ],
        "logical_table_assertions": [
            {"id": "t", "start_page": 1, "end_page": 1, "min_row_count": 3, "min_col_count": 2}
        ],
        "page_assertions": [{"id": "p", "page": 1, "min_type_counts": {"list_item": 1}}],
        "figure_assertions": [{"id": "f", "page": 1, "min_count": 1}],
    }
    report = evaluate_stage4_golden(_structure(), spec)
    assert report.source_match is True
    assert report.passed is True
    assert report.required_score == 1.0
    assert all(check.passed for check in report.checks)


def test_golden_evaluator_reports_semantic_regression_without_hiding_it():
    structure = _structure()
    structure.pages[0].elements[-1].type = "subclause"
    spec = {
        "spec_version": "test",
        "benchmark_id": "test-benchmark",
        "source": {"sha256": "abc", "page_count": 1},
        "element_assertions": [
            {"id": "item", "page": 1, "match": {"exact": "(a) Workstations;"}, "expect": {"type": "list_item"}}
        ],
    }
    report = evaluate_stage4_golden(structure, spec)
    assert report.passed is False
    assert report.required_passed == 0
    assert "expected 'list_item'" in report.checks[0].message


def test_primary_golden_spec_is_internally_consistent():
    path = Path(__file__).resolve().parents[1] / "evaluation" / "golden" / "sc_aml_cft_stage4_v1.json"
    spec = load_golden_spec(path)
    assert validate_golden_spec(spec) == []
    assert spec["source"]["page_count"] == 109
    assert len(spec["element_assertions"]) >= 40
    assert len(spec["coverage_matrix"]) >= 10


def test_golden_anchor_matching_ignores_missing_space_after_structural_markers():
    structure = _structure()
    structure.pages[0].elements[-1].text = "(a)Workstations;"
    footnote = _element("e-foot", 1, "1Regulation 3 of Strategic Trade", "footnote", document_order=5)
    structure.pages[0].elements.append(footnote)
    spec = {
        "spec_version": "test",
        "benchmark_id": "marker-spacing",
        "source": {"sha256": "abc", "page_count": 1},
        "element_assertions": [
            {"id": "item", "page": 1, "match": {"exact": "(a) Workstations;"}, "expect": {"type": "list_item"}},
            {"id": "foot", "page": 1, "match": {"starts_with": "1 Regulation 3"}, "expect": {"type": "footnote"}},
        ],
    }
    report = evaluate_stage4_golden(structure, spec)
    assert report.required_passed == 2
    assert report.required_total == 2


def test_primary_golden_appendix_a_uses_pdf_page_boundary_not_printed_page_number():
    path = Path(__file__).resolve().parents[1] / "evaluation" / "golden" / "sc_aml_cft_stage4_v1.json"
    spec = load_golden_spec(path)
    appendix_a = next(item for item in spec["appendix_assertions"] if item["label"] == "APPENDIX A")
    assert appendix_a["expect"]["start_page"] == 68
    assert appendix_a["expect"]["end_page"] == 78


def test_golden_evaluator_supports_zero_match_assertions_for_merged_fragments():
    structure = _structure()
    spec = {
        "spec_version": "test",
        "benchmark_id": "zero-match",
        "source": {"sha256": "abc", "page_count": 1},
        "element_assertions": [
            {
                "id": "removed-fragment",
                "page": 1,
                "match": {"exact": "standalone continuation that should have been merged"},
                "expect_count": 0,
                "expect": {},
            }
        ],
    }
    report = evaluate_stage4_golden(structure, spec)
    assert report.required_passed == 1
    assert report.required_total == 1


def test_golden_evaluator_supports_explicit_section_and_clause_hierarchy_assertions():
    structure = _structure()
    subheading = _element(
        "e-subheading", 1, "Customer identification", "section_header",
        section_id="s2", reading_order=2, document_order=2,
    )
    clause = next(item for item in structure.pages[0].elements if item.element_id == "e-clause")
    clause.section_id = "s2"
    clause.document_order = 3
    clause.reading_order = 3
    child = _element(
        "e-subclause", 1, "(a) Identify the customer;", "subclause",
        section_id="s2", clause_id="c2", parent_clause_id="c1",
        subclause_marker="(a)", reading_order=4, document_order=4,
    )
    structure.pages[0].elements.insert(2, subheading)
    structure.pages[0].elements.append(child)
    structure.sections.append(
        SectionRecord(
            section_id="s2", title="Customer identification", level=2,
            page_number=1, element_id="e-subheading", parent_section_id="s1",
            content_element_ids=["e-clause", "e-subclause"],
        )
    )
    structure.clauses[0].section_id = "s2"
    structure.clauses.append(
        ClauseRecord(
            clause_id="c2", number="(a)", kind="subclause",
            element_id="e-subclause", page_number=1, section_id="s2",
            parent_clause_id="c1",
        )
    )
    spec = {
        "spec_version": "test",
        "benchmark_id": "hierarchy",
        "source": {"sha256": "abc", "page_count": 1},
        "element_assertions": [
            {"id": "root", "page": 1, "match": {"exact": "1. TEST SECTION"}, "expect": {"type": "section_header", "section_record": True}},
            {"id": "sub", "page": 1, "match": {"exact": "Customer identification"}, "expect": {"type": "section_header", "section_record": True}},
            {"id": "clause", "page": 1, "match": {"starts_with": "1.1 The system"}, "expect": {"type": "clause"}},
            {"id": "child", "page": 1, "match": {"starts_with": "(a) Identify"}, "expect": {"type": "subclause"}},
        ],
        "hierarchy_assertions": [
            {"id": "h-parent", "kind": "section_parent", "child": "sub", "parent": "root"},
            {"id": "h-member", "kind": "section_membership", "element": "clause", "section": "root", "allow_descendant": True},
            {"id": "h-clause", "kind": "clause_parent", "child": "child", "parent": "clause"},
        ],
    }
    assert validate_golden_spec(spec) == []
    report = evaluate_stage4_golden(structure, spec)
    assert report.required_passed == report.required_total
    assert {check.category for check in report.checks if check.check_id.startswith("h-")} == {"hierarchy"}


def test_golden_evaluator_can_assert_canonical_section_level_separately_from_element_heading_evidence():
    structure = _structure()
    heading = structure.pages[0].elements[0]
    heading.heading_level = 5
    heading.heading_level_source = "pdf_toc"
    structure.sections[0].level = 2
    spec = {
        "spec_version": "test",
        "benchmark_id": "section-level",
        "source": {"sha256": "abc", "page_count": 1},
        "element_assertions": [
            {
                "id": "root",
                "page": 1,
                "match": {"exact": "1. TEST SECTION"},
                "expect": {"type": "section_header", "section_record": True, "section_level": 2},
            }
        ],
    }
    report = evaluate_stage4_golden(structure, spec)
    assert report.required_passed == 1
    assert report.required_total == 1
