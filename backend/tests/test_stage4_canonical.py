from datetime import datetime, timezone

from app.schemas import (
    DocumentClassification,
    DocumentExtraction,
    DocumentRecord,
    ExtractionSummary,
    CanonicalElement,
    CanonicalSourceTrace,
    SectionRecord,
    ExtractorInfo,
    PageExtraction,
    TableExtraction,
    TextBlock,
    TextLine,
    TextSpan,
)
from app.services.canonical import build_canonical_document
from app.services.semantic.validator import validate_semantic_structure


def _text_block(block_id: str, number: int, bbox: list[float], text: str, size: float) -> TextBlock:
    span = TextSpan(text=text, bbox=bbox, font="TestFont", size=size)
    line = TextLine(bbox=bbox, text=text, spans=[span])
    return TextBlock(block_id=block_id, number=number, bbox=bbox, text=text, lines=[line])


def _fixture():
    now = datetime.now(timezone.utc)
    record = DocumentRecord(
        document_id="doc-1",
        original_filename="sample.pdf",
        stored_filename="doc-1.pdf",
        extension=".pdf",
        detected_mime_type="application/pdf",
        size_bytes=100,
        sha256="abc123",
        validation_status="valid",
        classification=DocumentClassification(
            document_family="pdf",
            pdf_type="digital",
            page_count=1,
            text_pages=1,
            image_pages=0,
            has_text_layer=True,
            has_images=False,
            encrypted=False,
        ),
        ingested_at=now,
        extraction_status="completed",
        extracted_at=now,
    )

    extraction = DocumentExtraction(
        document_id="doc-1",
        source_filename="sample.pdf",
        source_sha256="abc123",
        source_pdf_type="digital",
        extraction_mode="text_layer",
        extractor=ExtractorInfo(name="PyMuPDF", version="test"),
        summary=ExtractionSummary(
            page_count=1,
            text_char_count=80,
            text_block_count=5,
            image_block_count=0,
            table_count=1,
        ),
        pages=[
            PageExtraction(
                page_number=1,
                width=600,
                height=800,
                rotation=0,
                text="Sample Report\n1 Introduction\nBody paragraph\nConfidential",
                text_char_count=60,
                blocks=[
                    _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
                    _text_block("p1-b1", 1, [50, 100, 300, 125], "1 Introduction", 16),
                    _text_block("p1-b2", 2, [50, 140, 500, 180], "Body paragraph", 11),
                    _text_block("p1-b3", 3, [50, 220, 500, 300], "A B C D", 10),
                    _text_block("p1-b4", 4, [50, 760, 300, 780], "Confidential", 8),
                ],
                tables=[
                    TableExtraction(
                        table_id="p1-t1",
                        bbox=[50, 220, 500, 300],
                        row_count=2,
                        col_count=2,
                        cells=[["A", "B"], ["C", "D"]],
                    )
                ],
                warnings=[],
            )
        ],
        warnings=[],
        extracted_at=now,
    )

    layout = {
        "engine": {
            "name": "PyMuPDF4LLM Layout",
            "version": "1.28.0",
            "settings": {"use_layout": True, "use_ocr": False},
        },
        "result": {
            "filename": "sample.pdf",
            "page_count": 1,
            "toc": [[1, "1 Introduction", 1]],
            "pages": [
                {
                    "page_number": 1,
                    "width": 600,
                    "height": 800,
                    "boxes": [
                        {
                            "x0": 50, "y0": 40, "x1": 300, "y1": 70,
                            "boxclass": "title",
                            "textlines": [{"spans": [{"text": "Sample Report"}]}],
                        },
                        {
                            "x0": 50, "y0": 100, "x1": 300, "y1": 125,
                            "boxclass": "section-header",
                            "textlines": [{"spans": [{"text": "1 Introduction"}]}],
                        },
                        {
                            "x0": 50, "y0": 140, "x1": 500, "y1": 180,
                            "boxclass": "text",
                            "textlines": [{"spans": [{"text": "Body paragraph"}]}],
                        },
                        {
                            "x0": 50, "y0": 220, "x1": 500, "y1": 300,
                            "boxclass": "table",
                            "table": {
                                "row_count": 2,
                                "col_count": 2,
                                "extract": [["A", "B"], ["C", "D"]],
                                "markdown": "|A|B|\n|---|---|\n|C|D|\n",
                            },
                            "textlines": None,
                        },
                        {
                            "x0": 50, "y0": 760, "x1": 300, "y1": 780,
                            "boxclass": "page-footer",
                            "textlines": [{"spans": [{"text": "Confidential"}]}],
                        },
                    ],
                }
            ],
        },
    }
    return record, extraction, layout


def test_builds_canonical_structure_without_footer_pollution():
    record, extraction, layout = _fixture()
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)

    assert result.title == "Sample Report"
    assert result.title_source == "layout_title"
    assert result.summary.page_count == 1
    assert result.summary.section_count == 1
    assert result.summary.element_counts["page_footer"] == 1
    assert result.sections[0].title == "1 Introduction"
    assert result.sections[0].level == 2
    assert result.sections[0].level_source == "pdf_toc"

    page = result.pages[0]
    types = [element.type for element in page.elements]
    assert types == ["title", "section_header", "paragraph", "table", "page_footer"]
    assert "Body paragraph" in page.body_text
    assert "|A|B|" in page.body_text
    assert "Confidential" not in page.body_text
    assert "Confidential" not in result.body_text

    paragraph = page.elements[2]
    assert paragraph.section_id == result.sections[0].section_id
    assert paragraph.source.stage3_block_ids == ["p1-b2"]

    table = page.elements[3]
    assert table.table is not None
    assert table.table.cells == [["A", "B"], ["C", "D"]]
    assert table.source.stage3_table_ids == ["p1-t1"]


def test_numbering_and_font_rank_are_explicit_fallbacks():
    record, extraction, layout = _fixture()
    layout["result"]["toc"] = []
    boxes = layout["result"]["pages"][0]["boxes"]
    boxes[1]["textlines"] = [{"spans": [{"text": "2.3 Methods"}]}]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    header = next(element for element in result.pages[0].elements if element.type == "section_header")
    assert header.heading_level == 3
    assert header.heading_level_source == "numbering"



def test_faq_role_refinement_and_question_answer_grouping():
    record, extraction, layout = _fixture()
    raw_page = extraction.pages[0]
    raw_page.text = (
        "FREQUENTLY ASKED QUESTIONS\nLICENSING HANDBOOK\n"
        "(Issued: 14 April 2023; Revised: 1 October 2024)\n"
        "1. Why did the SC revise the Licensing Handbook?\nAnswer one.\n"
        "2. Do I meet the eligibility requirements?\nAnswer two."
    )
    raw_page.blocks = [
        _text_block("p1-b0", 0, [210, 78, 390, 98], "FREQUENTLY ASKED QUESTIONS", 14),
        _text_block("p1-b1", 1, [230, 110, 370, 130], "LICENSING HANDBOOK", 14),
        _text_block("p1-b2", 2, [165, 145, 435, 166], "(Issued: 14 April 2023; Revised: 1 October 2024)", 11),
        _text_block("p1-b3", 3, [70, 205, 525, 235], "1. Why did the SC revise the Licensing Handbook?", 11),
        _text_block("p1-b4", 4, [105, 245, 525, 285], "Answer one.", 10),
        _text_block("p1-b5", 5, [70, 320, 525, 350], "2. Do I meet the eligibility requirements?", 11),
        _text_block("p1-b6", 6, [105, 360, 525, 400], "Answer two.", 10),
        _text_block("p1-b7", 7, [290, 760, 310, 778], "1", 8),
    ]
    raw_page.tables = []
    extraction.summary.text_block_count = len(raw_page.blocks)
    extraction.summary.table_count = 0

    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {
            "x0": 210, "y0": 78, "x1": 390, "y1": 98,
            "boxclass": "section-header",
            "textlines": [{"spans": [{"text": "FREQUENTLY ASKED QUESTIONS"}]}],
        },
        {
            "x0": 230, "y0": 110, "x1": 370, "y1": 130,
            "boxclass": "section-header",
            "textlines": [{"spans": [{"text": "LICENSING HANDBOOK"}]}],
        },
        {
            "x0": 165, "y0": 145, "x1": 435, "y1": 166,
            "boxclass": "section-header",
            "textlines": [{"spans": [{"text": "(Issued: 14 April 2023; Revised: 1 October 2024)"}]}],
        },
        {
            "x0": 70, "y0": 205, "x1": 525, "y1": 235,
            "boxclass": "section-header",
            "textlines": [{"spans": [{"text": "1. Why did the SC revise the Licensing Handbook?"}]}],
        },
        {
            "x0": 105, "y0": 245, "x1": 525, "y1": 285,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "Answer one."}]}],
        },
        {
            "x0": 70, "y0": 320, "x1": 525, "y1": 350,
            "boxclass": "section-header",
            "textlines": [{"spans": [{"text": "2. Do I meet the eligibility requirements?"}]}],
        },
        {
            "x0": 105, "y0": 360, "x1": 525, "y1": 400,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "Answer two."}]}],
        },
        {
            "x0": 290, "y0": 760, "x1": 310, "y1": 778,
            "boxclass": "page-footer",
            "textlines": [{"spans": [{"text": "1"}]}],
        },
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    page = result.pages[0]

    assert result.title == "FREQUENTLY ASKED QUESTIONS"
    assert result.title_source == "promoted_top_heading"
    assert result.subtitle == "LICENSING HANDBOOK"
    assert result.subtitle_source == "title_cluster_subtitle"
    assert result.outline_root_element_id == "p1-e1"
    assert result.metadata_element_ids == ["p1-e3"]

    assert [element.type for element in page.elements] == [
        "title",
        "subtitle",
        "document_metadata",
        "section_header",
        "paragraph",
        "section_header",
        "paragraph",
        "page_footer",
    ]

    assert len(result.sections) == 2
    assert [section.level for section in result.sections] == [2, 2]
    assert [section.kind for section in result.sections] == ["question", "question"]
    assert result.sections[0].parent_section_id is None
    assert result.sections[1].parent_section_id is None

    first_question = page.elements[3]
    first_answer = page.elements[4]
    second_question = page.elements[5]
    second_answer = page.elements[6]

    assert first_question.heading_level == 2
    assert first_question.heading_level_source == "numbering"
    assert first_answer.section_id == result.sections[0].section_id
    assert second_answer.section_id == result.sections[1].section_id
    assert result.sections[0].content_element_ids == [first_answer.element_id]
    assert result.sections[1].content_element_ids == [second_answer.element_id]

    assert "Issued: 14 April 2023" not in result.body_text
    assert "Answer one." in result.body_text
    assert "Answer two." in result.body_text
    assert "\n1\n" not in result.body_text


def test_definition_list_reconstruction_repairs_terms_clause_and_false_footer():
    record, extraction, layout = _fixture()
    raw_page = extraction.pages[0]
    raw_page.text = (
        "Sample Report\n3.DEFINITIONS\n"
        "3.1Unless otherwise defined, all words used in these Guidelines shall have the following meaning:\n"
        "AML/CFT/CPF\nmeans Anti-Money Laundering / Counter Financing of Terrorism / Counter Proliferation Financing.\n"
        "beneficial owner\nin the context of legal person, means any natural person who ultimately owns or controls a customer.\n"
        "Reference to ultimately owns or controls refers to indirect control.\n"
        "in the context of legal arrangements, beneficial owner includes trustees and beneficiaries.\n"
        "Reference to ultimate effective control over trusts includes indirect control.\n"
        "beneficiary\nthe meaning of the term beneficiary depends on"
    )
    raw_page.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 83, 194, 93], "3.DEFINITIONS", 12),
        _text_block("p1-b2", 2, [72, 119, 551, 146], "3.1Unless otherwise defined, all words used in these Guidelines shall have the following meaning:", 11),
        _text_block("p1-b3", 3, [112, 165, 548, 207], "AML/CFT/CPF means Anti-Money Laundering / Counter Financing of Terrorism / Counter Proliferation Financing.", 11),
        _text_block("p1-b4", 4, [112, 226, 548, 314], "beneficial owner in the context of legal person, means any natural person who ultimately owns or controls a customer.", 11),
        _text_block("p1-b5", 5, [311, 335, 548, 406], "Reference to ultimately owns or controls refers to indirect control.", 11),
        _text_block("p1-b6", 6, [311, 427, 548, 636], "in the context of legal arrangements, beneficial owner includes trustees and beneficiaries.", 11),
        _text_block("p1-b7", 7, [112, 656, 548, 774], "Reference to ultimate effective control over trusts includes indirect control. beneficiary the meaning of the term beneficiary depends on", 11),
        _text_block("p1-b8", 8, [312, 784, 322, 793], "8", 8),
    ]
    raw_page.tables = []
    extraction.summary.text_block_count = len(raw_page.blocks)
    extraction.summary.table_count = 0

    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {
            "x0": 50, "y0": 40, "x1": 300, "y1": 70,
            "boxclass": "title",
            "textlines": [{"spans": [{"text": "Sample Report"}]}],
        },
        {
            "x0": 72, "y0": 83, "x1": 194, "y1": 93,
            "boxclass": "section-header",
            "textlines": [{"spans": [{"text": "3.DEFINITIONS"}]}],
        },
        {
            "x0": 72, "y0": 119, "x1": 551, "y1": 146,
            "boxclass": "list-item",
            "textlines": [{"spans": [{"text": "3.1Unless otherwise defined, all words used in these Guidelines shall have the following meaning:"}]}],
        },
        {
            "x0": 112, "y0": 165, "x1": 182, "y1": 176,
            "boxclass": "section-header",
            "textlines": [{"spans": [{"text": "AML/CFT/CPF"}]}],
        },
        {
            "x0": 311, "y0": 165, "x1": 548, "y1": 207,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "means Anti-Money Laundering / Counter Financing of Terrorism / Counter Proliferation Financing."}]}],
        },
        {
            "x0": 112, "y0": 226, "x1": 160, "y1": 250,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "beneficial\nowner"}]}],
        },
        {
            "x0": 311, "y0": 226, "x1": 548, "y1": 314,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "in the context of legal person, means any natural person who ultimately owns or controls a customer."}]}],
        },
        {
            "x0": 311, "y0": 335, "x1": 548, "y1": 406,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "Reference to ultimately owns or controls refers to indirect control."}]}],
        },
        {
            "x0": 311, "y0": 427, "x1": 548, "y1": 636,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "in the context of legal arrangements, beneficial owner includes trustees and beneficiaries."}]}],
        },
        {
            "x0": 311, "y0": 656, "x1": 548, "y1": 726,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "Reference to ultimate effective control over trusts includes indirect control."}]}],
        },
        {
            "x0": 112, "y0": 763, "x1": 169, "y1": 774,
            "boxclass": "page-footer",
            "textlines": [{"spans": [{"text": "beneficiary"}]}],
        },
        {
            "x0": 311, "y0": 763, "x1": 548, "y1": 774,
            "boxclass": "text",
            "textlines": [{"spans": [{"text": "the meaning of the term beneficiary depends on"}]}],
        },
        {
            "x0": 312, "y0": 784, "x1": 322, "y1": 793,
            "boxclass": "page-footer",
            "textlines": [{"spans": [{"text": "8"}]}],
        },
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    page = result.pages[0]

    assert result.schema_version == "1.8"
    assert len(result.sections) == 1
    assert result.sections[0].title == "3. DEFINITIONS"
    assert result.sections[0].level == 2
    assert result.sections[0].level_source == "numbering"

    clause = next(element for element in page.elements if element.type == "clause")
    assert clause.clause_number == "3.1"
    assert clause.text.startswith("3.1 Unless otherwise defined")
    assert clause.section_id == result.sections[0].section_id

    assert result.summary.definition_count == 3
    assert [entry.term for entry in result.definitions] == ["AML/CFT/CPF", "beneficial owner", "beneficiary"]

    aml, beneficial_owner, beneficiary = result.definitions
    assert len(aml.definition_element_ids) == 1
    assert len(beneficial_owner.definition_element_ids) == 4
    assert beneficiary.continues_to_next_page is True

    beneficiary_term = next(element for element in page.elements if element.element_id == beneficiary.term_element_id)
    assert beneficiary_term.type == "definition_term"
    assert beneficiary_term.source.layout_box_class == "page-footer"
    assert beneficiary_term.role_source == "definition_list_geometry"

    assert "AML/CFT/CPF" not in [section.title for section in result.sections]
    assert result.summary.element_counts["page_footer"] == 1
    assert "beneficiary" in page.body_text
    assert "\n\n8\n" not in page.body_text


def test_definition_entry_can_continue_across_page_break():
    record, extraction, layout = _fixture()
    record.classification.page_count = 2
    record.classification.text_pages = 2

    page1 = extraction.pages[0]
    page1.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 102], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 700, 548, 780], "beneficiary the meaning of the term beneficiary depends on", 11),
        _text_block("p1-b3", 3, [312, 784, 322, 793], "1", 8),
    ]
    page1.tables = []
    page2 = PageExtraction(
        page_number=2,
        width=600,
        height=800,
        rotation=0,
        text="the context in which the term is used. customer means a person who maintains an account.",
        text_char_count=90,
        blocks=[
            _text_block("p2-b0", 0, [311, 45, 548, 105], "the context in which the term is used.", 11),
            _text_block("p2-b1", 1, [112, 140, 548, 190], "customer means a person who maintains an account.", 11),
            _text_block("p2-b2", 2, [312, 784, 322, 793], "2", 8),
        ],
        tables=[],
        warnings=[],
    )
    extraction.pages = [page1, page2]
    extraction.summary.page_count = 2
    extraction.summary.text_block_count = 7
    extraction.summary.table_count = 0

    layout["result"]["toc"] = []
    layout["result"]["page_count"] = 2
    layout["result"]["pages"] = [
        {
            "page_number": 1,
            "width": 600,
            "height": 800,
            "boxes": [
                {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "title", "textlines": [{"spans": [{"text": "Sample Report"}]}]},
                {"x0": 72, "y0": 90, "x1": 194, "y1": 102, "boxclass": "section-header", "textlines": [{"spans": [{"text": "3. DEFINITIONS"}]}]},
                {"x0": 112, "y0": 700, "x1": 169, "y1": 714, "boxclass": "page-footer", "textlines": [{"spans": [{"text": "beneficiary"}]}]},
                {"x0": 311, "y0": 700, "x1": 548, "y1": 780, "boxclass": "text", "textlines": [{"spans": [{"text": "the meaning of the term beneficiary depends on"}]}]},
                {"x0": 312, "y0": 784, "x1": 322, "y1": 793, "boxclass": "page-footer", "textlines": [{"spans": [{"text": "1"}]}]},
            ],
        },
        {
            "page_number": 2,
            "width": 600,
            "height": 800,
            "boxes": [
                {"x0": 311, "y0": 45, "x1": 548, "y1": 105, "boxclass": "text", "textlines": [{"spans": [{"text": "the context in which the term is used."}]}]},
                {"x0": 112, "y0": 140, "x1": 165, "y1": 155, "boxclass": "text", "textlines": [{"spans": [{"text": "customer"}]}]},
                {"x0": 311, "y0": 140, "x1": 548, "y1": 190, "boxclass": "text", "textlines": [{"spans": [{"text": "means a person who maintains an account."}]}]},
                {"x0": 312, "y0": 784, "x1": 322, "y1": 793, "boxclass": "page-footer", "textlines": [{"spans": [{"text": "2"}]}]},
            ],
        },
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)

    assert [entry.term for entry in result.definitions] == ["beneficiary", "customer"]
    beneficiary = result.definitions[0]
    assert beneficiary.start_page == 1
    assert beneficiary.end_page == 2
    assert beneficiary.spans_multiple_pages is True
    assert beneficiary.continues_to_next_page is False
    assert len(beneficiary.definition_element_ids) == 2

    continuation = result.pages[1].elements[0]
    assert continuation.type == "definition_text"
    assert continuation.definition_entry_id == beneficiary.definition_id
    assert continuation.role_source == "cross_page_definition_reconciliation"
    assert any(
        relation.type == "continues"
        and relation.source_element_id == beneficiary.definition_element_ids[0]
        and relation.target_element_id == continuation.element_id
        for relation in result.relationships
    )


def _make_page(page_number: int, blocks, tables=None, width=600, height=800):
    return PageExtraction(
        page_number=page_number,
        width=width,
        height=height,
        rotation=0,
        text="\n".join(block.text for block in blocks if getattr(block, "type", None) == "text"),
        text_char_count=sum(len(block.text) for block in blocks if getattr(block, "type", None) == "text"),
        blocks=blocks,
        tables=tables or [],
        warnings=[],
    )


def _layout_table(x0, y0, x1, y1, cells):
    return {
        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "boxclass": "table",
        "table": {
            "row_count": len(cells),
            "col_count": max(len(row) for row in cells),
            "extract": cells,
            "markdown": "\n".join("|" + "|".join(str(cell or "") for cell in row) + "|" for row in cells),
        },
        "textlines": None,
    }


def _two_page_base():
    record, extraction, layout = _fixture()
    record.classification.page_count = 2
    extraction.summary.page_count = 2
    layout["result"]["page_count"] = 2
    return record, extraction, layout


def test_cross_page_tables_are_one_logical_table_with_fragments():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [50, 100, 320, 125], "APPENDIX D", 14),
    ]
    p2_blocks = [_text_block("p2-b0", 0, [300, 770, 320, 790], "86", 8)]
    p1_cells = [["AMLA Provision", "Section 66C", "Section 66B"], ["Listing", "UNSCR List", "Domestic List"]]
    p2_cells = [["Subsidiary Legislation", "66C continuation", "66B continuation"], ["", "Other legislation", "Other legislation"]]
    p1_table = TableExtraction(table_id="p1-t1", bbox=[90, 430, 555, 790], row_count=2, col_count=3, cells=p1_cells)
    p2_table = TableExtraction(table_id="p2-t1", bbox=[92, 45, 557, 520], row_count=2, col_count=3, cells=p2_cells)
    extraction.pages = [
        _make_page(1, p1_blocks, [p1_table]),
        _make_page(2, p2_blocks, [p2_table]),
    ]
    extraction.summary.text_block_count = 3
    extraction.summary.table_count = 2
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {
            "page_number": 1, "width": 600, "height": 800,
            "boxes": [
                {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
                {"x0":50,"y0":100,"x1":320,"y1":125,"boxclass":"section-header","textlines":[{"spans":[{"text":"APPENDIX D"}]}]},
                _layout_table(90, 430, 555, 790, p1_cells),
            ],
        },
        {
            "page_number": 2, "width": 600, "height": 800,
            "boxes": [
                _layout_table(92, 45, 557, 520, p2_cells),
                {"x0":300,"y0":770,"x1":320,"y1":790,"boxclass":"page-footer","textlines":[{"spans":[{"text":"86"}]}]},
            ],
        },
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert result.schema_version == "1.8"
    assert len(result.tables) == 1
    table = result.tables[0]
    assert table.spans_multiple_pages is True
    assert table.start_page == 1 and table.end_page == 2
    assert table.fragment_element_ids == ["p1-e3", "p2-e1"]
    assert table.merge_source == "cross_page_geometry"
    assert table.row_count == 4
    assert result.pages[0].elements[2].logical_table_id == table.logical_table_id
    assert result.pages[1].elements[0].logical_table_id == table.logical_table_id
    assert any(r.type == "continues" and r.source_element_id == "p1-e3" and r.target_element_id == "p2-e1" for r in result.relationships)


def test_definition_normalization_accepts_table_rows_and_cross_page_text_continuation():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 83, 194, 93], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 700, 175, 715], "beneficiary", 11),
        _text_block("p1-b3", 3, [310, 700, 550, 775], "the meaning of the term beneficiary depends on", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [310, 35, 550, 65], "the context.", 11),
    ]
    table_cells = [
        ["customer due-diligence (CDD)", "means any measures undertaken pursuant to section 16 of AMLA."],
        ["digital asset", "refers collectively to a digital currency and digital token."],
        ["politically exposed person (PEP)", "means— (a) foreign PEP; (b) domestic PEP; (c) international organisation PEP."],
    ]
    p2_table = TableExtraction(table_id="p2-t1", bbox=[110, 110, 555, 620], row_count=3, col_count=2, cells=table_cells)
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks, [p2_table])]
    extraction.summary.text_block_count = 5
    extraction.summary.table_count = 1
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {
            "page_number":1,"width":600,"height":800,
            "boxes":[
                {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
                {"x0":72,"y0":83,"x1":194,"y1":93,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
                {"x0":112,"y0":700,"x1":175,"y1":715,"boxclass":"page-footer","textlines":[{"spans":[{"text":"beneficiary"}]}]},
                {"x0":310,"y0":700,"x1":550,"y1":775,"boxclass":"text","textlines":[{"spans":[{"text":"the meaning of the term beneficiary depends on"}]}]},
            ],
        },
        {
            "page_number":2,"width":600,"height":800,
            "boxes":[
                {"x0":310,"y0":35,"x1":550,"y1":65,"boxclass":"text","textlines":[{"spans":[{"text":"the context."}]}]},
                _layout_table(110,110,555,620,table_cells),
            ],
        },
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    beneficiary = next(entry for entry in result.definitions if entry.term == "beneficiary")
    assert beneficiary.spans_multiple_pages is True
    assert beneficiary.end_page == 2
    assert "the context." in beneficiary.definition_text
    digital = next(entry for entry in result.definitions if entry.term == "digital asset")
    assert digital.source_kind == "table_rows"
    assert digital.source_table_element_id == "p2-e2"
    pep = next(entry for entry in result.definitions if entry.term == "politically exposed person (PEP)")
    assert [item.marker for item in pep.items] == ["(a)", "(b)", "(c)"]


def test_clause_and_subclause_parent_child_relationships():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,100,500,140],"2.5 The outcome of the BbRA and RbRA complement each other.",11),
        _text_block("p1-b2",2,[105,155,500,195],"(a) a reporting institution must determine reasonable risk factors;",11),
        _text_block("p1-b3",3,[105,205,500,245],"(b) data from the RbRA may also be useful in updating parameters.",11),
    ]
    raw.tables=[]
    extraction.summary.text_block_count=4
    extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":500,"y1":140,"boxclass":"list-item","textlines":[{"spans":[{"text":"2.5 The outcome of the BbRA and RbRA complement each other."}]}]},
        {"x0":105,"y0":155,"x1":500,"y1":195,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) a reporting institution must determine reasonable risk factors;"}]}]},
        {"x0":105,"y0":205,"x1":500,"y1":245,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) data from the RbRA may also be useful in updating parameters."}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    assert [c.kind for c in result.clauses] == ["clause","subclause","subclause"]
    parent=result.clauses[0]
    assert result.clauses[1].parent_clause_id == parent.clause_id
    assert result.clauses[2].parent_clause_id == parent.clause_id
    assert sum(1 for r in result.relationships if r.type=="parent_of") == 2


def test_appendix_figure_relations_and_footnote_repair():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,30,300,55],"Sample Report",22),
        _text_block("p1-b1",1,[430,80,540,98],"APPENDIX C",12),
        _text_block("p1-b2",2,[70,115,500,140],"Submission of Suspicious Transaction Report (STR)",15),
        _text_block("p1-b3",3,[70,170,500,195],"The RBA steps above are illustrated in the diagram below:",11),
        _text_block("p1-b4",4,[70,470,520,505],"The diagram explains the risk-based approach.",11),
        _text_block("p1-b5",5,[70,520,520,550],"For full guidance and source for Illustration 1: https://example.com",10),
        _text_block("p1-b6",6,[45,745,560,770],"² Refers to customers covered before the new obligation.",8),
        _text_block("p1-b7",7,[295,780,310,794],"84",8),
    ]
    raw.tables=[]
    extraction.summary.text_block_count=len(raw.blocks)
    extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":30,"x1":300,"y1":55,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":430,"y0":80,"x1":540,"y1":98,"boxclass":"section-header","textlines":[{"spans":[{"text":"APPENDIX C"}]}]},
        {"x0":70,"y0":115,"x1":500,"y1":140,"boxclass":"section-header","textlines":[{"spans":[{"text":"Submission of Suspicious Transaction Report (STR)"}]}]},
        {"x0":70,"y0":170,"x1":500,"y1":195,"boxclass":"section-header","textlines":[{"spans":[{"text":"The RBA steps above are illustrated in the diagram below:"}]}]},
        {"x0":100,"y0":210,"x1":520,"y1":450,"boxclass":"picture","textlines":None},
        {"x0":70,"y0":470,"x1":520,"y1":505,"boxclass":"text","textlines":[{"spans":[{"text":"The diagram explains the risk-based approach."}]}]},
        {"x0":70,"y0":520,"x1":520,"y1":550,"boxclass":"text","textlines":[{"spans":[{"text":"For full guidance and source for Illustration 1: https://example.com"}]}]},
        {"x0":45,"y0":745,"x1":560,"y1":770,"boxclass":"page-footer","textlines":[{"spans":[{"text":"² Refers to customers covered before the new obligation."}]}]},
        {"x0":295,"y0":780,"x1":310,"y1":794,"boxclass":"page-footer","textlines":[{"spans":[{"text":"84"}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    assert len(result.appendices)==1
    assert result.appendices[0].label=="APPENDIX C"
    assert result.appendices[0].title=="Submission of Suspicious Transaction Report (STR)"
    assert len(result.figures)==1
    fig=result.figures[0]
    assert fig.intro_element_ids
    assert fig.explanation_element_ids
    assert fig.source_element_ids
    assert any(r.type=="introduces" for r in result.relationships)
    assert any(r.type=="explains" for r in result.relationships)
    assert any(r.type=="source_for" for r in result.relationships)
    assert any(e.type=="footnote" for e in result.pages[0].elements)
    assert next(e for e in result.pages[0].elements if e.text=="84").type=="page_footer"


def test_cross_page_table_repeated_header_is_kept_once():
    record, extraction, layout = _two_page_base()
    header = ["AMLA Provision", "Section 66C", "Section 66B"]
    p1_cells = [header, ["Listing", "UNSCR List", "Domestic List"]]
    p2_cells = [header, ["Subsidiary Legislation", "66C continuation", "66B continuation"]]
    p1_table = TableExtraction(table_id="p1-t1", bbox=[90, 430, 555, 790], row_count=2, col_count=3, cells=p1_cells)
    p2_table = TableExtraction(table_id="p2-t1", bbox=[92, 45, 557, 520], row_count=2, col_count=3, cells=p2_cells)
    extraction.pages = [
        _make_page(1, [_text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22)], [p1_table]),
        _make_page(2, [], [p2_table]),
    ]
    extraction.summary.text_block_count = 1
    extraction.summary.table_count = 2
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            _layout_table(90, 430, 555, 790, p1_cells),
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            _layout_table(92, 45, 557, 520, p2_cells),
        ]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert len(result.tables) == 1
    assert result.tables[0].row_count == 3
    assert result.tables[0].cells[0] == header
    assert result.tables[0].cells.count(header) == 1


def test_cross_page_tables_do_not_merge_when_new_body_content_precedes_table():
    record, extraction, layout = _two_page_base()
    p1_cells = [["A", "B"], ["1", "2"]]
    p2_cells = [["A", "B"], ["3", "4"]]
    p1_table = TableExtraction(table_id="p1-t1", bbox=[90, 430, 555, 790], row_count=2, col_count=2, cells=p1_cells)
    p2_table = TableExtraction(table_id="p2-t1", bbox=[92, 120, 557, 520], row_count=2, col_count=2, cells=p2_cells)
    extraction.pages = [
        _make_page(1, [_text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22)], [p1_table]),
        _make_page(2, [_text_block("p2-b0", 0, [70, 40, 530, 85], "A new paragraph starts before the next table.", 11)], [p2_table]),
    ]
    extraction.summary.text_block_count = 2
    extraction.summary.table_count = 2
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            _layout_table(90, 430, 555, 790, p1_cells),
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0":70,"y0":40,"x1":530,"y1":85,"boxclass":"text","textlines":[{"spans":[{"text":"A new paragraph starts before the next table."}]}]},
            _layout_table(92, 120, 557, 520, p2_cells),
        ]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert len(result.tables) == 2
    assert all(not table.spans_multiple_pages for table in result.tables)


def test_appendix_membership_begins_at_appendix_label_document_order():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 30, 300, 55], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 80, 520, 110], "Normal content before the appendix.", 11),
        _text_block("p1-b2", 2, [430, 180, 540, 198], "APPENDIX C", 12),
        _text_block("p1-b3", 3, [70, 215, 500, 240], "Submission of Suspicious Transaction Report (STR)", 15),
        _text_block("p1-b4", 4, [70, 280, 500, 320], "Appendix body content.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":30,"x1":300,"y1":55,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":80,"x1":520,"y1":110,"boxclass":"text","textlines":[{"spans":[{"text":"Normal content before the appendix."}]}]},
        {"x0":430,"y0":180,"x1":540,"y1":198,"boxclass":"section-header","textlines":[{"spans":[{"text":"APPENDIX C"}]}]},
        {"x0":70,"y0":215,"x1":500,"y1":240,"boxclass":"section-header","textlines":[{"spans":[{"text":"Submission of Suspicious Transaction Report (STR)"}]}]},
        {"x0":70,"y0":280,"x1":500,"y1":320,"boxclass":"text","textlines":[{"spans":[{"text":"Appendix body content."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    page = result.pages[0]
    before = next(element for element in page.elements if element.text == "Normal content before the appendix.")
    label = next(element for element in page.elements if element.text == "APPENDIX C")
    body = next(element for element in page.elements if element.text == "Appendix body content.")
    assert before.appendix_id is None
    assert label.appendix_id == "appendix-c"
    assert body.appendix_id == "appendix-c"
    assert any(r.type == "belongs_to" for r in result.relationships)


def test_figure_explanation_does_not_swallow_following_numbered_clause():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 30, 300, 55], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 100, 500, 130], "The process is illustrated in the diagram below:", 11),
        _text_block("p1-b2", 2, [70, 430, 520, 465], "This diagram summarizes the risk-based approach.", 11),
        _text_block("p1-b3", 3, [70, 490, 520, 530], "2.2 A reporting institution must identify relevant risk factors.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":30,"x1":300,"y1":55,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":500,"y1":130,"boxclass":"section-header","textlines":[{"spans":[{"text":"The process is illustrated in the diagram below:"}]}]},
        {"x0":100,"y0":150,"x1":520,"y1":410,"boxclass":"picture","textlines":None},
        {"x0":70,"y0":430,"x1":520,"y1":465,"boxclass":"text","textlines":[{"spans":[{"text":"This diagram summarizes the risk-based approach."}]}]},
        {"x0":70,"y0":490,"x1":520,"y1":530,"boxclass":"list-item","textlines":[{"spans":[{"text":"2.2 A reporting institution must identify relevant risk factors."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    fig = result.figures[0]
    explanation_texts = [
        next(element for element in result.pages[0].elements if element.element_id == element_id).text
        for element_id in fig.explanation_element_ids
    ]
    assert explanation_texts == ["This diagram summarizes the risk-based approach."]
    clause = next(element for element in result.pages[0].elements if element.type == "clause")
    assert clause.text.startswith("2.2 ")
    assert clause.element_id not in fig.explanation_element_ids



def test_cross_page_definition_reconciliation_repairs_pseudo_heading_and_absorbs_multiple_blocks():
    record, extraction, layout = _fixture()
    record.classification.page_count = 2
    record.classification.text_pages = 2

    page1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 102], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 690, 170, 710], "beneficiary", 11),
        _text_block("p1-b3", 3, [310, 690, 550, 775], "the meaning of the term beneficiary depends on", 11),
    ]
    page2_blocks = [
        _text_block("p2-b0", 0, [310, 35, 550, 55], "the context.", 11),
        _text_block("p2-b1", 1, [310, 80, 550, 290], "In trust law, a beneficiary refers to the person or persons who are entitled to the benefit of any trust arrangement.", 11),
        _text_block("p2-b2", 2, [310, 310, 550, 390], "In wire transfer, refers to the natural or legal person identified by the originator as the receiver of the requested wire transfer.", 11),
        _text_block("p2-b3", 3, [112, 430, 210, 450], "beneficiary institution", 11),
        _text_block("p2-b4", 4, [310, 430, 550, 500], "In wire transfer, refers to the institution which receives the wire transfer from the ordering institution.", 11),
    ]
    extraction.pages = [
        _make_page(1, page1_blocks),
        _make_page(2, page2_blocks),
    ]
    extraction.summary.page_count = 2
    extraction.summary.text_block_count = len(page1_blocks) + len(page2_blocks)
    extraction.summary.table_count = 0

    layout["result"]["toc"] = []
    layout["result"]["page_count"] = 2
    layout["result"]["pages"] = [
        {
            "page_number": 1, "width": 600, "height": 800,
            "boxes": [
                {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
                {"x0":72,"y0":90,"x1":194,"y1":102,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
                {"x0":112,"y0":690,"x1":170,"y1":710,"boxclass":"page-footer","textlines":[{"spans":[{"text":"beneficiary"}]}]},
                {"x0":310,"y0":690,"x1":550,"y1":775,"boxclass":"text","textlines":[{"spans":[{"text":"the meaning of the term beneficiary depends on"}]}]},
            ],
        },
        {
            "page_number": 2, "width": 600, "height": 800,
            "boxes": [
                # Deliberate vendor mistake: continuation fragment is labelled a heading.
                {"x0":310,"y0":35,"x1":550,"y1":55,"boxclass":"section-header","textlines":[{"spans":[{"text":"the context."}]}]},
                {"x0":310,"y0":80,"x1":550,"y1":290,"boxclass":"text","textlines":[{"spans":[{"text":"In trust law, a beneficiary refers to the person or persons who are entitled to the benefit of any trust arrangement."}]}]},
                {"x0":310,"y0":310,"x1":550,"y1":390,"boxclass":"text","textlines":[{"spans":[{"text":"In wire transfer, refers to the natural or legal person identified by the originator as the receiver of the requested wire transfer."}]}]},
                {"x0":112,"y0":430,"x1":210,"y1":450,"boxclass":"text","textlines":[{"spans":[{"text":"beneficiary institution"}]}]},
                {"x0":310,"y0":430,"x1":550,"y1":500,"boxclass":"text","textlines":[{"spans":[{"text":"In wire transfer, refers to the institution which receives the wire transfer from the ordering institution."}]}]},
            ],
        },
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    beneficiary = next(entry for entry in result.definitions if entry.term == "beneficiary")
    institution = next(entry for entry in result.definitions if entry.term == "beneficiary institution")

    assert beneficiary.start_page == 1
    assert beneficiary.end_page == 2
    assert beneficiary.spans_multiple_pages is True
    assert len(beneficiary.definition_element_ids) == 4
    assert "the context." in beneficiary.definition_text
    assert "In trust law" in beneficiary.definition_text
    assert "In wire transfer" in beneficiary.definition_text

    page2 = result.pages[1]
    assert page2.elements[0].type == "definition_text"
    assert page2.elements[0].role_source == "cross_page_definition_reconciliation"
    assert page2.elements[0].heading_level is None
    assert page2.elements[1].definition_entry_id == beneficiary.definition_id
    assert page2.elements[2].definition_entry_id == beneficiary.definition_id
    assert page2.elements[3].definition_entry_id == institution.definition_id

    continuation_relation = next(
        relation for relation in result.relationships
        if relation.type == "continues" and relation.target_element_id == page2.elements[0].element_id
    )
    assert "score=" in continuation_relation.evidence
    assert "definition column" in continuation_relation.evidence


def test_cross_page_definition_reconciliation_does_not_cross_genuine_new_section():
    record, extraction, layout = _fixture()
    record.classification.page_count = 2
    record.classification.text_pages = 2

    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 102], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 690, 170, 710], "beneficiary", 11),
        _text_block("p1-b3", 3, [310, 690, 550, 775], "a complete definition that ends here.", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [72, 45, 260, 70], "4. REPORTING OBLIGATIONS", 14),
        _text_block("p2-b1", 1, [72, 90, 550, 140], "A reporting institution must comply with the following requirements.", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.page_count = 2
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0

    layout["result"]["toc"] = []
    layout["result"]["page_count"] = 2
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":72,"y0":90,"x1":194,"y1":102,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
            {"x0":112,"y0":690,"x1":170,"y1":710,"boxclass":"page-footer","textlines":[{"spans":[{"text":"beneficiary"}]}]},
            {"x0":310,"y0":690,"x1":550,"y1":775,"boxclass":"text","textlines":[{"spans":[{"text":"a complete definition that ends here."}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":72,"y0":45,"x1":260,"y1":70,"boxclass":"section-header","textlines":[{"spans":[{"text":"4. REPORTING OBLIGATIONS"}]}]},
            {"x0":72,"y0":90,"x1":550,"y1":140,"boxclass":"text","textlines":[{"spans":[{"text":"A reporting institution must comply with the following requirements."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    beneficiary = next(entry for entry in result.definitions if entry.term == "beneficiary")
    assert beneficiary.end_page == 1
    assert beneficiary.spans_multiple_pages is False
    assert not any(
        relation.type == "continues" and relation.source_element_id in beneficiary.definition_element_ids
        for relation in result.relationships
    )
    assert result.pages[1].elements[0].type == "section_header"



def test_cross_page_definition_reconciliation_is_term_agnostic():
    record, extraction, layout = _fixture()
    record.classification.page_count = 2
    record.classification.text_pages = 2

    p1 = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Reference Manual", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 102], "5. GLOSSARY", 12),
        _text_block("p1-b2", 2, [105, 690, 190, 710], "alpha control", 11),
        _text_block("p1-b3", 3, [310, 690, 550, 775], "means the primary mechanism used to coordinate", 11),
    ]
    p2 = [
        _text_block("p2-b0", 0, [310, 35, 550, 60], "and monitor the relevant safeguards.", 11),
        _text_block("p2-b1", 1, [105, 130, 190, 150], "beta measure", 11),
        _text_block("p2-b2", 2, [310, 130, 550, 190], "means a secondary measure used for validation.", 11),
    ]
    extraction.pages = [_make_page(1, p1), _make_page(2, p2)]
    extraction.summary.page_count = 2
    extraction.summary.text_block_count = len(p1) + len(p2)
    extraction.summary.table_count = 0

    layout["result"]["toc"] = []
    layout["result"]["page_count"] = 2
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Reference Manual"}]}]},
            {"x0":72,"y0":90,"x1":194,"y1":102,"boxclass":"section-header","textlines":[{"spans":[{"text":"5. GLOSSARY"}]}]},
            {"x0":105,"y0":690,"x1":190,"y1":710,"boxclass":"text","textlines":[{"spans":[{"text":"alpha control"}]}]},
            {"x0":310,"y0":690,"x1":550,"y1":775,"boxclass":"text","textlines":[{"spans":[{"text":"means the primary mechanism used to coordinate"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":310,"y0":35,"x1":550,"y1":60,"boxclass":"section-header","textlines":[{"spans":[{"text":"and monitor the relevant safeguards."}]}]},
            {"x0":105,"y0":130,"x1":190,"y1":150,"boxclass":"text","textlines":[{"spans":[{"text":"beta measure"}]}]},
            {"x0":310,"y0":130,"x1":550,"y1":190,"boxclass":"text","textlines":[{"spans":[{"text":"means a secondary measure used for validation."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    alpha = next(entry for entry in result.definitions if entry.term == "alpha control")
    beta = next(entry for entry in result.definitions if entry.term == "beta measure")
    assert alpha.spans_multiple_pages is True
    assert alpha.end_page == 2
    assert "and monitor the relevant safeguards." in alpha.definition_text
    assert beta.start_page == 2 and beta.end_page == 2
    assert result.pages[1].elements[0].definition_entry_id == alpha.definition_id
    assert result.pages[1].elements[1].definition_entry_id == beta.definition_id


def _multi_span_text_block(
    block_id: str,
    number: int,
    bbox: list[float],
    lines: list[list[tuple[str, list[float]]]],
    size: float = 11,
) -> TextBlock:
    text_lines = []
    block_text_parts = []
    for parts in lines:
        spans = [TextSpan(text=text, bbox=span_bbox, font="TestFont", size=size) for text, span_bbox in parts]
        line_bbox = [
            min(span_bbox[0] for _, span_bbox in parts),
            min(span_bbox[1] for _, span_bbox in parts),
            max(span_bbox[2] for _, span_bbox in parts),
            max(span_bbox[3] for _, span_bbox in parts),
        ]
        line_text = " ".join(text.strip() for text, _ in parts if text.strip())
        text_lines.append(TextLine(bbox=line_bbox, text=line_text, spans=spans))
        block_text_parts.append(line_text)
    return TextBlock(
        block_id=block_id,
        number=number,
        bbox=bbox,
        text="\n".join(block_text_parts),
        lines=text_lines,
    )


def test_definition_row_recovery_splits_wide_body_regions_from_stage3_columns():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 150, 190, 165], "alpha control", 11),
        _text_block("p1-b3", 3, [310, 150, 550, 190], "means the first control used for testing.", 11),
        _multi_span_text_block(
            "p1-b4",
            4,
            [112, 230, 550, 280],
            [
                [
                    ("nominator", [112, 230, 180, 245]),
                    ("means an individual or group that issues instructions", [310, 230, 550, 245]),
                ],
                [("to a nominee to act on its behalf.", [310, 248, 550, 263])],
            ],
        ),
        _text_block("p1-b5", 5, [112, 320, 550, 350], "customer means new or existing customer.", 11),
        _text_block("p1-b6", 6, [295, 780, 310, 794], "10", 8),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":150,"x1":190,"y1":165,"boxclass":"text","textlines":[{"spans":[{"text":"alpha control"}]}]},
        {"x0":310,"y0":150,"x1":550,"y1":190,"boxclass":"text","textlines":[{"spans":[{"text":"means the first control used for testing."}]}]},
        {"x0":112,"y0":230,"x1":550,"y1":280,"boxclass":"text","textlines":[
            {"spans":[{"text":"nominator"},{"text":" means an individual or group that issues instructions"}]},
            {"spans":[{"text":"to a nominee to act on its behalf."}]},
        ]},
        {"x0":112,"y0":320,"x1":550,"y1":350,"boxclass":"text","textlines":[{"spans":[{"text":"customer means new or existing customer."}]}]},
        {"x0":295,"y0":780,"x1":310,"y1":794,"boxclass":"page-footer","textlines":[{"spans":[{"text":"10"}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    terms = [entry.term for entry in result.definitions]
    assert terms == ["alpha control", "nominator", "customer"]

    nominator = next(entry for entry in result.definitions if entry.term == "nominator")
    nom_term = next(e for e in result.pages[0].elements if e.element_id == nominator.term_element_id)
    nom_text = next(e for e in result.pages[0].elements if e.element_id in nominator.definition_element_ids)
    assert nom_term.role_source == "definition_row_recovery_span_columns"
    assert nom_text.role_source == "definition_row_recovery_span_columns"
    assert nom_term.bbox[2] < nom_text.bbox[0]
    assert nom_term.source.stage3_span_ids
    assert nom_text.source.stage3_span_ids
    assert set(nom_term.source.stage3_span_ids).isdisjoint(nom_text.source.stage3_span_ids)
    assert "issues instructions" in nominator.definition_text
    assert "act on its behalf" in nominator.definition_text

    customer = next(entry for entry in result.definitions if entry.term == "customer")
    customer_term = next(e for e in result.pages[0].elements if e.element_id == customer.term_element_id)
    assert customer_term.role_source == "definition_row_recovery_text_pattern"
    assert customer.definition_text == "means new or existing customer."


def test_definition_row_recovery_can_split_multiple_rows_from_one_vendor_box():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _multi_span_text_block(
            "p1-b2",
            2,
            [112, 170, 550, 285],
            [
                [("alpha control", [112, 170, 190, 185]), ("means the first safeguard.", [310, 170, 550, 185])],
                [("beta measure", [112, 245, 190, 260]), ("refers to the second safeguard.", [310, 245, 550, 260])],
            ],
        ),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":170,"x1":550,"y1":285,"boxclass":"text","textlines":[
            {"spans":[{"text":"alpha control"},{"text":" means the first safeguard."}]},
            {"spans":[{"text":"beta measure"},{"text":" refers to the second safeguard."}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [entry.term for entry in result.definitions] == ["alpha control", "beta measure"]
    assert all(entry.source_kind == "layout_columns" for entry in result.definitions)
    assert all(entry.definition_text for entry in result.definitions)
    assert result.summary.definition_count == 2
    recovered = [
        element for element in result.pages[0].elements
        if element.role_source == "definition_row_recovery_span_columns"
    ]
    span_owners: dict[str, list[str]] = {}
    for element in recovered:
        for span_id in element.source.stage3_span_ids:
            span_owners.setdefault(span_id, []).append(element.element_id)
    assert not {span_id: owners for span_id, owners in span_owners.items() if len(owners) > 1}


def test_definition_row_recovery_does_not_split_unrelated_wide_prose():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    prose = "This explanatory note applies throughout the glossary and provides general context for readers."
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [90, 170, 550, 215], prose, 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":90,"y0":170,"x1":550,"y1":215,"boxclass":"text","textlines":[{"spans":[{"text":prose}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert result.definitions == []
    element = next(e for e in result.pages[0].elements if e.text == prose)
    assert element.type == "paragraph"
    assert element.role_source == "layout"


def test_definition_row_recovery_is_vocabulary_agnostic_with_shall_mean_pattern():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    merged = "gamma mechanism shall mean a synthetic control used only for regression testing."
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 170, 550, 215], merged, 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":170,"x1":550,"y1":215,"boxclass":"text","textlines":[{"spans":[{"text":merged}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [entry.term for entry in result.definitions] == ["gamma mechanism"]
    assert result.definitions[0].definition_text.startswith("shall mean")


def test_parallel_tall_columns_are_reconstructed_into_definition_rows():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 135, 190, 150], "anchor term", 11),
        _text_block("p1-b3", 3, [310, 135, 550, 170], "means an anchor definition used to learn the columns.", 11),
        _multi_span_text_block(
            "p1-b4",
            4,
            [112, 220, 210, 430],
            [
                [("alpha service", [112, 220, 190, 235])],
                [("beta control", [112, 290, 190, 305])],
                [("gamma mechanism", [112, 365, 205, 380])],
            ],
        ),
        _multi_span_text_block(
            "p1-b5",
            5,
            [310, 220, 550, 450],
            [
                [("means the first synthetic definition.", [310, 220, 550, 235])],
                [("refers to the second synthetic definition.", [310, 290, 550, 305])],
                [("includes the third synthetic definition", [310, 365, 550, 380])],
                [("with an additional continuation line.", [310, 383, 550, 398])],
            ],
        ),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":135,"x1":190,"y1":150,"boxclass":"text","textlines":[{"spans":[{"text":"anchor term"}]}]},
        {"x0":310,"y0":135,"x1":550,"y1":170,"boxclass":"text","textlines":[{"spans":[{"text":"means an anchor definition used to learn the columns."}]}]},
        {"x0":112,"y0":220,"x1":210,"y1":430,"boxclass":"text","textlines":[
            {"spans":[{"text":"alpha service"}]},
            {"spans":[{"text":"beta control"}]},
            {"spans":[{"text":"gamma mechanism"}]},
        ]},
        {"x0":310,"y0":220,"x1":550,"y1":450,"boxclass":"text","textlines":[
            {"spans":[{"text":"means the first synthetic definition."}]},
            {"spans":[{"text":"refers to the second synthetic definition."}]},
            {"spans":[{"text":"includes the third synthetic definition with an additional continuation line."}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    by_term = {entry.term: entry for entry in result.definitions}
    assert {"anchor term", "alpha service", "beta control", "gamma mechanism"}.issubset(by_term)
    gamma = by_term["gamma mechanism"]
    assert "additional continuation line" in gamma.definition_text
    term_element = next(e for e in result.pages[0].elements if e.element_id == gamma.term_element_id)
    assert term_element.role_source == "definition_parallel_stream_recovery"
    assert not any(
        e.text.startswith("alpha service beta control")
        for e in result.pages[0].elements
    )


def test_glossary_like_vendor_table_is_semantically_promoted_to_definition_entries():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    cells = [
        ["alpha asset", "means a synthetic asset used in regression testing."],
        ["beta token", "refers to a second synthetic concept used for validation."],
        ["gamma person", "means a person designated for a hypothetical control."],
        ["delta group", "includes a group of related synthetic entities."],
    ]
    table = TableExtraction(table_id="p1-t1", bbox=[110, 170, 555, 600], row_count=4, col_count=2, cells=cells)
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
    ]
    raw.tables = [table]
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 1
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        _layout_table(110, 170, 555, 600, cells),
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [entry.term for entry in result.definitions] == ["alpha asset", "beta token", "gamma person", "delta group"]
    assert all(entry.source_kind == "table_rows" for entry in result.definitions)
    assert all(entry.source_table_element_id == "p1-e3" for entry in result.definitions)
    assert not any(element.type == "table" for element in result.pages[0].elements)
    assert result.tables == []
    assert all(
        element.source.layout_box_class == "table"
        for element in result.pages[0].elements
        if element.type in {"definition_term", "definition_text"}
    )


def test_two_column_table_inside_definitions_is_not_promoted_without_glossary_signature():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    cells = [
        ["Category", "Amount"],
        ["A", "100"],
        ["B", "200"],
        ["C", "300"],
    ]
    table = TableExtraction(table_id="p1-t1", bbox=[110, 170, 555, 420], row_count=4, col_count=2, cells=cells)
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
    ]
    raw.tables = [table]
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 1
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        _layout_table(110, 170, 555, 420, cells),
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert result.definitions == []
    assert any(element.type == "table" for element in result.pages[0].elements)
    assert len(result.tables) == 1


def test_definition_with_nested_items_can_continue_across_page_boundary():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 700, 205, 720], "related concept", 11),
        _text_block("p1-b3", 3, [310, 700, 370, 720], "means—", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [310, 35, 550, 80], "(a) first enumerated continuation item;", 11),
        _text_block("p2-b1", 1, [310, 95, 550, 140], "(b) second enumerated continuation item;", 11),
        _text_block("p2-b2", 2, [310, 155, 550, 200], "(c) third enumerated continuation item;", 11),
        _text_block("p2-b3", 3, [310, 215, 550, 260], "(d) fourth enumerated continuation item.", 11),
        _text_block("p2-b4", 4, [112, 340, 190, 355], "next term", 11),
        _text_block("p2-b5", 5, [310, 340, 550, 380], "means the next independent definition.", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
            {"x0":112,"y0":700,"x1":205,"y1":720,"boxclass":"text","textlines":[{"spans":[{"text":"related concept"}]}]},
            {"x0":310,"y0":700,"x1":370,"y1":720,"boxclass":"text","textlines":[{"spans":[{"text":"means—"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":310,"y0":35,"x1":550,"y1":80,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) first enumerated continuation item;"}]}]},
            {"x0":310,"y0":95,"x1":550,"y1":140,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) second enumerated continuation item;"}]}]},
            {"x0":310,"y0":155,"x1":550,"y1":200,"boxclass":"list-item","textlines":[{"spans":[{"text":"(c) third enumerated continuation item;"}]}]},
            {"x0":310,"y0":215,"x1":550,"y1":260,"boxclass":"list-item","textlines":[{"spans":[{"text":"(d) fourth enumerated continuation item."}]}]},
            {"x0":112,"y0":340,"x1":190,"y1":355,"boxclass":"text","textlines":[{"spans":[{"text":"next term"}]}]},
            {"x0":310,"y0":340,"x1":550,"y1":380,"boxclass":"text","textlines":[{"spans":[{"text":"means the next independent definition."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    related = next(entry for entry in result.definitions if entry.term == "related concept")
    nxt = next(entry for entry in result.definitions if entry.term == "next term")
    assert related.spans_multiple_pages is True
    assert related.start_page == 1 and related.end_page == 2
    assert [item.marker for item in related.items] == ["(a)", "(b)", "(c)", "(d)"]
    assert nxt.start_page == 2 and nxt.end_page == 2
    assert any(
        relation.type == "continues"
        and relation.source_element_id in related.definition_element_ids
        and relation.target_element_id in related.definition_element_ids
        for relation in result.relationships
    )


def test_nested_definition_items_do_not_absorb_trailing_explanation_into_last_item():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 160, 260, 190], "synthetic exposed person", 11),
        _text_block("p1-b3", 3, [310, 160, 370, 180], "means—", 11),
        _text_block("p1-b4", 4, [310, 205, 550, 250], "(a) first category;", 11),
        _text_block("p1-b5", 5, [310, 265, 550, 310], "(b) second category;", 11),
        _text_block("p1-b6", 6, [310, 325, 550, 370], "(c) third category.", 11),
        _text_block("p1-b7", 7, [310, 390, 550, 430], "This trailing explanation applies to the definition as a whole.", 11),
        _text_block("p1-b8", 8, [112, 480, 190, 495], "next term", 11),
        _text_block("p1-b9", 9, [310, 480, 550, 520], "means another definition.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":160,"x1":260,"y1":190,"boxclass":"text","textlines":[{"spans":[{"text":"synthetic exposed person"}]}]},
        {"x0":310,"y0":160,"x1":370,"y1":180,"boxclass":"text","textlines":[{"spans":[{"text":"means—"}]}]},
        {"x0":310,"y0":205,"x1":550,"y1":250,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) first category;"}]}]},
        {"x0":310,"y0":265,"x1":550,"y1":310,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) second category;"}]}]},
        {"x0":310,"y0":325,"x1":550,"y1":370,"boxclass":"list-item","textlines":[{"spans":[{"text":"(c) third category."}]}]},
        {"x0":310,"y0":390,"x1":550,"y1":430,"boxclass":"text","textlines":[{"spans":[{"text":"This trailing explanation applies to the definition as a whole."}]}]},
        {"x0":112,"y0":480,"x1":190,"y1":495,"boxclass":"text","textlines":[{"spans":[{"text":"next term"}]}]},
        {"x0":310,"y0":480,"x1":550,"y1":520,"boxclass":"text","textlines":[{"spans":[{"text":"means another definition."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    entry = next(item for item in result.definitions if item.term == "synthetic exposed person")
    assert [item.marker for item in entry.items] == ["(a)", "(b)", "(c)"]
    assert entry.items[-1].text == "third category."
    assert "trailing explanation" in entry.definition_text


def test_general_open_block_engine_records_cross_page_clause_continuation():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 730, 540, 780], "2.5 A reporting institution must document the process and", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [105, 35, 540, 75], "retain sufficient evidence for supervisory review.", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = 3
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":70,"y0":730,"x1":540,"y1":780,"boxclass":"list-item","textlines":[{"spans":[{"text":"2.5 A reporting institution must document the process and"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":105,"y0":35,"x1":540,"y1":75,"boxclass":"text","textlines":[{"spans":[{"text":"retain sufficient evidence for supervisory review."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    clause = next(e for e in result.pages[0].elements if e.type == "clause")
    continuation = result.pages[1].elements[0]
    relation = next(
        r for r in result.relationships
        if r.type == "continues" and r.source_element_id == clause.element_id and r.target_element_id == continuation.element_id
    )
    assert "open clause continuation" in relation.evidence


def test_multiline_definition_term_is_consolidated_before_pairing():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 160, 255, 175], "Synthetic Network Provider", 11),
        _text_block("p1-b3", 3, [112, 177, 155, 192], "(SNP)", 11),
        _text_block("p1-b4", 4, [310, 160, 550, 220], "means a synthetic provider used only for regression testing.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":160,"x1":255,"y1":175,"boxclass":"text","textlines":[{"spans":[{"text":"Synthetic Network Provider"}]}]},
        {"x0":112,"y0":177,"x1":155,"y1":192,"boxclass":"text","textlines":[{"spans":[{"text":"(SNP)"}]}]},
        {"x0":310,"y0":160,"x1":550,"y1":220,"boxclass":"text","textlines":[{"spans":[{"text":"means a synthetic provider used only for regression testing."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [entry.term for entry in result.definitions] == ["Synthetic Network Provider (SNP)"]
    entry = result.definitions[0]
    term = next(element for element in result.pages[0].elements if element.element_id == entry.term_element_id)
    assert term.role_source == "definition_multiline_term_consolidation"
    assert term.bbox[1] == 160 and term.bbox[3] == 192
    assert set(term.source.stage3_block_ids) == {"p1-b2", "p1-b3"}
    assert not any(element.text.strip() == "(SNP)" for element in result.pages[0].elements)


def test_dense_adjacent_definition_rows_are_not_merged_as_multiline_term():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 160, 190, 175], "alpha service", 11),
        _text_block("p1-b3", 3, [310, 160, 550, 178], "means the first independent concept.", 11),
        _text_block("p1-b4", 4, [112, 184, 190, 199], "beta control", 11),
        _text_block("p1-b5", 5, [310, 184, 550, 202], "means the second independent concept.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":160,"x1":190,"y1":175,"boxclass":"text","textlines":[{"spans":[{"text":"alpha service"}]}]},
        {"x0":310,"y0":160,"x1":550,"y1":178,"boxclass":"text","textlines":[{"spans":[{"text":"means the first independent concept."}]}]},
        {"x0":112,"y0":184,"x1":190,"y1":199,"boxclass":"text","textlines":[{"spans":[{"text":"beta control"}]}]},
        {"x0":310,"y0":184,"x1":550,"y1":202,"boxclass":"text","textlines":[{"spans":[{"text":"means the second independent concept."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [entry.term for entry in result.definitions] == ["alpha service", "beta control"]


def test_empty_textual_layout_artifact_is_removed_after_reconstruction():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 160, 190, 175], "alpha service", 11),
        _text_block("p1-b3", 3, [310, 160, 550, 195], "means a valid synthetic definition.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":160,"x1":190,"y1":175,"boxclass":"text","textlines":[{"spans":[{"text":"alpha service"}]}]},
        {"x0":310,"y0":160,"x1":550,"y1":195,"boxclass":"text","textlines":[{"spans":[{"text":"means a valid synthetic definition."}]}]},
        {"x0":260,"y0":210,"x1":330,"y1":270,"boxclass":"text","textlines":[]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [entry.term for entry in result.definitions] == ["alpha service"]
    assert all(element.text.strip() for element in result.pages[0].elements if element.type not in {"figure", "table", "formula"})
    assert not any(element.bbox == [260.0, 210.0, 330.0, 270.0] for element in result.pages[0].elements)


def test_multiline_definition_term_can_be_completed_from_stage3_when_vendor_omits_first_line():
    """A missing canonical line must not prevent a wrapped term from being recovered."""
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 160, 270, 175], "Synthetic Network Provider", 11),
        _text_block("p1-b3", 3, [112, 177, 155, 192], "(SNP)", 11),
        _text_block("p1-b4", 4, [310, 160, 550, 220], "means a synthetic provider used only for regression testing.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    # Simulate a vendor failure: the first term line is absent from layout
    # output even though immutable Stage 3 still contains it.
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":177,"x1":155,"y1":192,"boxclass":"text","textlines":[{"spans":[{"text":"(SNP)"}]}]},
        {"x0":310,"y0":160,"x1":550,"y1":220,"boxclass":"text","textlines":[{"spans":[{"text":"means a synthetic provider used only for regression testing."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [entry.term for entry in result.definitions] == ["Synthetic Network Provider (SNP)"]
    entry = result.definitions[0]
    term = next(element for element in result.pages[0].elements if element.element_id == entry.term_element_id)
    assert term.role_source == "definition_multiline_term_stage3_completion"
    assert term.bbox == [112.0, 160.0, 270.0, 192.0]
    assert {"p1-b2", "p1-b3"}.issubset(set(term.source.stage3_block_ids))
    assert not any(element.text.strip() == "(SNP)" for element in result.pages[0].elements)


def test_table_derived_definition_geometry_snaps_to_stage3_text_and_removes_blank_extension():
    """Synthetic table-row boxes should use real text geometry when available."""
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    cells = [
        ["alpha term", "means the first synthetic definition."],
        ["beta term", "means the second synthetic definition:"],
        ["", "additional continuation detail for the second definition."],
    ]
    table = TableExtraction(table_id="p1-t1", bbox=[110, 150, 560, 390], row_count=3, col_count=2, cells=cells)
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 165, 180, 180], "alpha term", 11),
        _text_block("p1-b3", 3, [360, 165, 550, 195], "means the first synthetic definition.", 11),
        _text_block("p1-b4", 4, [112, 235, 180, 250], "beta term", 11),
        _text_block("p1-b5", 5, [360, 235, 550, 270], "means the second synthetic definition:", 11),
        _text_block("p1-b6", 6, [360, 300, 550, 335], "additional continuation detail for the second definition.", 11),
    ]
    raw.tables = [table]
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 1
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":194,"y1":104,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        _layout_table(110, 150, 560, 390, cells),
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    beta = next(entry for entry in result.definitions if entry.term == "beta term")
    continuation = next(
        element for element in result.pages[0].elements
        if element.element_id in beta.definition_element_ids
        and "additional continuation detail" in element.text
    )
    # The semantic table fallback used to create a synthetic box that could
    # extend into the empty inter-column gap.  Stage-3 text geometry is the
    # source of truth for the rendered canonical bbox when it exists.
    assert continuation.bbox == [360.0, 300.0, 550.0, 335.0]
    assert continuation.role_source == "definition_table_semantic_normalization"


def test_cross_page_definition_nested_sequence_skips_running_header():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 194, 104], "3. DEFINITIONS", 12),
        _text_block("p1-b2", 2, [112, 630, 205, 650], "controller", 11),
        _text_block("p1-b3", 3, [310, 630, 550, 675], "means a person who—", 11),
        _text_block("p1-b4", 4, [310, 690, 550, 755], "(a) first condition in the definition;", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [360, 35, 545, 50], "Chapter 1: Introduction", 8),
        _text_block("p2-b1", 1, [310, 90, 550, 145], "(b) second condition in the definition;", 11),
        _text_block("p2-b2", 2, [310, 165, 550, 220], "(c) third condition in the definition.", 11),
        _text_block("p2-b3", 3, [112, 330, 170, 350], "CPE", 11),
        _text_block("p2-b4", 4, [310, 330, 550, 370], "means continuing professional education.", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "title", "textlines": [{"spans": [{"text": "Sample Report"}]}]},
            {"x0": 72, "y0": 90, "x1": 194, "y1": 104, "boxclass": "section-header", "textlines": [{"spans": [{"text": "3. DEFINITIONS"}]}]},
            {"x0": 112, "y0": 630, "x1": 205, "y1": 650, "boxclass": "text", "textlines": [{"spans": [{"text": "controller"}]}]},
            {"x0": 310, "y0": 630, "x1": 550, "y1": 675, "boxclass": "text", "textlines": [{"spans": [{"text": "means a person who—"}]}]},
            {"x0": 310, "y0": 690, "x1": 550, "y1": 755, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(a) first condition in the definition;"}]}]},
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0": 360, "y0": 35, "x1": 545, "y1": 50, "boxclass": "page-header", "textlines": [{"spans": [{"text": "Chapter 1: Introduction"}]}]},
            {"x0": 310, "y0": 90, "x1": 550, "y1": 145, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(b) second condition in the definition;"}]}]},
            {"x0": 310, "y0": 165, "x1": 550, "y1": 220, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(c) third condition in the definition."}]}]},
            {"x0": 112, "y0": 330, "x1": 170, "y1": 350, "boxclass": "text", "textlines": [{"spans": [{"text": "CPE"}]}]},
            {"x0": 310, "y0": 330, "x1": 550, "y1": 370, "boxclass": "text", "textlines": [{"spans": [{"text": "means continuing professional education."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    controller = next(entry for entry in result.definitions if entry.term == "controller")
    assert controller.spans_multiple_pages is True
    assert controller.start_page == 1 and controller.end_page == 2
    assert [item.marker for item in controller.items] == ["(a)", "(b)", "(c)"]
    assert any(
        relation.type == "continues"
        and relation.source_element_id in controller.definition_element_ids
        and relation.target_element_id in controller.definition_element_ids
        for relation in result.relationships
    )


def test_generic_cross_page_hierarchy_does_not_mark_bullet_siblings_as_text_continuation():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 110, 330, 130], "Operational requirements", 14),
        _text_block("p1-b2", 2, [110, 710, 520, 750], "• Dealing in derivatives; and", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [360, 35, 545, 50], "Chapter 4: Licensing Criteria", 8),
        _text_block("p2-b1", 1, [110, 80, 350, 105], "• Fund management.", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "title", "textlines": [{"spans": [{"text": "Sample Report"}]}]},
            {"x0": 70, "y0": 110, "x1": 330, "y1": 130, "boxclass": "section-header", "textlines": [{"spans": [{"text": "Operational requirements"}]}]},
            {"x0": 110, "y0": 710, "x1": 520, "y1": 750, "boxclass": "list-item", "textlines": [{"spans": [{"text": "• Dealing in derivatives; and"}]}]},
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0": 360, "y0": 35, "x1": 545, "y1": 50, "boxclass": "page-header", "textlines": [{"spans": [{"text": "Chapter 4: Licensing Criteria"}]}]},
            {"x0": 110, "y0": 80, "x1": 350, "y1": 105, "boxclass": "list-item", "textlines": [{"spans": [{"text": "• Fund management."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    source = next(e for e in result.pages[0].elements if "Dealing in derivatives" in e.text)
    target = next(e for e in result.pages[1].elements if "Fund management" in e.text)
    assert source.section_id == target.section_id
    assert not any(
        r.type == "continues"
        and r.source_element_id == source.element_id
        and r.target_element_id == target.element_id
        for r in result.relationships
    )


def test_generic_cross_page_hierarchy_treats_nested_marker_as_fresh_child_not_text_continuation():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 110, 330, 130], "Technology requirements", 14),
        _text_block("p1-b2", 2, [100, 700, 540, 760], "(b) ensure that the outcomes produced by the algorithm are—", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [360, 35, 545, 50], "Chapter 4: Licensing Criteria", 8),
        _text_block("p2-b1", 1, [130, 85, 540, 125], "(i) consistent with the investment strategies;", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "title", "textlines": [{"spans": [{"text": "Sample Report"}]}]},
            {"x0": 70, "y0": 110, "x1": 330, "y1": 130, "boxclass": "section-header", "textlines": [{"spans": [{"text": "Technology requirements"}]}]},
            {"x0": 100, "y0": 700, "x1": 540, "y1": 760, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(b) ensure that the outcomes produced by the algorithm are—"}]}]},
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0": 360, "y0": 35, "x1": 545, "y1": 50, "boxclass": "page-header", "textlines": [{"spans": [{"text": "Chapter 4: Licensing Criteria"}]}]},
            {"x0": 130, "y0": 85, "x1": 540, "y1": 125, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(i) consistent with the investment strategies;"}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    source = next(e for e in result.pages[0].elements if e.text.startswith("(b)"))
    target = next(e for e in result.pages[1].elements if e.text.startswith("(i)"))
    assert target.type == "list_item"
    assert not any(
        r.type == "continues"
        and r.source_element_id == source.element_id
        and r.target_element_id == target.element_id
        for r in result.relationships
    )


def test_generic_cross_page_hierarchy_does_not_mark_numbered_siblings_as_text_continuation():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 110, 330, 130], "Requirement for licensed director", 14),
        _text_block("p1-b2", 2, [85, 700, 540, 760], "(20) final requirement on this page.", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [360, 35, 545, 50], "Chapter 4: Licensing Criteria", 8),
        _text_block("p2-b1", 1, [85, 85, 540, 135], "(21) first requirement on the next page.", 11),
        _text_block("p2-b2", 2, [70, 300, 360, 325], "Requirement for head of regulated activity", 14),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "title", "textlines": [{"spans": [{"text": "Sample Report"}]}]},
            {"x0": 70, "y0": 110, "x1": 330, "y1": 130, "boxclass": "section-header", "textlines": [{"spans": [{"text": "Requirement for licensed director"}]}]},
            {"x0": 85, "y0": 700, "x1": 540, "y1": 760, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(20) final requirement on this page."}]}]},
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0": 360, "y0": 35, "x1": 545, "y1": 50, "boxclass": "page-header", "textlines": [{"spans": [{"text": "Chapter 4: Licensing Criteria"}]}]},
            {"x0": 85, "y0": 85, "x1": 540, "y1": 135, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(21) first requirement on the next page."}]}]},
            {"x0": 70, "y0": 300, "x1": 360, "y1": 325, "boxclass": "section-header", "textlines": [{"spans": [{"text": "Requirement for head of regulated activity"}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    source = next(e for e in result.pages[0].elements if e.text.startswith("(20)"))
    target = next(e for e in result.pages[1].elements if e.text.startswith("(21)"))
    assert source.section_id == target.section_id
    assert not any(
        r.type == "continues"
        and r.source_element_id == source.element_id
        and r.target_element_id == target.element_id
        for r in result.relationships
    )


def test_generic_cross_page_hierarchy_stops_at_new_section_before_candidate():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 110, 330, 130], "First requirements", 14),
        _text_block("p1-b2", 2, [85, 700, 540, 760], "(20) final item in the first section.", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [360, 35, 545, 50], "Chapter 4: Licensing Criteria", 8),
        _text_block("p2-b1", 1, [70, 75, 360, 100], "Different requirements", 14),
        _text_block("p2-b2", 2, [85, 125, 540, 170], "(21) item under the new section.", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "title", "textlines": [{"spans": [{"text": "Sample Report"}]}]},
            {"x0": 70, "y0": 110, "x1": 330, "y1": 130, "boxclass": "section-header", "textlines": [{"spans": [{"text": "First requirements"}]}]},
            {"x0": 85, "y0": 700, "x1": 540, "y1": 760, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(20) final item in the first section."}]}]},
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0": 360, "y0": 35, "x1": 545, "y1": 50, "boxclass": "page-header", "textlines": [{"spans": [{"text": "Chapter 4: Licensing Criteria"}]}]},
            {"x0": 70, "y0": 75, "x1": 360, "y1": 100, "boxclass": "section-header", "textlines": [{"spans": [{"text": "Different requirements"}]}]},
            {"x0": 85, "y0": 125, "x1": 540, "y1": 170, "boxclass": "list-item", "textlines": [{"spans": [{"text": "(21) item under the new section."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    source = next(e for e in result.pages[0].elements if e.text.startswith("(20)"))
    target = next(e for e in result.pages[1].elements if e.text.startswith("(21)"))
    assert not any(r.type == "continues" and r.source_element_id == source.element_id and r.target_element_id == target.element_id for r in result.relationships)


def test_toc_table_repair_splits_embedded_heading_from_following_entry_without_splitting_wrapped_titles():
    record, extraction, layout = _fixture()
    cells = [
        ["6A.", "Internal Programmes, Policies, Procedures and Controls", "20"],
        ["6E.", "Group-wide AML/CFT/CPF Programmes", "24"],
        ["PART     \n7", "II: RISK-BASED APPROACH APPLICATION \n         Risk-Based Approach Application", "25"],
        ["7.1", "ML/TF Risk Assessment", "25"],
        ["7.2", "ML/TF Risk Management and Mitigation", "26"],
        ["7.6", "Risk Management and Mitigation in Third-Party Deposits and \nPayments", "29"],
        ["PART", "III: CUSTOMER DUE DILIGENCE", ""],
        ["8", "Customer Due Diligence", "30"],
    ]
    extraction.pages[0].blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "CONTENTS", 22),
    ]
    extraction.pages[0].tables = [
        TableExtraction(
            table_id="p1-t1",
            bbox=[70, 120, 530, 700],
            row_count=len(cells),
            col_count=3,
            cells=cells,
        )
    ]
    extraction.summary.text_block_count = 1
    extraction.summary.table_count = 1
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {
            "x0": 50, "y0": 40, "x1": 300, "y1": 70,
            "boxclass": "section-header",
            "textlines": [{"spans": [{"text": "CONTENTS"}]}],
        },
        _layout_table(70, 120, 530, 700, cells),
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    table_element = result.pages[0].elements[1]
    assert table_element.type == "table"
    assert table_element.table is not None
    repaired = table_element.table.cells

    assert ["PART", "II: RISK-BASED APPROACH APPLICATION", ""] in repaired
    assert ["7", "Risk-Based Approach Application", "25"] in repaired
    assert ["PART     \n7", "II: RISK-BASED APPROACH APPLICATION \n         Risk-Based Approach Application", "25"] not in repaired
    assert ["7.6", "Risk Management and Mitigation in Third-Party Deposits and \nPayments", "29"] in repaired
    assert table_element.table.row_count == len(cells) + 1
    assert result.tables[0].row_count == len(cells) + 1
    assert "PART\tII: RISK-BASED APPROACH APPLICATION" in table_element.text
    assert "7\tRisk-Based Approach Application\t25" in table_element.text
    assert "|PART|II: RISK-BASED APPROACH APPLICATION||" in (table_element.table.markdown or "")


def test_toc_table_repair_does_not_run_without_explicit_contents_context():
    record, extraction, layout = _fixture()
    cells = [
        ["6A.", "Internal Programmes, Policies, Procedures and Controls", "20"],
        ["6E.", "Group-wide AML/CFT/CPF Programmes", "24"],
        ["PART     \n7", "II: RISK-BASED APPROACH APPLICATION \n         Risk-Based Approach Application", "25"],
        ["7.1", "ML/TF Risk Assessment", "25"],
        ["7.2", "ML/TF Risk Management and Mitigation", "26"],
        ["7.6", "Risk Management and Mitigation in Third-Party Deposits and \nPayments", "29"],
        ["PART", "III: CUSTOMER DUE DILIGENCE", ""],
        ["8", "Customer Due Diligence", "30"],
    ]
    extraction.pages[0].blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Quarterly Risk Register", 22),
    ]
    extraction.pages[0].tables = [
        TableExtraction(
            table_id="p1-t1",
            bbox=[70, 120, 530, 700],
            row_count=len(cells),
            col_count=3,
            cells=cells,
        )
    ]
    extraction.summary.text_block_count = 1
    extraction.summary.table_count = 1
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {
            "x0": 50, "y0": 40, "x1": 300, "y1": 70,
            "boxclass": "title",
            "textlines": [{"spans": [{"text": "Quarterly Risk Register"}]}],
        },
        _layout_table(70, 120, 530, 700, cells),
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    table_element = result.pages[0].elements[1]
    assert table_element.type == "table"
    assert table_element.table is not None

    canonical_cells = table_element.table.cells
    merged = ["PART     \n7", "II: RISK-BASED APPROACH APPLICATION \n         Risk-Based Approach Application", "25"]
    assert merged in canonical_cells
    assert ["PART", "II: RISK-BASED APPROACH APPLICATION", ""] not in canonical_cells
    assert ["7", "Risk-Based Approach Application", "25"] not in canonical_cells
    assert table_element.table.row_count == len(cells)
    assert result.tables[0].row_count == len(cells)


def test_toc_context_inherits_to_adjacent_table_continuation_without_repeated_contents_heading():
    record, extraction, layout = _two_page_base()
    p1_cells = [
        ["1.", "Introduction", "5"],
        ["2.", "Applicability", "6"],
        ["3.", "Definitions", "8"],
        ["4.", "General Description", "16"],
    ]
    p2_cells = [
        ["PART\n5", "II: RISK-BASED APPROACH\nRisk-Based Approach", "25"],
        ["5.1", "Risk Assessment", "25"],
        ["5.2", "Risk Management and Mitigation", "26"],
        ["5.3", "Risk Profiling", "28"],
    ]
    p1_blocks = [_text_block("p1-b0", 0, [50, 40, 300, 70], "CONTENTS", 16)]
    p2_blocks = [_text_block("p2-b0", 0, [360, 20, 545, 35], "Guidelines", 8)]
    extraction.pages = [
        _make_page(1, p1_blocks, [TableExtraction(table_id="p1-t1", bbox=[70, 430, 530, 790], row_count=4, col_count=3, cells=p1_cells)]),
        _make_page(2, p2_blocks, [TableExtraction(table_id="p2-t1", bbox=[72, 45, 532, 720], row_count=4, col_count=3, cells=p2_cells)]),
    ]
    extraction.summary.text_block_count = 2
    extraction.summary.table_count = 2
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {
            "page_number": 1, "width": 600, "height": 800,
            "boxes": [
                {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "section-header", "textlines": [{"spans": [{"text": "CONTENTS"}]}]},
                _layout_table(70, 430, 530, 790, p1_cells),
            ],
        },
        {
            "page_number": 2, "width": 600, "height": 800,
            "boxes": [
                {"x0": 360, "y0": 20, "x1": 545, "y1": 35, "boxclass": "page-header", "textlines": [{"spans": [{"text": "Guidelines"}]}]},
                _layout_table(72, 45, 532, 720, p2_cells),
            ],
        },
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    p2_table = next(e for e in result.pages[1].elements if e.type == "table")
    assert p2_table.table is not None
    assert ["PART", "II: RISK-BASED APPROACH", ""] in p2_table.table.cells
    assert ["5", "Risk-Based Approach", "25"] in p2_table.table.cells
    assert p2_cells[0] not in p2_table.table.cells
    assert p2_table.table.row_count == len(p2_cells) + 1

    assert len(result.tables) == 1
    logical = result.tables[0]
    assert logical.spans_multiple_pages is True
    assert logical.start_page == 1 and logical.end_page == 2
    assert ["PART", "II: RISK-BASED APPROACH", ""] in logical.cells
    assert ["5", "Risk-Based Approach", "25"] in logical.cells


def test_toc_context_inheritance_propagates_across_multiple_continuation_pages():
    record, extraction, layout = _fixture()
    record.classification.page_count = 3
    extraction.summary.page_count = 3
    layout["result"]["page_count"] = 3

    p1_cells = [
        ["1.", "Introduction", "5"],
        ["2.", "Applicability", "6"],
        ["3.", "Definitions", "8"],
        ["4.", "General Description", "16"],
    ]
    p2_cells = [
        ["5.", "Programme Requirements", "20"],
        ["5.1", "Board of Directors", "20"],
        ["5.2", "Senior Management", "22"],
        ["5.3", "Compliance Officer", "23"],
    ]
    p3_cells = [
        ["PART\n6", "III: CUSTOMER DUE DILIGENCE\nCustomer Due Diligence", "30"],
        ["6.1", "Conducting CDD", "38"],
        ["6.2", "Enhanced CDD Measures", "40"],
        ["6.3", "Higher-Risk Countries", "42"],
    ]

    extraction.pages = [
        _make_page(1, [_text_block("p1-b0", 0, [50, 40, 300, 70], "CONTENTS", 16)], [TableExtraction(table_id="p1-t1", bbox=[70, 430, 530, 790], row_count=4, col_count=3, cells=p1_cells)]),
        _make_page(2, [], [TableExtraction(table_id="p2-t1", bbox=[72, 45, 532, 790], row_count=4, col_count=3, cells=p2_cells)]),
        _make_page(3, [], [TableExtraction(table_id="p3-t1", bbox=[71, 40, 531, 700], row_count=4, col_count=3, cells=p3_cells)]),
    ]
    extraction.summary.text_block_count = 1
    extraction.summary.table_count = 3
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "section-header", "textlines": [{"spans": [{"text": "CONTENTS"}]}]},
            _layout_table(70, 430, 530, 790, p1_cells),
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [_layout_table(72, 45, 532, 790, p2_cells)]},
        {"page_number": 3, "width": 600, "height": 800, "boxes": [_layout_table(71, 40, 531, 700, p3_cells)]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    p3_table = next(e for e in result.pages[2].elements if e.type == "table")
    assert p3_table.table is not None
    assert ["PART", "III: CUSTOMER DUE DILIGENCE", ""] in p3_table.table.cells
    assert ["6", "Customer Due Diligence", "30"] in p3_table.table.cells
    assert p3_cells[0] not in p3_table.table.cells

    assert len(result.tables) == 1
    assert result.tables[0].spans_multiple_pages is True
    assert result.tables[0].start_page == 1
    assert result.tables[0].end_page == 3


def test_toc_context_inheritance_stops_when_substantive_content_precedes_candidate_table():
    record, extraction, layout = _two_page_base()
    p1_cells = [
        ["1.", "Introduction", "5"],
        ["2.", "Applicability", "6"],
        ["3.", "Definitions", "8"],
        ["4.", "General Description", "16"],
    ]
    merged = ["PART\n5", "II: RISK-BASED APPROACH\nRisk-Based Approach", "25"]
    p2_cells = [
        merged,
        ["5.1", "Risk Assessment", "25"],
        ["5.2", "Risk Management", "26"],
        ["5.3", "Risk Profiling", "28"],
    ]
    extraction.pages = [
        _make_page(1, [_text_block("p1-b0", 0, [50, 40, 300, 70], "CONTENTS", 16)], [TableExtraction(table_id="p1-t1", bbox=[70, 430, 530, 790], row_count=4, col_count=3, cells=p1_cells)]),
        _make_page(2, [_text_block("p2-b0", 0, [70, 35, 350, 60], "APPENDIX A", 14)], [TableExtraction(table_id="p2-t1", bbox=[72, 80, 532, 720], row_count=4, col_count=3, cells=p2_cells)]),
    ]
    extraction.summary.text_block_count = 2
    extraction.summary.table_count = 2
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "section-header", "textlines": [{"spans": [{"text": "CONTENTS"}]}]},
            _layout_table(70, 430, 530, 790, p1_cells),
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0": 70, "y0": 35, "x1": 350, "y1": 60, "boxclass": "section-header", "textlines": [{"spans": [{"text": "APPENDIX A"}]}]},
            _layout_table(72, 80, 532, 720, p2_cells),
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    p2_table = next(e for e in result.pages[1].elements if e.type == "table")
    assert p2_table.table is not None
    assert merged in p2_table.table.cells
    assert ["PART", "II: RISK-BASED APPROACH", ""] not in p2_table.table.cells
    assert len(result.tables) == 2


def test_inherited_toc_context_repairs_only_the_continuing_top_table_on_the_page():
    record, extraction, layout = _two_page_base()
    p1_cells = [
        ["1.", "Introduction", "5"],
        ["2.", "Applicability", "6"],
        ["3.", "Definitions", "8"],
        ["4.", "General Description", "16"],
    ]
    top_merged = ["PART\n5", "II: RISK-BASED APPROACH\nRisk-Based Approach", "25"]
    top_cells = [
        top_merged,
        ["5.1", "Risk Assessment", "25"],
        ["5.2", "Risk Management", "26"],
        ["5.3", "Risk Profiling", "28"],
    ]
    lower_merged = ["GROUP\n9", "INTERNAL TEST SECTION\nUnrelated Entry", "70"]
    lower_cells = [
        lower_merged,
        ["9.1", "Unrelated A", "71"],
        ["9.2", "Unrelated B", "72"],
        ["9.3", "Unrelated C", "73"],
    ]
    extraction.pages = [
        _make_page(1, [_text_block("p1-b0", 0, [50, 40, 300, 70], "CONTENTS", 16)], [TableExtraction(table_id="p1-t1", bbox=[70, 430, 530, 790], row_count=4, col_count=3, cells=p1_cells)]),
        _make_page(2, [], [
            TableExtraction(table_id="p2-t1", bbox=[72, 45, 532, 360], row_count=4, col_count=3, cells=top_cells),
            TableExtraction(table_id="p2-t2", bbox=[72, 430, 532, 740], row_count=4, col_count=3, cells=lower_cells),
        ]),
    ]
    extraction.summary.text_block_count = 1
    extraction.summary.table_count = 3
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "section-header", "textlines": [{"spans": [{"text": "CONTENTS"}]}]},
            _layout_table(70, 430, 530, 790, p1_cells),
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            _layout_table(72, 45, 532, 360, top_cells),
            _layout_table(72, 430, 532, 740, lower_cells),
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    p2_tables = [e for e in result.pages[1].elements if e.type == "table"]
    assert len(p2_tables) == 2
    assert p2_tables[0].table is not None and p2_tables[1].table is not None
    assert top_merged not in p2_tables[0].table.cells
    assert ["PART", "II: RISK-BASED APPROACH", ""] in p2_tables[0].table.cells
    assert lower_merged in p2_tables[1].table.cells
    assert ["GROUP", "INTERNAL TEST SECTION", ""] not in p2_tables[1].table.cells


def test_toc_context_inheritance_stops_when_next_table_starts_too_low_on_page():
    record, extraction, layout = _two_page_base()
    p1_cells = [
        ["1.", "Introduction", "5"],
        ["2.", "Applicability", "6"],
        ["3.", "Definitions", "8"],
        ["4.", "General Description", "16"],
    ]
    merged = ["PART\n5", "II: RISK-BASED APPROACH\nRisk-Based Approach", "25"]
    p2_cells = [
        merged,
        ["5.1", "Risk Assessment", "25"],
        ["5.2", "Risk Management", "26"],
        ["5.3", "Risk Profiling", "28"],
    ]
    extraction.pages = [
        _make_page(1, [_text_block("p1-b0", 0, [50, 40, 300, 70], "CONTENTS", 16)], [TableExtraction(table_id="p1-t1", bbox=[70, 430, 530, 790], row_count=4, col_count=3, cells=p1_cells)]),
        _make_page(2, [], [TableExtraction(table_id="p2-t1", bbox=[72, 300, 532, 720], row_count=4, col_count=3, cells=p2_cells)]),
    ]
    extraction.summary.text_block_count = 1
    extraction.summary.table_count = 2
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "section-header", "textlines": [{"spans": [{"text": "CONTENTS"}]}]},
            _layout_table(70, 430, 530, 790, p1_cells),
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [_layout_table(72, 300, 532, 720, p2_cells)]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    p2_table = next(e for e in result.pages[1].elements if e.type == "table")
    assert p2_table.table is not None
    assert merged in p2_table.table.cells
    assert len(result.tables) == 2


def test_toc_context_inheritance_stops_when_table_geometry_is_incompatible():
    record, extraction, layout = _two_page_base()
    p1_cells = [
        ["1.", "Introduction", "5"],
        ["2.", "Applicability", "6"],
        ["3.", "Definitions", "8"],
        ["4.", "General Description", "16"],
    ]
    merged = ["PART\n5", "II: RISK-BASED APPROACH\nRisk-Based Approach", "25"]
    p2_cells = [
        merged,
        ["5.1", "Risk Assessment", "25"],
        ["5.2", "Risk Management", "26"],
        ["5.3", "Risk Profiling", "28"],
    ]
    extraction.pages = [
        _make_page(1, [_text_block("p1-b0", 0, [50, 40, 300, 70], "CONTENTS", 16)], [TableExtraction(table_id="p1-t1", bbox=[70, 430, 530, 790], row_count=4, col_count=3, cells=p1_cells)]),
        _make_page(2, [], [TableExtraction(table_id="p2-t1", bbox=[180, 45, 590, 720], row_count=4, col_count=3, cells=p2_cells)]),
    ]
    extraction.summary.text_block_count = 1
    extraction.summary.table_count = 2
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0": 50, "y0": 40, "x1": 300, "y1": 70, "boxclass": "section-header", "textlines": [{"spans": [{"text": "CONTENTS"}]}]},
            _layout_table(70, 430, 530, 790, p1_cells),
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [_layout_table(180, 45, 590, 720, p2_cells)]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    p2_table = next(e for e in result.pages[1].elements if e.type == "table")
    assert p2_table.table is not None
    assert merged in p2_table.table.cells
    assert len(result.tables) == 2


def test_semantic_v2_resolves_local_group_and_phrase_items_without_domain_rules():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.text = (
        "Operations Manual\n"
        "4.2 The inspection applies to the following equipment types:\n"
        "Equipment\n"
        "(a) Pumps;\n"
        "(b) Valves;\n"
        "(c) Sensors;"
    )
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Operations Manual", 22),
        _text_block("p1-b1", 1, [70, 110, 530, 145], "4.2 The inspection applies to the following equipment types:", 11),
        _text_block("p1-b2", 2, [105, 165, 240, 185], "Equipment", 12),
        _text_block("p1-b3", 3, [135, 205, 350, 225], "(a) Pumps;", 11),
        _text_block("p1-b4", 4, [135, 235, 350, 255], "(b) Valves;", 11),
        _text_block("p1-b5", 5, [135, 265, 350, 285], "(c) Sensors;", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Operations Manual"}]}]},
        {"x0":70,"y0":110,"x1":530,"y1":145,"boxclass":"list-item","textlines":[{"spans":[{"text":"4.2 The inspection applies to the following equipment types:"}]}]},
        {"x0":105,"y0":165,"x1":240,"y1":185,"boxclass":"section-header","textlines":[{"spans":[{"text":"Equipment"}]}]},
        {"x0":135,"y0":205,"x1":350,"y1":225,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Pumps;"}]}]},
        {"x0":135,"y0":235,"x1":350,"y1":255,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Valves;"}]}]},
        {"x0":135,"y0":265,"x1":350,"y1":285,"boxclass":"list-item","textlines":[{"spans":[{"text":"(c) Sensors;"}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    elements = result.pages[0].elements
    clause = next(item for item in elements if item.text.startswith("4.2"))
    group = next(item for item in elements if item.text == "Equipment")
    items = [item for item in elements if item.text.startswith("(")]

    assert clause.type == "clause"
    assert group.type == "group_header"
    assert group.layout_role == "section-header"
    assert group.heading_level is None
    assert [item.type for item in items] == ["list_item", "list_item", "list_item"]
    assert all(item.layout_role == "list-item" for item in items)
    assert all(item.classification is not None for item in [clause, group, *items])
    assert all(item.classification.selected_type == item.type for item in [clause, group, *items])
    assert any(
        relation.type == "introduces"
        and relation.source_element_id == clause.element_id
        and relation.target_element_id == group.element_id
        for relation in result.relationships
    )
    assert all(
        any(
            relation.type == "introduces"
            and relation.source_element_id == group.element_id
            and relation.target_element_id == item.element_id
            for relation in result.relationships
        )
        for item in items
    )
    assert not any(section.element_id == group.element_id for section in result.sections)


def test_semantic_v2_keeps_independent_enumerated_propositions_as_subclauses():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.text = (
        "Safety Standard\n"
        "5.2 The organization shall ensure:\n"
        "(a) the supervisor must approve the shutdown;\n"
        "(b) the technician shall record the result."
    )
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Safety Standard", 22),
        _text_block("p1-b1", 1, [70, 110, 530, 145], "5.2 The organization shall ensure:", 11),
        _text_block("p1-b2", 2, [105, 165, 530, 195], "(a) the supervisor must approve the shutdown;", 11),
        _text_block("p1-b3", 3, [105, 205, 530, 235], "(b) the technician shall record the result.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Safety Standard"}]}]},
        {"x0":70,"y0":110,"x1":530,"y1":145,"boxclass":"list-item","textlines":[{"spans":[{"text":"5.2 The organization shall ensure:"}]}]},
        {"x0":105,"y0":165,"x1":530,"y1":195,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) the supervisor must approve the shutdown;"}]}]},
        {"x0":105,"y0":205,"x1":530,"y1":235,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) the technician shall record the result."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [record.kind for record in result.clauses] == ["clause", "subclause", "subclause"]
    subclauses = [item for item in result.pages[0].elements if item.type == "subclause"]
    assert [item.subclause_marker for item in subclauses] == ["(a)", "(b)"]
    assert all(item.classification and item.classification.source == "sequence_resolver" for item in subclauses)
    assert all(any(alt.type == "list_item" for alt in item.classification.alternatives) for item in subclauses)


def test_semantic_v2_classification_metadata_is_backfilled_after_specialized_repairs():
    record, extraction, layout = _fixture()
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    for element in result.pages[0].elements:
        assert element.layout_role is not None
        assert element.classification is not None
        assert element.classification.selected_type == element.type
        assert 0.0 <= element.classification.confidence <= 1.0
        assert element.classification.source


def test_semantic_v2_validator_surfaces_orphan_group_headers_without_blocking_build():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Manual", 22),
        _text_block("p1-b1", 1, [90, 120, 260, 140], "Local label", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = 2
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Manual"}]}]},
        {"x0":90,"y0":120,"x1":260,"y1":140,"boxclass":"section-header","textlines":[{"spans":[{"text":"Local label"}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    # With no contextual sequence, the resolver remains conservative and keeps
    # this as a section header rather than inventing a local group relation.
    assert result.pages[0].elements[1].type == "section_header"
    assert not any("local group header" in warning for warning in result.warnings)


def test_semantic_v21_propagates_parallel_local_group_with_single_member():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.text = (
        "Device Guide\n"
        "4.2 Supported device categories include the following:\n"
        "Desktop devices\n"
        "(a) Workstations;\n"
        "(b) Laptops;\n"
        "Mobile devices\n"
        "(a) Tablets"
    )
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Device Guide", 22),
        _text_block("p1-b1", 1, [70, 110, 530, 145], "4.2 Supported device categories include the following:", 11),
        _text_block("p1-b2", 2, [105, 165, 240, 185], "Desktop devices", 12),
        _text_block("p1-b3", 3, [135, 205, 350, 225], "(a) Workstations;", 11),
        _text_block("p1-b4", 4, [135, 235, 350, 255], "(b) Laptops;", 11),
        _text_block("p1-b5", 5, [105, 285, 240, 305], "Mobile devices", 12),
        _text_block("p1-b6", 6, [135, 325, 350, 345], "(a) Tablets", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Device Guide"}]}]},
        {"x0":70,"y0":110,"x1":530,"y1":145,"boxclass":"list-item","textlines":[{"spans":[{"text":"4.2 Supported device categories include the following:"}]}]},
        {"x0":105,"y0":165,"x1":240,"y1":185,"boxclass":"section-header","textlines":[{"spans":[{"text":"Desktop devices"}]}]},
        {"x0":135,"y0":205,"x1":350,"y1":225,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Workstations;"}]}]},
        {"x0":135,"y0":235,"x1":350,"y1":255,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Laptops;"}]}]},
        {"x0":105,"y0":285,"x1":240,"y1":305,"boxclass":"section-header","textlines":[{"spans":[{"text":"Mobile devices"}]}]},
        {"x0":135,"y0":325,"x1":350,"y1":345,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Tablets"}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    elements = result.pages[0].elements
    clause = next(item for item in elements if item.text.startswith("4.2"))
    desktop = next(item for item in elements if item.text == "Desktop devices")
    mobile = next(item for item in elements if item.text == "Mobile devices")
    tablet = next(item for item in elements if item.text == "(a) Tablets")

    assert desktop.type == "group_header"
    assert mobile.type == "group_header"
    assert tablet.type == "list_item"
    assert mobile.classification is not None
    assert any("parallel previously-resolved local group" in item for item in mobile.classification.evidence)
    assert any(
        relation.type == "introduces"
        and relation.source_element_id == clause.element_id
        and relation.target_element_id == mobile.element_id
        for relation in result.relationships
    )
    assert any(
        relation.type == "introduces"
        and relation.source_element_id == mobile.element_id
        and relation.target_element_id == tablet.element_id
        for relation in result.relationships
    )
    assert not any(section.element_id == mobile.element_id for section in result.sections)


def test_semantic_v21_heading_scope_demotes_weak_empty_heading_before_strong_outline_heading():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.text = (
        "Service Guide\n"
        "Maintenance procedures\n"
        "Mechanical systems\n"
        "3.1 Technicians must isolate power before service."
    )
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Service Guide", 22),
        _text_block("p1-b1", 1, [72, 110, 300, 132], "Maintenance procedures", 12),
        _text_block("p1-b2", 2, [72, 150, 260, 172], "Mechanical systems", 12),
        _text_block("p1-b3", 3, [72, 195, 530, 230], "3.1 Technicians must isolate power before service.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = [[2, "Mechanical systems", 1]]
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Service Guide"}]}]},
        {"x0":72,"y0":110,"x1":300,"y1":132,"boxclass":"section-header","textlines":[{"spans":[{"text":"Maintenance procedures"}]}]},
        {"x0":72,"y0":150,"x1":260,"y1":172,"boxclass":"section-header","textlines":[{"spans":[{"text":"Mechanical systems"}]}]},
        {"x0":72,"y0":195,"x1":530,"y1":230,"boxclass":"list-item","textlines":[{"spans":[{"text":"3.1 Technicians must isolate power before service."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    elements = result.pages[0].elements
    local = next(item for item in elements if item.text == "Maintenance procedures")
    outline = next(item for item in elements if item.text == "Mechanical systems")
    clause = next(item for item in elements if item.text.startswith("3.1"))

    assert local.type == "group_header"
    assert local.heading_level is None
    assert local.classification is not None
    assert local.classification.source == "heading_scope_resolver"
    assert outline.type == "section_header"
    assert outline.heading_level_source == "pdf_toc"
    assert not any(section.element_id == local.element_id for section in result.sections)
    outline_section = next(section for section in result.sections if section.element_id == outline.element_id)
    assert clause.section_id == outline_section.section_id
    assert any(
        relation.type == "introduces"
        and relation.source_element_id == local.element_id
        and relation.target_element_id == outline.element_id
        for relation in result.relationships
    )


def test_semantic_v21_fresh_numbered_clause_blocks_false_cross_page_continuation():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Procedure Manual", 22),
        _text_block("p1-b1", 1, [70, 730, 540, 780], "2.4 Operators must record the completed inspection.", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [70, 35, 540, 75], "2.5 Supervisors must review the inspection record.", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = 3
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Procedure Manual"}]}]},
            {"x0":70,"y0":730,"x1":540,"y1":780,"boxclass":"list-item","textlines":[{"spans":[{"text":"2.4 Operators must record the completed inspection."}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":70,"y0":35,"x1":540,"y1":75,"boxclass":"list-item","textlines":[{"spans":[{"text":"2.5 Supervisors must review the inspection record."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    first = next(item for item in result.pages[0].elements if item.type == "clause")
    second = next(item for item in result.pages[1].elements if item.type == "clause")
    assert first.clause_number == "2.4"
    assert second.clause_number == "2.5"
    assert not any(
        relation.type == "continues"
        and relation.source_element_id == first.element_id
        and relation.target_element_id == second.element_id
        for relation in result.relationships
    )


def test_semantic_v21_classification_alternative_scores_fit_remaining_confidence_mass():
    from app.services.semantic.classifier import apply_classification

    record, extraction, layout = _fixture()
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    element = result.pages[0].elements[1]
    apply_classification(
        element,
        element.type,
        confidence=0.70,
        source="test_support_normalization",
        evidence=["synthetic support normalization check"],
        alternatives=[("group_header", 0.44), ("paragraph", 0.11)],
        mutate_type=False,
    )
    classification = element.classification
    assert classification is not None
    total = classification.confidence + sum(item.score for item in classification.alternatives)
    assert abs(total - 1.0) < 1e-9
    assert all(item.score <= 1.0 - classification.confidence + 1e-9 for item in classification.alternatives)
    assert [round(item.score, 2) for item in classification.alternatives] == [0.24, 0.06]


def test_semantic_v21_validator_warns_about_empty_same_level_section_scope():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Reference Manual", 22),
        _text_block("p1-b1", 1, [72, 110, 300, 132], "Installation", 12),
        _text_block("p1-b2", 2, [72, 150, 300, 172], "Operation", 12),
        _text_block("p1-b3", 3, [72, 195, 530, 230], "2.1 Operators must verify the status indicator.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = [[2, "Installation", 1], [2, "Operation", 1]]
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Reference Manual"}]}]},
        {"x0":72,"y0":110,"x1":300,"y1":132,"boxclass":"section-header","textlines":[{"spans":[{"text":"Installation"}]}]},
        {"x0":72,"y0":150,"x1":300,"y1":172,"boxclass":"section-header","textlines":[{"spans":[{"text":"Operation"}]}]},
        {"x0":72,"y0":195,"x1":530,"y1":230,"boxclass":"list-item","textlines":[{"spans":[{"text":"2.1 Operators must verify the status indicator."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    installation = next(item for item in result.pages[0].elements if item.text == "Installation")
    assert installation.type == "section_header"
    assert any("heading-scope review recommended" in warning for warning in result.warnings)


def test_semantic_v21_validator_warns_for_unowned_sequence_list_item():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Quick Guide", 22),
        _text_block("p1-b1", 1, [110, 140, 350, 165], "(a) Spare module", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Quick Guide"}]}]},
        {"x0":110,"y0":140,"x1":350,"y1":165,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Spare module"}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    item = next(element for element in result.pages[0].elements if element.text.startswith("(a)"))
    assert item.type == "list_item"
    assert item.classification is not None
    assert item.classification.confidence == 0.62
    assert any("hierarchy calibration" in evidence for evidence in item.classification.evidence)
    assert any("enumerated list item" in warning for warning in result.warnings)


def test_semantic_v22_promotes_large_centered_cover_text_to_title():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks[0] = _text_block(
        "p1-b0", 0, [140, 250, 500, 520],
        "COMPLEX DOCUMENT PROCESSING GUIDELINES", 24,
    )
    raw.text = raw.text.replace("Sample Report", "COMPLEX DOCUMENT PROCESSING GUIDELINES")
    layout["result"]["pages"][0]["boxes"][0] = {
        "x0": 140, "y0": 250, "x1": 500, "y1": 520,
        "boxclass": "text",
        "textlines": [{"spans": [{"text": "COMPLEX DOCUMENT PROCESSING GUIDELINES"}]}],
    }
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    cover = next(item for item in result.pages[0].elements if item.text == "COMPLEX DOCUMENT PROCESSING GUIDELINES")
    assert cover.type == "title"
    assert cover.role_source == "promoted_top_heading"


def test_semantic_v22_promotes_page_header_appendix_labels_and_builds_boundaries():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [450, 40, 550, 60], "APPENDIX A", 11),
        _text_block("p1-b1", 1, [70, 100, 500, 130], "Risk Assessment Guide", 14),
        _text_block("p1-b2", 2, [70, 160, 520, 200], "1.1 The guide applies to all systems.", 11),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [450, 40, 550, 60], "APPENDIX B", 11),
        _text_block("p2-b1", 1, [70, 100, 500, 130], "Control Measures", 14),
        _text_block("p2-b2", 2, [70, 160, 520, 200], "1.1 Controls must be documented.", 11),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = 6
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0":450,"y0":40,"x1":550,"y1":60,"boxclass":"page-header","textlines":[{"spans":[{"text":"APPENDIX A"}]}]},
            {"x0":70,"y0":100,"x1":500,"y1":130,"boxclass":"section-header","textlines":[{"spans":[{"text":"Risk Assessment Guide"}]}]},
            {"x0":70,"y0":160,"x1":520,"y1":200,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.1 The guide applies to all systems."}]}]},
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0":450,"y0":40,"x1":550,"y1":60,"boxclass":"page-header","textlines":[{"spans":[{"text":"APPENDIX B"}]}]},
            {"x0":70,"y0":100,"x1":500,"y1":130,"boxclass":"section-header","textlines":[{"spans":[{"text":"Control Measures"}]}]},
            {"x0":70,"y0":160,"x1":520,"y1":200,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.1 Controls must be documented."}]}]},
        ]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert [(item.label, item.start_page, item.end_page) for item in result.appendices] == [
        ("APPENDIX A", 1, 1), ("APPENDIX B", 2, 2)
    ]
    labels = [item for page in result.pages for item in page.elements if item.text in {"APPENDIX A", "APPENDIX B"}]
    assert all(item.type == "section_header" for item in labels)
    assert all(item.layout_role == "page-header" for item in labels)


def test_semantic_v22_numbered_step_heading_becomes_clause_when_it_has_no_deeper_numbered_family():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Procedure Guide", 22),
        _text_block("p1-b1", 1, [70, 110, 530, 145], "1.7 The process begins with preparation.", 11),
        _text_block("p1-b2", 2, [70, 170, 530, 205], "1.8 Step 1: Identify the responsible person", 11),
        _text_block("p1-b3", 3, [110, 230, 530, 270], "(a) The supervisor must verify the record.", 11),
        _text_block("p1-b4", 4, [70, 300, 530, 335], "1.9 Step 2: Confirm the result", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = 5
    extraction.summary.table_count = 0
    layout["result"]["toc"] = [[4, "1.8 Step 1: Identify the responsible person", 1], [4, "1.9 Step 2: Confirm the result", 1]]
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Procedure Guide"}]}]},
        {"x0":70,"y0":110,"x1":530,"y1":145,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.7 The process begins with preparation."}]}]},
        {"x0":70,"y0":170,"x1":530,"y1":205,"boxclass":"section-header","textlines":[{"spans":[{"text":"1.8 Step 1: Identify the responsible person"}]}]},
        {"x0":110,"y0":230,"x1":530,"y1":270,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) The supervisor must verify the record."}]}]},
        {"x0":70,"y0":300,"x1":530,"y1":335,"boxclass":"section-header","textlines":[{"spans":[{"text":"1.9 Step 2: Confirm the result"}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    step1 = next(item for item in result.pages[0].elements if item.text.startswith("1.8"))
    step2 = next(item for item in result.pages[0].elements if item.text.startswith("1.9"))
    assert step1.type == "clause" and step1.clause_number == "1.8"
    assert step2.type == "clause" and step2.clause_number == "1.9"


def test_semantic_v22_nested_roman_run_splits_from_outer_alpha_marker_by_indentation():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Procedure Guide", 22),
        _text_block("p1-b1", 1, [70, 110, 530, 145], "1.1 The assessment includes the following:", 11),
        _text_block("p1-b2", 2, [140, 155, 530, 185], "Such a situation can be observed, among others, where:", 11),
        _text_block("p1-b3", 3, [140, 195, 530, 230], "(i) The person has majority voting power; or", 11),
        _text_block("p1-b4", 4, [140, 240, 530, 275], "(ii) The person exercises appointment rights.", 11),
        _text_block("p1-b5", 5, [110, 300, 530, 350], "(d) The institution shall then carry out Step 2.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = 6
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Procedure Guide"}]}]},
        {"x0":70,"y0":110,"x1":530,"y1":145,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.1 The assessment includes the following:"}]}]},
        {"x0":140,"y0":155,"x1":530,"y1":185,"boxclass":"text","textlines":[{"spans":[{"text":"Such a situation can be observed, among others, where:"}]}]},
        {"x0":140,"y0":195,"x1":530,"y1":230,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) The person has majority voting power; or"}]}]},
        {"x0":140,"y0":240,"x1":530,"y1":275,"boxclass":"list-item","textlines":[{"spans":[{"text":"(ii) The person exercises appointment rights."}]}]},
        {"x0":110,"y0":300,"x1":530,"y1":350,"boxclass":"list-item","textlines":[{"spans":[{"text":"(d) The institution shall then carry out Step 2."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    i = next(item for item in result.pages[0].elements if item.text.startswith("(i)"))
    ii = next(item for item in result.pages[0].elements if item.text.startswith("(ii)"))
    d = next(item for item in result.pages[0].elements if item.text.startswith("(d)"))
    assert i.type == "list_item"
    assert ii.type == "list_item"
    assert d.type == "subclause"


def test_definition_items_accept_missing_space_after_markers():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.text = "Sample Report\n3. DEFINITIONS\nterm\nmeans items that:\n(a)first item;\n(b)second item;\n(c)third item."
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [72, 90, 250, 110], "3. DEFINITIONS", 14),
        _text_block("p1-b2", 2, [112, 150, 180, 170], "term", 11),
        _text_block("p1-b3", 3, [310, 150, 550, 190], "means items that:", 11),
        _text_block("p1-b4", 4, [310, 205, 550, 230], "(a)first item;", 11),
        _text_block("p1-b5", 5, [310, 240, 550, 265], "(b)second item;", 11),
        _text_block("p1-b6", 6, [310, 275, 550, 300], "(c)third item.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = 7
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":90,"x1":250,"y1":110,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":112,"y0":150,"x1":180,"y1":170,"boxclass":"text","textlines":[{"spans":[{"text":"term"}]}]},
        {"x0":310,"y0":150,"x1":550,"y1":190,"boxclass":"text","textlines":[{"spans":[{"text":"means items that:"}]}]},
        {"x0":310,"y0":205,"x1":550,"y1":230,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a)first item;"}]}]},
        {"x0":310,"y0":240,"x1":550,"y1":265,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b)second item;"}]}]},
        {"x0":310,"y0":275,"x1":550,"y1":300,"boxclass":"list-item","textlines":[{"spans":[{"text":"(c)third item."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    entry = next(item for item in result.definitions if item.term == "term")
    assert [item.marker for item in entry.items] == ["(a)", "(b)", "(c)"]


def _shared_text_block(block_id: str, number: int, pieces: list[tuple[str, list[float]]], size: float = 11.04) -> TextBlock:
    lines = []
    for text, bbox in pieces:
        span = TextSpan(text=text, bbox=bbox, font="TestFont", size=size)
        lines.append(TextLine(bbox=bbox, text=text, spans=[span]))
    bbox = [
        min(piece[1][0] for piece in pieces),
        min(piece[1][1] for piece in pieces),
        max(piece[1][2] for piece in pieces),
        max(piece[1][3] for piece in pieces),
    ]
    return TextBlock(
        block_id=block_id,
        number=number,
        bbox=bbox,
        text="\n".join(piece[0] for piece in pieces),
        lines=lines,
    )


def test_semantic_v23_merges_markerless_same_block_subclause_continuation_and_owns_nested_list():
    record, extraction, layout = _fixture()
    pieces = [
        ("(c) Shareholders may exercise control and have the power to take actions", [115, 250, 535, 300]),
        ("and make decisions for the entity. Such a situation can be observed, where:", [143, 305, 535, 330]),
    ]
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "1. TEST SECTION", 14),
        _text_block("p1-b2", 2, [70, 135, 530, 175], "1.8 Step 1: Identify the controlling person", 11.04),
        _shared_text_block("p1-b3", 3, pieces),
        _text_block("p1-b4", 4, [143, 350, 520, 375], "(i)The natural person has majority voting power; or", 11.04),
        _text_block("p1-b5", 5, [143, 385, 520, 410], "(ii)The natural person may appoint directors.", 11.04),
    ]
    extraction.pages = [_make_page(1, blocks)]
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"1. TEST SECTION"}]}]},
        {"x0":70,"y0":135,"x1":530,"y1":175,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.8 Step 1: Identify the controlling person"}]}]},
        {"x0":115,"y0":250,"x1":535,"y1":300,"boxclass":"list-item","textlines":[{"spans":[{"text":pieces[0][0]}]}]},
        {"x0":143,"y0":305,"x1":535,"y1":330,"boxclass":"list-item","textlines":[{"spans":[{"text":pieces[1][0]}]}]},
        {"x0":143,"y0":350,"x1":520,"y1":375,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i)The natural person has majority voting power; or"}]}]},
        {"x0":143,"y0":385,"x1":520,"y1":410,"boxclass":"list-item","textlines":[{"spans":[{"text":"(ii)The natural person may appoint directors."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    page = result.pages[0]
    subclause = next(item for item in page.elements if item.text.startswith("(c) Shareholders"))
    assert subclause.type == "subclause"
    assert "and make decisions for the entity" in subclause.text
    assert not any(item.text.startswith("and make decisions for the entity") for item in page.elements)
    assert subclause.source.stage3_block_ids == ["p1-b3"]
    assert len(subclause.source.stage3_line_ids) == 2

    roman = [item for item in page.elements if item.text.startswith(("(i)", "(ii)"))]
    assert all(item.type == "list_item" for item in roman)
    for item in roman:
        assert any(
            relation.type == "introduces"
            and relation.source_element_id == subclause.element_id
            and relation.target_element_id == item.element_id
            for relation in result.relationships
        )


def test_semantic_v23_merges_style_split_sentence_but_not_appendix_title():
    record, extraction, layout = _two_page_base()
    intro_a = "Regulation 3 of the Strategic Trade (United Nations Security Council Resolutions)"
    intro_b = "Regulations 2010 requires the following counter-proliferation financing measures:"
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [450, 40, 550, 60], "APPENDIX G", 11.04),
        _text_block("p2-b1", 1, [70, 80, 540, 125], "REGULATION 3 OF STRATEGIC TRADE REGULATIONS 2010", 11.04),
        _shared_text_block("p2-b2", 2, [(intro_a, [70, 150, 540, 165]), (intro_b, [70, 170, 540, 215])]),
        _text_block("p2-b3", 3, [70, 235, 530, 260], "(a)Freezing of relevant assets;", 11.04),
        _text_block("p2-b4", 4, [70, 270, 530, 295], "(b)Prohibition of restricted investment.", 11.04),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":450,"y0":40,"x1":550,"y1":60,"boxclass":"page-header","textlines":[{"spans":[{"text":"APPENDIX G"}]}]},
            {"x0":70,"y0":80,"x1":540,"y1":125,"boxclass":"section-header","textlines":[{"spans":[{"text":"REGULATION 3 OF STRATEGIC TRADE REGULATIONS 2010"}]}]},
            {"x0":70,"y0":150,"x1":540,"y1":165,"boxclass":"section-header","textlines":[{"spans":[{"text":intro_a}]}]},
            {"x0":70,"y0":170,"x1":540,"y1":215,"boxclass":"text","textlines":[{"spans":[{"text":intro_b}]}]},
            {"x0":70,"y0":235,"x1":530,"y1":260,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a)Freezing of relevant assets;"}]}]},
            {"x0":70,"y0":270,"x1":530,"y1":295,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b)Prohibition of restricted investment."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    page = result.pages[1]
    merged = next(item for item in page.elements if item.text.startswith(intro_a))
    assert merged.type == "paragraph"
    assert intro_b in merged.text
    assert merged.element_id not in {section.element_id for section in result.sections}
    assert next(item for item in page.elements if item.text == "APPENDIX G").type == "section_header"
    members = [item for item in page.elements if item.text.startswith(("(a)", "(b)"))]
    for item in members:
        assert any(
            relation.type == "introduces"
            and relation.source_element_id == merged.element_id
            and relation.target_element_id == item.element_id
            for relation in result.relationships
        )


def test_semantic_v23_parent_clause_tail_belongs_to_parent_after_embedded_list():
    record, extraction, layout = _fixture()
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "8.5 Higher-Risk Countries", 14),
        _text_block("p1-b2", 2, [70, 135, 530, 170], "8.5.3 For transactions with persons from countries identified by–", 11.04),
        _text_block("p1-b3", 3, [115, 190, 530, 220], "(a)the FATF as having strategic deficiencies; or", 11.04),
        _text_block("p1-b4", 4, [115, 230, 530, 260], "(b)the Government as having strategic deficiencies;", 11.04),
        _text_block("p1-b5", 5, [115, 275, 530, 315], "a reporting institution is required to assess the risk and conduct enhanced CDD.", 11.04),
    ]
    extraction.pages = [_make_page(1, blocks)]
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"8.5 Higher-Risk Countries"}]}]},
        {"x0":70,"y0":135,"x1":530,"y1":170,"boxclass":"list-item","textlines":[{"spans":[{"text":"8.5.3 For transactions with persons from countries identified by–"}]}]},
        {"x0":115,"y0":190,"x1":530,"y1":220,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a)the FATF as having strategic deficiencies; or"}]}]},
        {"x0":115,"y0":230,"x1":530,"y1":260,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b)the Government as having strategic deficiencies;"}]}]},
        {"x0":115,"y0":275,"x1":530,"y1":315,"boxclass":"text","textlines":[{"spans":[{"text":"a reporting institution is required to assess the risk and conduct enhanced CDD."}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    clause = next(item for item in result.pages[0].elements if item.text.startswith("8.5.3"))
    tail = next(item for item in result.pages[0].elements if item.text.startswith("a reporting institution"))
    members = [item for item in result.pages[0].elements if item.text.startswith(("(a)", "(b)"))]
    assert clause.type == "clause"
    assert all(item.type == "list_item" for item in members)
    assert any(
        relation.type == "belongs_to"
        and relation.source_element_id == tail.element_id
        and relation.target_element_id == clause.element_id
        for relation in result.relationships
    )


def test_semantic_v23_cross_page_nested_list_keeps_subclause_owner():
    record, extraction, layout = _two_page_base()
    p1 = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "1. TEST SECTION", 14),
        _text_block("p1-b2", 2, [70, 600, 530, 635], "1.9 Step 2: Identify the controlling person", 11.04),
        _text_block("p1-b3", 3, [115, 670, 530, 730], "(b) Such powers may be attained through other means, such as:", 11.04),
    ]
    p2 = [
        _text_block("p2-b0", 0, [143, 55, 530, 85], "(i) Reflecting dominant influence to appoint directors;", 11.04),
        _text_block("p2-b1", 1, [143, 95, 530, 125], "(ii) Having power of attorney over the entity.", 11.04),
    ]
    extraction.pages = [_make_page(1, p1), _make_page(2, p2)]
    extraction.summary.text_block_count = len(p1) + len(p2)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"1. TEST SECTION"}]}]},
            {"x0":70,"y0":600,"x1":530,"y1":635,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.9 Step 2: Identify the controlling person"}]}]},
            {"x0":115,"y0":670,"x1":530,"y1":730,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Such powers may be attained through other means, such as:"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":143,"y0":55,"x1":530,"y1":85,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) Reflecting dominant influence to appoint directors;"}]}]},
            {"x0":143,"y0":95,"x1":530,"y1":125,"boxclass":"list-item","textlines":[{"spans":[{"text":"(ii) Having power of attorney over the entity."}]}]},
        ]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    sub = next(item for item in result.pages[0].elements if item.text.startswith("(b) Such powers"))
    nested = [item for item in result.pages[1].elements if item.text.startswith(("(i)", "(ii)"))]
    assert sub.type == "subclause"
    assert all(item.type == "list_item" for item in nested)
    for item in nested:
        assert any(
            relation.type == "introduces"
            and relation.source_element_id == sub.element_id
            and relation.target_element_id == item.element_id
            for relation in result.relationships
        )


def test_semantic_v23_inherited_obligation_keeps_parallel_actions_as_subclauses():
    record, extraction, layout = _fixture()
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "7.2 Risk management", 14),
        _text_block("p1-b2", 2, [70, 135, 530, 165], "7.2.1 A reporting institution is required to–", 11.04),
        _text_block("p1-b3", 3, [115, 185, 530, 225], "(a)have policies and controls to manage the risk;", 11.04),
        _text_block("p1-b4", 4, [115, 235, 530, 275], "(b)monitor implementation of those controls; and", 11.04),
        _text_block("p1-b5", 5, [115, 285, 530, 325], "(c)take enhanced measures where higher risks are identified.", 11.04),
    ]
    extraction.pages = [_make_page(1, blocks)]
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"7.2 Risk management"}]}]},
        {"x0":70,"y0":135,"x1":530,"y1":165,"boxclass":"list-item","textlines":[{"spans":[{"text":"7.2.1 A reporting institution is required to–"}]}]},
        {"x0":115,"y0":185,"x1":530,"y1":225,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a)have policies and controls to manage the risk;"}]}]},
        {"x0":115,"y0":235,"x1":530,"y1":275,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b)monitor implementation of those controls; and"}]}]},
        {"x0":115,"y0":285,"x1":530,"y1":325,"boxclass":"list-item","textlines":[{"spans":[{"text":"(c)take enhanced measures where higher risks are identified."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    actions = [item for item in result.pages[0].elements if item.text.startswith(("(a)", "(b)", "(c)"))]
    assert len(actions) == 3
    assert all(item.type == "subclause" for item in actions)
    assert len({item.parent_clause_id for item in actions}) == 1


def test_semantic_v23_recognizes_spaced_alphanumeric_clause_number():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 100, 500, 130], "6 A. INTERNAL PROGRAMMES", 14),
        _text_block("p1-b2", 2, [70, 150, 530, 205], "6 A.1 A reporting institution shall adopt internal programmes and controls.", 11.04),
    ]
    raw.tables = []
    extraction.summary.text_block_count = 3
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":500,"y1":130,"boxclass":"section-header","textlines":[{"spans":[{"text":"6 A. INTERNAL PROGRAMMES"}]}]},
        {"x0":70,"y0":150,"x1":530,"y1":205,"boxclass":"list-item","textlines":[{"spans":[{"text":"6 A.1 A reporting institution shall adopt internal programmes and controls."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    clause = next(item for item in result.pages[0].elements if item.text.startswith("6 A.1"))
    assert clause.type == "clause"
    assert clause.clause_number == "6A.1"


def test_semantic_v23_appendix_descriptive_title_is_group_header_not_duplicate_section():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [450, 80, 550, 100], "APPENDIX F", 11.04),
        _text_block("p2-b1", 1, [70, 120, 540, 155], "Guidance on Counterparty Due Diligence", 13.0),
        _text_block("p2-b2", 2, [70, 185, 530, 210], "1.0 Introduction", 12.0),
        _text_block("p2-b3", 3, [70, 225, 530, 270], "1.1 This Guidance describes the recommended process.", 11.04),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":450,"y0":80,"x1":550,"y1":100,"boxclass":"page-header","textlines":[{"spans":[{"text":"APPENDIX F"}]}]},
            {"x0":70,"y0":120,"x1":540,"y1":155,"boxclass":"section-header","textlines":[{"spans":[{"text":"Guidance on Counterparty Due Diligence"}]}]},
            {"x0":70,"y0":185,"x1":530,"y1":210,"boxclass":"section-header","textlines":[{"spans":[{"text":"1.0 Introduction"}]}]},
            {"x0":70,"y0":225,"x1":530,"y1":270,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.1 This Guidance describes the recommended process."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    page = result.pages[1]
    appendix_label = next(item for item in page.elements if item.text == "APPENDIX F")
    appendix_title = next(item for item in page.elements if item.text == "Guidance on Counterparty Due Diligence")
    introduction = next(item for item in page.elements if item.text == "1.0 Introduction")

    assert appendix_label.type == "section_header"
    assert appendix_title.type == "group_header"
    assert appendix_title.element_id not in {section.element_id for section in result.sections}
    appendix = next(item for item in result.appendices if item.label == "APPENDIX F")
    assert appendix.title_element_id == appendix_title.element_id
    assert appendix.title == appendix_title.text
    assert introduction.type == "section_header"
    assert any(
        relation.type == "introduces"
        and relation.source_element_id == appendix_title.element_id
        and relation.target_element_id == introduction.element_id
        for relation in result.relationships
    )


def test_semantic_v23_same_block_short_local_heading_is_not_merged_into_paragraph():
    record, extraction, layout = _fixture()
    pieces = [
        ("Risk factors", [70, 140, 180, 160]),
        ("A reporting institution should consider the customer's risk profile.", [70, 165, 530, 195]),
    ]
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "1. TEST SECTION", 14),
        _shared_text_block("p1-b2", 2, pieces),
    ]
    extraction.pages = [_make_page(1, blocks)]
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"1. TEST SECTION"}]}]},
        {"x0":70,"y0":140,"x1":180,"y1":160,"boxclass":"section-header","textlines":[{"spans":[{"text":"Risk factors"}]}]},
        {"x0":70,"y0":165,"x1":530,"y1":195,"boxclass":"text","textlines":[{"spans":[{"text":pieces[1][0]}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    page = result.pages[0]
    assert any(item.text == "Risk factors" for item in page.elements)
    assert any(item.text.startswith("A reporting institution should consider") for item in page.elements)
    assert not any(
        item.text.startswith("Risk factors") and "A reporting institution should consider" in item.text
        for item in page.elements
    )


def test_semantic_v23_same_block_definition_term_and_body_are_not_merged_before_definition_recovery():
    record, extraction, layout = _fixture()
    pieces = [
        ("beneficiary", [110, 140, 190, 160]),
        ("means a natural or legal person entitled to receive a benefit.", [110, 165, 530, 195]),
    ]
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "3. DEFINITIONS", 14),
        _shared_text_block("p1-b2", 2, pieces),
    ]
    extraction.pages = [_make_page(1, blocks)]
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"3. DEFINITIONS"}]}]},
        {"x0":110,"y0":140,"x1":190,"y1":160,"boxclass":"text","textlines":[{"spans":[{"text":"beneficiary"}]}]},
        {"x0":110,"y0":165,"x1":530,"y1":195,"boxclass":"text","textlines":[{"spans":[{"text":pieces[1][0]}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    page = result.pages[0]
    # The continuity pass must not collapse these two source boxes. Specialized
    # definition reconstruction may refine their final roles later, but both
    # source texts must remain independently represented/provenanced.
    texts = [item.text for item in page.elements]
    assert any("beneficiary" in text.casefold() for text in texts)
    assert any("means a natural or legal person" in text.casefold() for text in texts)
    assert not any(
        text.casefold().startswith("beneficiary") and "means a natural or legal person" in text.casefold()
        for text in texts
    )


def test_semantic_v23_cascading_step_remains_subclause_when_it_introduces_nested_items():
    record, extraction, layout = _fixture()
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "8.1 Customer Due Diligence", 14),
        _text_block("p1-b2", 2, [70, 135, 530, 180], "8.1.11 A reporting institution is required to identify beneficial owners according to the following cascading steps:", 11.04),
        _text_block("p1-b3", 3, [115, 195, 530, 250], "(a) the identity of the natural person(s) who ultimately has a controlling ownership interest in a legal person. Where applicable, this includes identifying:", 11.04),
        _text_block("p1-b4", 4, [143, 265, 530, 300], "(i) shareholders with equity interest of more than twenty-five percent in a corporation; and", 11.04),
        _text_block("p1-b5", 5, [143, 310, 530, 345], "(ii) partners with equivalent controlling interests.", 11.04),
    ]
    extraction.pages = [_make_page(1, blocks)]
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"8.1 Customer Due Diligence"}]}]},
        {"x0":70,"y0":135,"x1":530,"y1":180,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[2].text}]}]},
        {"x0":115,"y0":195,"x1":530,"y1":250,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[3].text}]}]},
        {"x0":143,"y0":265,"x1":530,"y1":300,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[4].text}]}]},
        {"x0":143,"y0":310,"x1":530,"y1":345,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[5].text}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    clause = next(item for item in result.pages[0].elements if item.text.startswith("8.1.11"))
    outer = next(item for item in result.pages[0].elements if item.text.startswith("(a) the identity"))
    nested = [item for item in result.pages[0].elements if item.text.startswith(("(i)", "(ii)"))]
    assert clause.type == "clause"
    assert outer.type == "subclause"
    assert outer.parent_clause_id == clause.clause_id
    assert all(item.type == "list_item" for item in nested)
    for item in nested:
        assert any(
            relation.type == "introduces"
            and relation.source_element_id == outer.element_id
            and relation.target_element_id == item.element_id
            for relation in result.relationships
        )


def test_semantic_v231_appendix_title_membership_counts_as_resolved_group_scope():
    record, extraction, layout = _two_page_base()
    p1_blocks = [_text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22)]
    p2_blocks = [
        _text_block("p2-b0", 0, [450, 80, 550, 100], "APPENDIX A1", 11.04),
        _text_block("p2-b1", 1, [70, 120, 540, 150], "Control Measures in Accepting Third-Party Deposits", 13.0),
        _text_block("p2-b2", 2, [70, 170, 530, 195], "1.0 General", 12.0),
        _text_block("p2-b3", 3, [70, 215, 530, 260], "1.1 This Appendix sets out requirements on control measures.", 11.04),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":450,"y0":80,"x1":550,"y1":100,"boxclass":"page-header","textlines":[{"spans":[{"text":"APPENDIX A1"}]}]},
            {"x0":70,"y0":120,"x1":540,"y1":150,"boxclass":"section-header","textlines":[{"spans":[{"text":"Control Measures in Accepting Third-Party Deposits"}]}]},
            {"x0":70,"y0":170,"x1":530,"y1":195,"boxclass":"section-header","textlines":[{"spans":[{"text":"1.0 General"}]}]},
            {"x0":70,"y0":215,"x1":530,"y1":260,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.1 This Appendix sets out requirements on control measures."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    title = next(item for item in result.pages[1].elements if item.text == "Control Measures in Accepting Third-Party Deposits")
    assert title.type == "group_header"
    assert title.classification is not None
    assert title.classification.confidence >= 0.85
    assert any(
        relation.type == "belongs_to"
        and relation.source_element_id == title.element_id
        and relation.target_element_id == next(item for item in result.pages[1].elements if item.text == "APPENDIX A1").element_id
        for relation in result.relationships
    )
    assert not any("local group header(s) without an introduces relationship" in warning for warning in result.warnings)
    assert not any("low-confidence element(s)" in warning for warning in result.warnings)


def test_semantic_v231_continues_relation_prevents_false_detached_tail_warning():
    record, extraction, layout = _two_page_base()
    p1_blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "1. TEST SECTION", 14),
        _text_block("p1-b2", 2, [115, 650, 530, 785], "(iii) The due diligence results must be reviewed", 11.04),
    ]
    p2_blocks = [
        _text_block("p2-b0", 0, [115, 40, 220, 60], "periodically.", 11.04),
        _text_block("p2-b1", 1, [115, 85, 530, 130], "(iv) The institution may require compliance by contract.", 11.04),
    ]
    extraction.pages = [_make_page(1, p1_blocks), _make_page(2, p2_blocks)]
    extraction.summary.text_block_count = len(p1_blocks) + len(p2_blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"1. TEST SECTION"}]}]},
            {"x0":115,"y0":650,"x1":530,"y1":785,"boxclass":"list-item","textlines":[{"spans":[{"text":"(iii) The due diligence results must be reviewed"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":115,"y0":40,"x1":220,"y1":60,"boxclass":"text","textlines":[{"spans":[{"text":"periodically."}]}]},
            {"x0":115,"y0":85,"x1":530,"y1":130,"boxclass":"list-item","textlines":[{"spans":[{"text":"(iv) The institution may require compliance by contract."}]}]},
        ]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    left = next(item for item in result.pages[0].elements if item.text.startswith("(iii)"))
    tail = next(item for item in result.pages[1].elements if item.text == "periodically.")
    assert any(
        relation.type == "continues"
        and relation.source_element_id == left.element_id
        and relation.target_element_id == tail.element_id
        for relation in result.relationships
    )
    assert not any("paragraph tail(s)" in warning for warning in result.warnings)


def test_semantic_v231_form_headings_do_not_trigger_style_split_warning():
    record, extraction, layout = _fixture()
    pieces_a = [
        ("Match with Designated Person(s) (YES / NO) :", [70, 140, 360, 160]),
        ("If YES, please fill-up the details in the form below", [70, 165, 500, 185]),
    ]
    pieces_b = [
        ("Details of Capital Market Intermediary", [70, 220, 330, 240]),
        ("Name :\nContact Person :\nDesignation :\nReporting Date :", [70, 245, 430, 300]),
    ]
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "REPORTING UPON DETERMINATION", 14),
        _shared_text_block("p1-b2", 2, pieces_a),
        _shared_text_block("p1-b3", 3, pieces_b),
    ]
    extraction.pages = [_make_page(1, blocks)]
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"REPORTING UPON DETERMINATION"}]}]},
        {"x0":70,"y0":140,"x1":360,"y1":160,"boxclass":"section-header","textlines":[{"spans":[{"text":pieces_a[0][0]}]}]},
        {"x0":70,"y0":165,"x1":500,"y1":185,"boxclass":"text","textlines":[{"spans":[{"text":pieces_a[1][0]}]}]},
        {"x0":70,"y0":220,"x1":330,"y1":240,"boxclass":"section-header","textlines":[{"spans":[{"text":pieces_b[0][0]}]}]},
        {"x0":70,"y0":245,"x1":430,"y1":300,"boxclass":"text","textlines":[{"spans":[{"text":pieces_b[1][0]}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert not any("heading/paragraph pair(s)" in warning for warning in result.warnings)
    assert any(item.text.startswith("Match with Designated Person") for item in result.pages[0].elements)
    assert any(item.text == "Details of Capital Market Intermediary" for item in result.pages[0].elements)


def test_semantic_v231_paragraph_list_intro_survives_intervening_figure_fragments():
    record, extraction, layout = _fixture()
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 300, 115], "Examples", 14),
        _text_block("p1-b2", 2, [70, 140, 530, 165], "The ownership breakdown is as follows:", 11.04),
        _text_block("p1-b3", 3, [70, 180, 100, 195], "A)", 11.04),
        _text_block("p1-b4", 4, [100, 180, 500, 210], "Mr. W has a controlling ownership interest", 11.04),
        _text_block("p1-b5", 5, [70, 180, 500, 210], "A) Mr. W has a controlling ownership interest", 11.04),
        _text_block("p1-b6", 6, [70, 225, 500, 250], "B) Mr. Z does not have a controlling ownership interest", 11.04),
    ]
    extraction.pages = [_make_page(1, blocks)]
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":300,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"Examples"}]}]},
        {"x0":70,"y0":140,"x1":530,"y1":165,"boxclass":"text","textlines":[{"spans":[{"text":"The ownership breakdown is as follows:"}]}]},
        {"x0":70,"y0":180,"x1":100,"y1":195,"boxclass":"picture","textlines":[{"spans":[{"text":"A)"}]}]},
        {"x0":100,"y0":180,"x1":500,"y1":210,"boxclass":"picture","textlines":[{"spans":[{"text":"Mr. W has a controlling ownership interest"}]}]},
        {"x0":70,"y0":180,"x1":500,"y1":210,"boxclass":"list-item","textlines":[{"spans":[{"text":"A) Mr. W has a controlling ownership interest"}]}]},
        {"x0":70,"y0":225,"x1":500,"y1":250,"boxclass":"list-item","textlines":[{"spans":[{"text":"B) Mr. Z does not have a controlling ownership interest"}]}]},
    ]

    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    intro = next(item for item in result.pages[0].elements if item.text == "The ownership breakdown is as follows:")
    members = [item for item in result.pages[0].elements if item.type == "list_item" and item.text.startswith(("A)", "B)"))]
    assert len(members) == 2
    for member in members:
        assert any(
            relation.type == "introduces"
            and relation.source_element_id == intro.element_id
            and relation.target_element_id == member.element_id
            for relation in result.relationships
        )


def test_semantic_v24_toc_navigation_headings_do_not_create_body_sections():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [70, 40, 250, 65], "CONTENTS", 16),
        _text_block("p1-b1", 1, [70, 100, 500, 125], "PART II: RISK-BASED APPROACH", 12),
    ]
    raw.tables = []
    extraction.summary.text_block_count = 2
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":70,"y0":40,"x1":250,"y1":65,"boxclass":"section-header","textlines":[{"spans":[{"text":"CONTENTS"}]}]},
        {"x0":70,"y0":100,"x1":500,"y1":125,"boxclass":"section-header","textlines":[{"spans":[{"text":"PART II: RISK-BASED APPROACH"}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    assert result.sections == []
    part = next(item for item in result.pages[0].elements if item.text.startswith("PART II"))
    assert part.type == "unknown"
    assert "PART II" not in result.body_text


def test_semantic_v24_numbering_repairs_parent_when_heading_levels_disagree():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50,40,300,70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70,90,500,115], "PART II: RISK-BASED APPROACH APPLICATION", 14),
        _text_block("p1-b2", 2, [70,130,500,155], "7. RISK-BASED APPROACH APPLICATION", 13),
        _text_block("p1-b3", 3, [70,170,500,195], "7.1 ML/TF Risk assessment", 12),
        _text_block("p1-b4", 4, [70,210,500,235], "7.3 PF Risk assessment", 12),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    # Deliberately inconsistent bookmark coverage: 7.3 must still be recovered
    # from its numbering family rather than inheriting a wrong sibling level.
    layout["result"]["toc"] = [[2, "7. RISK-BASED APPROACH APPLICATION", 1], [3, "7.1 ML/TF Risk assessment", 1]]
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":500,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"PART II: RISK-BASED APPROACH APPLICATION"}]}]},
        {"x0":70,"y0":130,"x1":500,"y1":155,"boxclass":"section-header","textlines":[{"spans":[{"text":"7. RISK-BASED APPROACH APPLICATION"}]}]},
        {"x0":70,"y0":170,"x1":500,"y1":195,"boxclass":"section-header","textlines":[{"spans":[{"text":"7.1 ML/TF Risk assessment"}]}]},
        {"x0":70,"y0":210,"x1":500,"y1":235,"boxclass":"section-header","textlines":[{"spans":[{"text":"7.3 PF Risk assessment"}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    sec7 = next(section for section in result.sections if section.title.startswith("7. RISK"))
    sec71 = next(section for section in result.sections if section.title.startswith("7.1"))
    sec73 = next(section for section in result.sections if section.title.startswith("7.3"))
    assert sec71.parent_section_id == sec7.section_id
    assert sec73.parent_section_id == sec7.section_id
    assert sec73.level == sec71.level


def test_semantic_v24_note_is_local_callout_and_cannot_absorb_next_clause():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,90,500,115],"14 IDENTIFICATION AND DESIGNATION",14),
        _text_block("p1-b2",2,[70,140,530,175],"14.3 A reporting institution should maintain a database.",11),
        _text_block("p1-b3",3,[95,200,160,220],"Note:",11),
        _text_block("p1-b4",4,[95,230,530,260],"The updated list can be obtained from the relevant authority.",10),
        _text_block("p1-b5",5,[70,300,530,345],"14.4 A reporting institution must conduct checks on customer names.",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":500,"y1":115,"boxclass":"section-header","textlines":[{"spans":[{"text":"14 IDENTIFICATION AND DESIGNATION"}]}]},
        {"x0":70,"y0":140,"x1":530,"y1":175,"boxclass":"list-item","textlines":[{"spans":[{"text":"14.3 A reporting institution should maintain a database."}]}]},
        {"x0":95,"y0":200,"x1":160,"y1":220,"boxclass":"section-header","textlines":[{"spans":[{"text":"Note:"}]}]},
        {"x0":95,"y0":230,"x1":530,"y1":260,"boxclass":"text","textlines":[{"spans":[{"text":"The updated list can be obtained from the relevant authority."}]}]},
        {"x0":70,"y0":300,"x1":530,"y1":345,"boxclass":"list-item","textlines":[{"spans":[{"text":"14.4 A reporting institution must conduct checks on customer names."}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    note=next(item for item in result.pages[0].elements if item.text=="Note:")
    clause14_4=next(item for item in result.pages[0].elements if item.text.startswith("14.4"))
    assert note.type=="group_header"
    assert note.element_id not in {section.element_id for section in result.sections}
    assert not any(r.type=="introduces" and r.target_element_id==note.element_id for r in result.relationships)
    assert not any(r.type=="introduces" and r.source_element_id==note.element_id and r.target_element_id==clause14_4.element_id for r in result.relationships)


def test_semantic_v24_obligation_intro_generalizes_must_incorporate_the_following():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,100,530,140],"7.3.3 The risk assessment processes must incorporate the following:",11),
        _text_block("p1-b2",2,[110,160,530,190],"(a) Documenting the risk assessments and findings;",11),
        _text_block("p1-b3",3,[110,205,530,235],"(b) Considering all relevant risk factors;",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":530,"y1":140,"boxclass":"list-item","textlines":[{"spans":[{"text":"7.3.3 The risk assessment processes must incorporate the following:"}]}]},
        {"x0":110,"y0":160,"x1":530,"y1":190,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Documenting the risk assessments and findings;"}]}]},
        {"x0":110,"y0":205,"x1":530,"y1":235,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Considering all relevant risk factors;"}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    members=[item for item in result.pages[0].elements if item.text.startswith(("(a)","(b)"))]
    assert len(members)==2
    assert all(item.type=="subclause" for item in members)


def test_semantic_v24_marker_only_fragment_merges_with_same_row_content():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[140,180,520,205],"(ii) Not listed in jurisdictions identified in public statements;",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=2; extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":143,"y0":180,"x1":157,"y1":195,"boxclass":"list-item","textlines":[{"spans":[{"text":"(ii)"}]}]},
        {"x0":171,"y0":180,"x1":500,"y1":195,"boxclass":"list-item","textlines":[{"spans":[{"text":"Not listed in jurisdictions identified in public statements;"}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    matching=[item for item in result.pages[0].elements if "Not listed in jurisdictions" in item.text]
    assert len(matching)==1
    assert matching[0].text.startswith("(ii)")
    assert len(result.pages[0].elements)==2


def test_semantic_v24_wrapped_heading_fragments_merge_when_same_stage3_block():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[72,150,320,185],"Secretary General Ministry of Home Affairs",11),
        _text_block("p1-b2",2,[72,220,500,250],"Level 10, Complex D",10),
    ]
    raw.tables=[]; extraction.summary.text_block_count=3; extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":72,"y0":150,"x1":280,"y1":165,"boxclass":"section-header","textlines":[{"spans":[{"text":"Secretary General Ministry of Home"}]}]},
        {"x0":72,"y0":170,"x1":120,"y1":182,"boxclass":"section-header","textlines":[{"spans":[{"text":"Affairs"}]}]},
        {"x0":72,"y0":220,"x1":500,"y1":250,"boxclass":"text","textlines":[{"spans":[{"text":"Level 10, Complex D"}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    headings=[item for item in result.pages[0].elements if "Secretary General" in item.text]
    assert len(headings)==1
    assert "Home\nAffairs" in headings[0].text
    assert not any(item.text=="Affairs" for item in result.pages[0].elements)


def test_semantic_v24_complete_clause_does_not_continue_to_fresh_capitalized_paragraph():
    record, extraction, layout = _fixture()
    p1=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,700,530,770],"6.2 A reporting institution should direct customers to the authority.",11),
    ]
    p2=[_text_block("p2-b0",0,[70,45,530,90],"The contact point for the authority is:",11)]
    extraction.pages=[_make_page(1,p1),_make_page(2,p2)]
    extraction.summary.page_count=2; extraction.summary.text_block_count=3; extraction.summary.table_count=0
    layout["result"]["page_count"]=2; layout["result"]["toc"]=[]
    layout["result"]["pages"]=[
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":70,"y0":700,"x1":530,"y1":770,"boxclass":"list-item","textlines":[{"spans":[{"text":"6.2 A reporting institution should direct customers to the authority."}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":70,"y0":45,"x1":530,"y1":90,"boxclass":"text","textlines":[{"spans":[{"text":"The contact point for the authority is:"}]}]},
        ]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    source=next(item for item in result.pages[0].elements if item.text.startswith("6.2"))
    target=result.pages[1].elements[0]
    assert not any(r.type=="continues" and r.source_element_id==source.element_id and r.target_element_id==target.element_id for r in result.relationships)


def test_semantic_v24_bottom_paragraph_with_marker_and_small_font_is_footnote():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,150,530,190],"Main body paragraph.",11),
        _text_block("p1-b2",2,[45,710,555,755],"2 Refers to customers before the obligation became applicable.",9.2),
    ]
    raw.tables=[]; extraction.summary.text_block_count=3; extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":150,"x1":530,"y1":190,"boxclass":"text","textlines":[{"spans":[{"text":"Main body paragraph."}]}]},
        {"x0":45,"y0":710,"x1":555,"y1":755,"boxclass":"text","textlines":[{"spans":[{"text":"2 Refers to customers before the obligation became applicable."}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    foot=next(item for item in result.pages[0].elements if item.text.startswith("2 Refers"))
    assert foot.type=="footnote"


def test_semantic_v24_textual_picture_duplicates_are_suppressed_not_counted_as_figures():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,140,500,175],"The breakdown is as follows:",11),
        _text_block("p1-b2",2,[70,190,500,225],"A) Alpha member",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=3; extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":140,"x1":500,"y1":175,"boxclass":"text","textlines":[{"spans":[{"text":"The breakdown is as follows:"}]}]},
        {"x0":70,"y0":190,"x1":95,"y1":205,"boxclass":"picture","textlines":[{"spans":[{"text":"A)"}]}]},
        {"x0":100,"y0":190,"x1":500,"y1":225,"boxclass":"picture","textlines":[{"spans":[{"text":"Alpha member"}]}]},
        {"x0":70,"y0":192,"x1":500,"y1":225,"boxclass":"list-item","textlines":[{"spans":[{"text":"A) Alpha member"}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    assert result.summary.figure_count==0
    assert all(item.type!="figure" for item in result.pages[0].elements)
    assert sum(item.type=="list_item" and item.text.startswith("A)") for item in result.pages[0].elements)==1


def test_semantic_v24_unnumbered_appendix_sections_do_not_nest_from_fluctuating_toc_levels():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[70,40,250,65],"APPENDIX B",14),
        _text_block("p1-b1",1,[70,75,500,95],"Guidance on Appendix Topic",12),
        _text_block("p1-b2",2,[70,110,520,140],"1.1 Introductory appendix clause.",11),
        _text_block("p1-b3",3,[70,180,300,200],"Family Members",11),
        _text_block("p1-b4",4,[70,220,520,250],"1.3 First topic clause.",11),
        _text_block("p1-b5",5,[70,290,300,310],"Close Associates",11),
        _text_block("p1-b6",6,[70,330,520,360],"1.5 Second topic clause.",11),
        _text_block("p1-b7",7,[70,400,400,420],"Source of Information",11),
        _text_block("p1-b8",8,[70,440,520,470],"1.12 Third topic clause.",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[[3,"Family Members",1],[4,"Close Associates",1],[5,"Source of Information",1]]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":70,"y0":40,"x1":250,"y1":65,"boxclass":"section-header","textlines":[{"spans":[{"text":"APPENDIX B"}]}]},
        {"x0":70,"y0":75,"x1":500,"y1":95,"boxclass":"section-header","textlines":[{"spans":[{"text":"Guidance on Appendix Topic"}]}]},
        {"x0":70,"y0":110,"x1":520,"y1":140,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.1 Introductory appendix clause."}]}]},
        {"x0":70,"y0":180,"x1":300,"y1":200,"boxclass":"section-header","textlines":[{"spans":[{"text":"Family Members"}]}]},
        {"x0":70,"y0":220,"x1":520,"y1":250,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.3 First topic clause."}]}]},
        {"x0":70,"y0":290,"x1":300,"y1":310,"boxclass":"section-header","textlines":[{"spans":[{"text":"Close Associates"}]}]},
        {"x0":70,"y0":330,"x1":520,"y1":360,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.5 Second topic clause."}]}]},
        {"x0":70,"y0":400,"x1":400,"y1":420,"boxclass":"section-header","textlines":[{"spans":[{"text":"Source of Information"}]}]},
        {"x0":70,"y0":440,"x1":520,"y1":470,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.12 Third topic clause."}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    appendix=next(section for section in result.sections if section.title=="APPENDIX B")
    topics=[section for section in result.sections if section.title in {"Family Members","Close Associates","Source of Information"}]
    assert len(topics)==3
    assert all(section.parent_section_id==appendix.section_id for section in topics)

def test_semantic_v24_descriptive_phase_groups_own_nested_lists_without_clause_parent_corruption():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,100,530,140],"1.2 There are three phases in the process:",11),
        _text_block("p1-b2",2,[110,160,220,180],"(a) Phase 1",11),
        _text_block("p1-b3",3,[145,195,530,225],"(i) A reporting institution should identify the counterparty.",11),
        _text_block("p1-b4",4,[110,250,220,270],"(b) Phase 2",11),
        _text_block("p1-b5",5,[145,285,530,315],"(i) A reporting institution should assess eligibility.",11),
        _text_block("p1-b6",6,[145,325,530,355],"(ii) A reporting institution may document the result.",11),
        _text_block("p1-b7",7,[110,380,220,400],"(c) Phase 3",11),
        _text_block("p1-b8",8,[145,415,530,445],"(i) A reporting institution should review the relationship.",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":530,"y1":140,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.2 There are three phases in the process:"}]}]},
        {"x0":110,"y0":160,"x1":220,"y1":180,"boxclass":"section-header","textlines":[{"spans":[{"text":"(a) Phase 1"}]}]},
        {"x0":145,"y0":195,"x1":530,"y1":225,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) A reporting institution should identify the counterparty."}]}]},
        {"x0":110,"y0":250,"x1":220,"y1":270,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Phase 2"}]}]},
        {"x0":145,"y0":285,"x1":530,"y1":315,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) A reporting institution should assess eligibility."}]}]},
        {"x0":145,"y0":325,"x1":530,"y1":355,"boxclass":"list-item","textlines":[{"spans":[{"text":"(ii) A reporting institution may document the result."}]}]},
        {"x0":110,"y0":380,"x1":220,"y1":400,"boxclass":"section-header","textlines":[{"spans":[{"text":"(c) Phase 3"}]}]},
        {"x0":145,"y0":415,"x1":530,"y1":445,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) A reporting institution should review the relationship."}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    clause=next(item for item in result.pages[0].elements if item.text.startswith("1.2"))
    phases=[item for item in result.pages[0].elements if "Phase " in item.text]
    nested=[item for item in result.pages[0].elements if item.text.startswith("(i)") or item.text.startswith("(ii)")]
    assert len(phases)==3 and all(item.type=="list_item" for item in phases)
    assert all(item.type=="list_item" for item in nested)
    assert all(item.clause_id is None and item.parent_clause_id is None for item in nested)
    for phase in phases:
        assert any(r.type=="introduces" and r.source_element_id==clause.element_id and r.target_element_id==phase.element_id for r in result.relationships)
    phase1=next(item for item in phases if "Phase 1" in item.text)
    phase2=next(item for item in phases if "Phase 2" in item.text)
    phase3=next(item for item in phases if "Phase 3" in item.text)
    p1_child=next(item for item in nested if "identify the counterparty" in item.text)
    p2_children=[item for item in nested if "assess eligibility" in item.text or "document the result" in item.text]
    p3_child=next(item for item in nested if "review the relationship" in item.text)
    assert any(r.type=="introduces" and r.source_element_id==phase1.element_id and r.target_element_id==p1_child.element_id for r in result.relationships)
    assert all(any(r.type=="introduces" and r.source_element_id==phase2.element_id and r.target_element_id==child.element_id for r in result.relationships) for child in p2_children)
    assert any(r.type=="introduces" and r.source_element_id==phase3.element_id and r.target_element_id==p3_child.element_id for r in result.relationships)


def test_semantic_v24_numbered_heading_near_page_bottom_is_recovered_from_footer_role():
    record, extraction, layout = _fixture()
    p1 = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 120, 500, 145], "8.3 Enhanced CDD measures", 12),
        _text_block("p1-b2", 2, [72, 735, 430, 755], "8.4 Politically exposed persons (PEPs)", 11),
    ]
    p2 = [_text_block("p2-b0", 0, [72, 55, 530, 95], "8.4.1 The requirements also apply to family members.", 11)]
    extraction.pages = [_make_page(1, p1), _make_page(2, p2)]
    extraction.summary.page_count = 2
    extraction.summary.text_block_count = 4
    extraction.summary.table_count = 0
    layout["result"]["page_count"] = 2
    layout["result"]["toc"] = []
    layout["result"]["pages"] = [
        {"page_number": 1, "width": 600, "height": 800, "boxes": [
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":70,"y0":120,"x1":500,"y1":145,"boxclass":"section-header","textlines":[{"spans":[{"text":"8.3 Enhanced CDD measures"}]}]},
            {"x0":72,"y0":735,"x1":430,"y1":755,"boxclass":"page-footer","textlines":[{"spans":[{"text":"8.4Politically exposed persons (PEPs)"}]}]},
        ]},
        {"page_number": 2, "width": 600, "height": 800, "boxes": [
            {"x0":72,"y0":55,"x1":530,"y1":95,"boxclass":"list-item","textlines":[{"spans":[{"text":"8.4.1 The requirements also apply to family members."}]}]},
        ]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    heading = next(item for item in result.pages[0].elements if "Politically exposed" in item.text)
    assert heading.type == "section_header"
    assert heading.text.startswith("8.4 ")
    section = next(section for section in result.sections if section.element_id == heading.element_id)
    clause = next(item for item in result.pages[1].elements if item.text.startswith("8.4.1"))
    assert clause.type == "clause"
    assert clause.section_id == section.section_id


def test_semantic_v24_numeric_guidance_points_are_not_promoted_to_global_clauses():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50,40,300,70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70,120,530,150], "9.2.1 A reporting institution must provide information.", 11),
        _text_block("p1-b2", 2, [105,180,430,200], "Guidance for paragraph 9.2.1 (a)", 11),
        _text_block("p1-b3", 3, [120,220,530,260], "1. Accurate means the information has been verified.", 11),
        _text_block("p1-b4", 4, [70,310,530,350], "9.2.2 A reporting institution must submit the information securely.", 11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":120,"x1":530,"y1":150,"boxclass":"list-item","textlines":[{"spans":[{"text":"9.2.1 A reporting institution must provide information."}]}]},
        {"x0":105,"y0":180,"x1":430,"y1":200,"boxclass":"section-header","textlines":[{"spans":[{"text":"Guidance for paragraph 9.2.1 (a)"}]}]},
        {"x0":120,"y0":220,"x1":530,"y1":260,"boxclass":"list-item","textlines":[{"spans":[{"text":"1. Accurate means the information has been verified."}]}]},
        {"x0":70,"y0":310,"x1":530,"y1":350,"boxclass":"list-item","textlines":[{"spans":[{"text":"9.2.2 A reporting institution must submit the information securely."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    guidance = next(item for item in result.pages[0].elements if item.text.startswith("Guidance for"))
    point = next(item for item in result.pages[0].elements if item.text.startswith("1. Accurate"))
    fresh = next(item for item in result.pages[0].elements if item.text.startswith("9.2.2"))
    assert guidance.type == "group_header"
    assert point.type != "clause"
    assert point.clause_number is None
    assert fresh.type == "clause"
    assert any(r.type == "introduces" and r.source_element_id == guidance.element_id and r.target_element_id == point.element_id for r in result.relationships)
    assert not any(r.type == "introduces" and r.source_element_id == guidance.element_id and r.target_element_id == fresh.element_id for r in result.relationships)


def test_semantic_v24_guidance_sentence_items_do_not_inherit_previous_clause_parent():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50,40,300,70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70,120,530,150], "18.4 A reporting institution must reject the customer.", 11),
        _text_block("p1-b2", 2, [105,180,430,200], "Guidance for paragraph 18", 11),
        _text_block("p1-b3", 3, [120,220,530,275], "(a) Funds that are controlled indirectly by the designated person must be frozen.", 11),
        _text_block("p1-b4", 4, [120,290,530,345], "(b) The obligation continues until the person is delisted.", 11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":120,"x1":530,"y1":150,"boxclass":"list-item","textlines":[{"spans":[{"text":"18.4 A reporting institution must reject the customer."}]}]},
        {"x0":105,"y0":180,"x1":430,"y1":200,"boxclass":"section-header","textlines":[{"spans":[{"text":"Guidance for paragraph 18"}]}]},
        {"x0":120,"y0":220,"x1":530,"y1":275,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Funds that are controlled indirectly by the designated person must be frozen."}]}]},
        {"x0":120,"y0":290,"x1":530,"y1":345,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) The obligation continues until the person is delisted."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    clause = next(item for item in result.pages[0].elements if item.text.startswith("18.4"))
    guidance = next(item for item in result.pages[0].elements if item.text.startswith("Guidance for"))
    members = [item for item in result.pages[0].elements if item.text.startswith("(a)") or item.text.startswith("(b)")]
    assert guidance.type == "group_header"
    assert all(item.type == "list_item" for item in members)
    assert all(item.parent_clause_id is None for item in members)
    assert all(any(r.type == "introduces" and r.source_element_id == guidance.element_id and r.target_element_id == item.element_id for r in result.relationships) for item in members)
    assert not any(r.type == "parent_of" and r.source_element_id == clause.element_id and r.target_element_id in {item.element_id for item in members} for r in result.relationships)


def test_semantic_v24_appendix_topic_label_between_number_families_becomes_section_boundary():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0",0,[70,40,250,65],"APPENDIX D",14),
        _text_block("p1-b1",1,[70,90,520,120],"4.6 Previous topic clause.",11),
        _text_block("p1-b2",2,[70,155,300,175],"Reporting requirements",11),
        _text_block("p1-b3",3,[70,210,520,240],"5.1 Reporting starts here.",11),
        _text_block("p1-b4",4,[70,275,300,295],"False positives",11),
        _text_block("p1-b5",5,[70,330,520,360],"6.1 False-positive handling starts here.",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":70,"y0":40,"x1":250,"y1":65,"boxclass":"section-header","textlines":[{"spans":[{"text":"APPENDIX D"}]}]},
        {"x0":70,"y0":90,"x1":520,"y1":120,"boxclass":"list-item","textlines":[{"spans":[{"text":"4.6 Previous topic clause."}]}]},
        {"x0":70,"y0":155,"x1":300,"y1":175,"boxclass":"section-header","textlines":[{"spans":[{"text":"Reporting requirements"}]}]},
        {"x0":70,"y0":210,"x1":520,"y1":240,"boxclass":"list-item","textlines":[{"spans":[{"text":"5.1 Reporting starts here."}]}]},
        {"x0":70,"y0":275,"x1":300,"y1":295,"boxclass":"section-header","textlines":[{"spans":[{"text":"False positives"}]}]},
        {"x0":70,"y0":330,"x1":520,"y1":360,"boxclass":"list-item","textlines":[{"spans":[{"text":"6.1 False-positive handling starts here."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    appendix = next(section for section in result.sections if section.title == "APPENDIX D")
    reporting = next(section for section in result.sections if section.title == "Reporting requirements")
    falsepos = next(section for section in result.sections if section.title == "False positives")
    assert reporting.parent_section_id == appendix.section_id
    assert falsepos.parent_section_id == appendix.section_id
    c5 = next(item for item in result.pages[0].elements if item.text.startswith("5.1"))
    c6 = next(item for item in result.pages[0].elements if item.text.startswith("6.1"))
    assert c5.section_id == reporting.section_id
    assert c6.section_id == falsepos.section_id


def test_semantic_v24_text_layout_guidance_label_is_recovered_as_local_group_header():
    record, extraction, layout = _fixture()
    p1 = [
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,690,530,745],"7.1.4 The institution must document the assessment.",11),
    ]
    p2 = [
        _text_block("p2-b0",0,[95,50,500,70],"Guidance for paragraphs 7.1.1, 7.1.2, 7.1.3 and 7.1.4:",11),
        _text_block("p2-b1",1,[110,90,530,125],"(a) Consider the national risk assessment;",11),
        _text_block("p2-b2",2,[70,180,530,220],"7.1.5 A reporting institution must assess new products.",11),
    ]
    extraction.pages=[_make_page(1,p1),_make_page(2,p2)]
    extraction.summary.page_count=2; extraction.summary.text_block_count=5; extraction.summary.table_count=0
    layout["result"]["page_count"]=2; layout["result"]["toc"]=[]
    layout["result"]["pages"]=[
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":70,"y0":690,"x1":530,"y1":745,"boxclass":"list-item","textlines":[{"spans":[{"text":"7.1.4 The institution must document the assessment."}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":95,"y0":50,"x1":500,"y1":70,"boxclass":"text","textlines":[{"spans":[{"text":"Guidance for paragraphs 7.1.1, 7.1.2, 7.1.3 and 7.1.4:"}]}]},
            {"x0":110,"y0":90,"x1":530,"y1":125,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Consider the national risk assessment;"}]}]},
            {"x0":70,"y0":180,"x1":530,"y1":220,"boxclass":"list-item","textlines":[{"spans":[{"text":"7.1.5 A reporting institution must assess new products."}]}]},
        ]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    guidance=next(item for item in result.pages[1].elements if item.text.startswith("Guidance for"))
    assert guidance.type=="group_header"
    source=next(item for item in result.pages[0].elements if item.text.startswith("7.1.4"))
    assert not any(r.type=="continues" and r.source_element_id==source.element_id and r.target_element_id==guidance.element_id for r in result.relationships)


def test_semantic_v24_callout_resets_prior_subclause_marker_family():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,100,530,135],"18.2 The freezing of funds shall remain in effect until:",11),
        _text_block("p1-b2",2,[110,150,530,180],"(a) The person is delisted; or",11),
        _text_block("p1-b3",3,[110,190,530,230],"(b) The match is confirmed as a false positive.",11),
        _text_block("p1-b4",4,[100,260,500,280],"Guidance for False Positive under paragraph 18.2(b)",11),
        _text_block("p1-b5",5,[110,300,530,345],"(a) A reporting institution may forward queries to the authority.",11),
        _text_block("p1-b6",6,[110,355,530,400],"(b) Any query must include additional information.",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":530,"y1":135,"boxclass":"list-item","textlines":[{"spans":[{"text":"18.2 The freezing of funds shall remain in effect until:"}]}]},
        {"x0":110,"y0":150,"x1":530,"y1":180,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) The person is delisted; or"}]}]},
        {"x0":110,"y0":190,"x1":530,"y1":230,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) The match is confirmed as a false positive."}]}]},
        {"x0":100,"y0":260,"x1":500,"y1":280,"boxclass":"section-header","textlines":[{"spans":[{"text":"Guidance for False Positive under paragraph 18.2(b)"}]}]},
        {"x0":110,"y0":300,"x1":530,"y1":345,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) A reporting institution may forward queries to the authority."}]}]},
        {"x0":110,"y0":355,"x1":530,"y1":400,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Any query must include additional information."}]}]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    main_items=[item for item in result.pages[0].elements if item.text.startswith("(a) The person") or item.text.startswith("(b) The match")]
    guidance=next(item for item in result.pages[0].elements if item.text.startswith("Guidance for False"))
    guidance_items=[item for item in result.pages[0].elements if item.text.startswith("(a) A reporting") or item.text.startswith("(b) Any query")]
    assert all(item.type=="subclause" for item in main_items)
    assert guidance.type=="group_header"
    assert all(item.type=="list_item" and item.parent_clause_id is None for item in guidance_items)
    assert all(any(r.type=="introduces" and r.source_element_id==guidance.element_id and r.target_element_id==item.element_id for r in result.relationships) for item in guidance_items)


def test_semantic_v24_toc_inheritance_accepts_short_residual_table_fragment_and_suppresses_navigation_headings():
    record, extraction, layout = _two_page_base()
    p1_cells = [
        ["1.", "Introduction", "5"],
        ["2.", "Applicability", "6"],
        ["3.", "Definitions", "8"],
        ["4.", "General Description", "16"],
    ]
    p2_cells = [
        ["8.7", "Failure to Complete CDD", "44"],
        ["8.8", "Ongoing Due Diligence", "45"],
    ]
    p1_blocks=[_text_block("p1-b0",0,[50,40,300,70],"CONTENTS",16)]
    p2_blocks=[_text_block("p2-b0",0,[70,230,400,250],"PART IIIA: WIRE TRANSFER",12)]
    extraction.pages=[
        _make_page(1,p1_blocks,[TableExtraction(table_id="p1-t1",bbox=[70,430,530,790],row_count=4,col_count=3,cells=p1_cells)]),
        _make_page(2,p2_blocks,[TableExtraction(table_id="p2-t1",bbox=[72,45,532,180],row_count=2,col_count=3,cells=p2_cells)]),
    ]
    extraction.summary.text_block_count=2; extraction.summary.table_count=2
    layout["result"]["toc"]=[]
    layout["result"]["pages"]=[
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"section-header","textlines":[{"spans":[{"text":"CONTENTS"}]}]},
            _layout_table(70,430,530,790,p1_cells),
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            _layout_table(72,45,532,180,p2_cells),
            {"x0":70,"y0":230,"x1":400,"y1":250,"boxclass":"section-header","textlines":[{"spans":[{"text":"PART IIIA: WIRE TRANSFER"}]}]},
        ]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    nav=next(item for item in result.pages[1].elements if item.text=="PART IIIA: WIRE TRANSFER")
    assert nav.type=="unknown"
    assert nav.element_id not in {section.element_id for section in result.sections}


def test_semantic_v24_guidance_on_appendix_title_does_not_flatten_real_appendix_topics():
    record, extraction, layout = _two_page_base()
    p1=[_text_block("p1-b0",0,[50,30,300,60],"Sample Report",22)]
    p2=[
        _text_block("p2-b0",0,[430,80,550,100],"APPENDIX B",11),
        _text_block("p2-b1",1,[70,120,540,150],"Guidance on Politically Exposed Persons",13),
        _text_block("p2-b2",2,[70,175,530,210],"1.1 The requirements also extend to family members.",11),
        _text_block("p2-b3",3,[70,240,300,260],"Family Members of a PEP",11),
        _text_block("p2-b4",4,[70,285,530,320],"1.3 Family members are individuals related to a PEP.",11),
        _text_block("p2-b5",5,[70,350,300,370],"Close Associates of a PEP",11),
        _text_block("p2-b6",6,[70,395,530,430],"1.5 A close associate is an individual closely connected to a PEP.",11),
    ]
    extraction.pages=[_make_page(1,p1),_make_page(2,p2)]
    extraction.summary.page_count=2; extraction.summary.text_block_count=len(p1)+len(p2); extraction.summary.table_count=0
    layout["result"]["page_count"]=2; layout["result"]["toc"]=[]
    layout["result"]["pages"]=[
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":30,"x1":300,"y1":60,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":430,"y0":80,"x1":550,"y1":100,"boxclass":"page-header","textlines":[{"spans":[{"text":"APPENDIX B"}]}]},
            {"x0":70,"y0":120,"x1":540,"y1":150,"boxclass":"section-header","textlines":[{"spans":[{"text":"Guidance on Politically Exposed Persons"}]}]},
            {"x0":70,"y0":175,"x1":530,"y1":210,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.1 The requirements also extend to family members."}]}]},
            {"x0":70,"y0":240,"x1":300,"y1":260,"boxclass":"section-header","textlines":[{"spans":[{"text":"Family Members of a PEP"}]}]},
            {"x0":70,"y0":285,"x1":530,"y1":320,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.3 Family members are individuals related to a PEP."}]}]},
            {"x0":70,"y0":350,"x1":300,"y1":370,"boxclass":"section-header","textlines":[{"spans":[{"text":"Close Associates of a PEP"}]}]},
            {"x0":70,"y0":395,"x1":530,"y1":430,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.5 A close associate is an individual closely connected to a PEP."}]}]},
        ]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    title=next(item for item in result.pages[1].elements if item.text=="Guidance on Politically Exposed Persons")
    intro=next(item for item in result.pages[1].elements if item.text.startswith("1.1"))
    appendix=next(section for section in result.sections if section.title=="APPENDIX B")
    family=next(section for section in result.sections if section.title=="Family Members of a PEP")
    close=next(section for section in result.sections if section.title=="Close Associates of a PEP")
    assert title.type=="group_header"
    assert title.role_source=="semantic_appendix_title_scope"
    assert intro.type=="clause"
    assert family.parent_section_id==appendix.section_id
    assert close.parent_section_id==appendix.section_id

def test_semantic_v24_examples_of_ordinary_prose_is_not_mistaken_for_callout():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,95,500,120],"19 REPORTING REQUIREMENTS",14),
        _text_block("p1-b2",2,[95,150,500,170],"Guidance for paragraph 19",11),
        _text_block("p1-b3",3,[105,195,530,235],"Examples of changes to the frozen funds include changes in balance and account status.",10),
        _text_block("p1-b4",4,[70,285,530,325],"19.4 A reporting institution must keep the information updated.",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":95,"x1":500,"y1":120,"boxclass":"section-header","textlines":[{"spans":[{"text":"19 REPORTING REQUIREMENTS"}]}]},
        {"x0":95,"y0":150,"x1":500,"y1":170,"boxclass":"section-header","textlines":[{"spans":[{"text":"Guidance for paragraph 19"}]}]},
        {"x0":105,"y0":195,"x1":530,"y1":235,"boxclass":"text","textlines":[{"spans":[{"text":"Examples of changes to the frozen funds include changes in balance and account status."}]}]},
        {"x0":70,"y0":285,"x1":530,"y1":325,"boxclass":"list-item","textlines":[{"spans":[{"text":"19.4 A reporting institution must keep the information updated."}]}]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    examples=next(item for item in result.pages[0].elements if item.text.startswith("Examples of changes"))
    clause=next(item for item in result.pages[0].elements if item.text.startswith("19.4"))
    assert examples.type=="paragraph"
    assert clause.type=="clause"


def test_semantic_v24_callout_owns_prose_and_paragraph_owned_nested_list_until_fresh_clause():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,95,500,120],"14 IDENTIFICATION AND DESIGNATION",14),
        _text_block("p1-b2",2,[95,150,150,170],"Note:",11),
        _text_block("p1-b3",3,[105,195,530,225],"The following examples apply:",10),
        _text_block("p1-b4",4,[125,245,530,275],"(a) First illustrative measure;",10),
        _text_block("p1-b5",5,[125,290,530,320],"(b) Second illustrative measure.",10),
        _text_block("p1-b6",6,[70,370,530,410],"14.4 A reporting institution must conduct the next required check.",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":95,"x1":500,"y1":120,"boxclass":"section-header","textlines":[{"spans":[{"text":"14 IDENTIFICATION AND DESIGNATION"}]}]},
        {"x0":95,"y0":150,"x1":150,"y1":170,"boxclass":"section-header","textlines":[{"spans":[{"text":"Note:"}]}]},
        {"x0":105,"y0":195,"x1":530,"y1":225,"boxclass":"text","textlines":[{"spans":[{"text":"The following examples apply:"}]}]},
        {"x0":125,"y0":245,"x1":530,"y1":275,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) First illustrative measure;"}]}]},
        {"x0":125,"y0":290,"x1":530,"y1":320,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Second illustrative measure."}]}]},
        {"x0":70,"y0":370,"x1":530,"y1":410,"boxclass":"list-item","textlines":[{"spans":[{"text":"14.4 A reporting institution must conduct the next required check."}]}]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    note=next(item for item in result.pages[0].elements if item.text=="Note:")
    prose=next(item for item in result.pages[0].elements if item.text.startswith("The following examples"))
    members=[item for item in result.pages[0].elements if item.text.startswith(("(a)","(b)"))]
    clause=next(item for item in result.pages[0].elements if item.text.startswith("14.4"))
    assert any(r.type=="introduces" and r.source_element_id==note.element_id and r.target_element_id==prose.element_id for r in result.relationships)
    assert all(any(r.type=="introduces" and r.source_element_id==prose.element_id and r.target_element_id==item.element_id for r in result.relationships) for item in members)
    assert not any(r.type=="introduces" and r.source_element_id==note.element_id and r.target_element_id==clause.element_id for r in result.relationships)


def test_semantic_v24_cross_page_continuation_preserves_outer_list_owner_for_next_marker():
    record, extraction, layout = _two_page_base()
    p1=[
        _text_block("p1-b0",0,[50,30,300,60],"Sample Report",22),
        _text_block("p1-b1",1,[70,100,530,135],"1.2 There are three phases in the process:",11),
        _text_block("p1-b2",2,[110,160,250,180],"(a) Phase 1",11),
        _text_block("p1-b3",3,[143,195,530,225],"(i) Complete the first review.",11),
        _text_block("p1-b4",4,[110,250,250,270],"(b) Phase 2",11),
        _text_block("p1-b5",5,[143,285,530,315],"(i) Complete the second review.",11),
        _text_block("p1-b6",6,[110,630,250,650],"(c) Phase 3",11),
        _text_block("p1-b7",7,[143,690,530,760],"(iii) The due diligence results must be reviewed",11),
    ]
    p2=[
        _text_block("p2-b0",0,[171,45,300,65],"periodically.",11),
        _text_block("p2-b1",1,[143,90,530,130],"(iv) Repeat the assessment when material conditions change.",11),
    ]
    extraction.pages=[_make_page(1,p1),_make_page(2,p2)]
    extraction.summary.page_count=2; extraction.summary.text_block_count=len(p1)+len(p2); extraction.summary.table_count=0
    layout["result"]["page_count"]=2; layout["result"]["toc"]=[]
    layout["result"]["pages"]=[
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":30,"x1":300,"y1":60,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":70,"y0":100,"x1":530,"y1":135,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.2 There are three phases in the process:"}]}]},
            {"x0":110,"y0":160,"x1":250,"y1":180,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Phase 1"}]}]},
            {"x0":143,"y0":195,"x1":530,"y1":225,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) Complete the first review."}]}]},
            {"x0":110,"y0":250,"x1":250,"y1":270,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Phase 2"}]}]},
            {"x0":143,"y0":285,"x1":530,"y1":315,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) Complete the second review."}]}]},
            {"x0":110,"y0":630,"x1":250,"y1":650,"boxclass":"list-item","textlines":[{"spans":[{"text":"(c) Phase 3"}]}]},
            {"x0":143,"y0":690,"x1":530,"y1":760,"boxclass":"list-item","textlines":[{"spans":[{"text":"(iii) The due diligence results must be reviewed"}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":171,"y0":45,"x1":300,"y1":65,"boxclass":"text","textlines":[{"spans":[{"text":"periodically."}]}]},
            {"x0":143,"y0":90,"x1":530,"y1":130,"boxclass":"list-item","textlines":[{"spans":[{"text":"(iv) Repeat the assessment when material conditions change."}]}]},
        ]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    phase3=next(item for item in result.pages[0].elements if "Phase 3" in item.text)
    third=next(item for item in result.pages[0].elements if item.text.startswith("(iii)"))
    continuation=next(item for item in result.pages[1].elements if item.text=="periodically.")
    fourth=next(item for item in result.pages[1].elements if item.text.startswith("(iv)"))
    assert any(r.type=="continues" and r.source_element_id==third.element_id and r.target_element_id==continuation.element_id for r in result.relationships)
    assert any(r.type=="introduces" and r.source_element_id==phase3.element_id and r.target_element_id==fourth.element_id for r in result.relationships)


def test_semantic_v24_validator_accepts_clause_inside_descendant_of_matching_numbered_section():
    trace = CanonicalSourceTrace(layout_box_index=0, layout_box_class="section-header")
    parent_el = CanonicalElement(
        element_id="p1-e1", type="section_header", page_number=1, reading_order=0,
        document_order=0, bbox=[70,80,500,100], text="8.1 Customer Due Diligence",
        section_id="sec-1", source=trace,
    )
    child_el = CanonicalElement(
        element_id="p1-e2", type="section_header", page_number=1, reading_order=1,
        document_order=1, bbox=[70,120,500,140], text="Customer identification",
        section_id="sec-2", source=trace,
    )
    clause_el = CanonicalElement(
        element_id="p1-e3", type="clause", page_number=1, reading_order=2,
        document_order=2, bbox=[70,160,530,200], text="8.1.6 A reporting institution must identify the customer.",
        section_id="sec-2", clause_number="8.1.6", source=CanonicalSourceTrace(layout_box_index=2, layout_box_class="list-item"),
    )
    sections = [
        SectionRecord(section_id="sec-1", title="8.1 Customer Due Diligence", level=2, page_number=1, element_id="p1-e1", parent_section_id=None, level_source="numbering"),
        SectionRecord(section_id="sec-2", title="Customer identification", level=3, page_number=1, element_id="p1-e2", parent_section_id="sec-1", level_source="font_rank"),
    ]
    validation = validate_semantic_structure(elements=[parent_el, child_el, clause_el], sections=sections, relationships=[])
    assert validation.clause_section_mismatch_ids == []


def test_semantic_v24_merged_sequential_list_rows_are_split_before_semantic_resolution():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 105, 530, 140], "6D.4 The roles include the following:", 11),
        _text_block("p1-b2", 2, [110, 180, 530, 205], "(d) Timely reporting to the board of directors;", 11),
        _text_block("p1-b3", 3, [110, 220, 530, 265], "(e) All employees are aware of the AML/CFT measures;", 11),
        _text_block("p1-b4", 4, [110, 285, 530, 315], "(f) Internal reports are evaluated;", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":105,"x1":530,"y1":140,"boxclass":"list-item","textlines":[{"spans":[{"text":"6D.4 The roles include the following:"}]}]},
        {"x0":110,"y0":180,"x1":530,"y1":265,"boxclass":"list-item","textlines":[
            {"spans":[{"text":"(d) Timely reporting to the board of directors;"}]},
            {"spans":[{"text":"(e) All employees are aware of the AML/CFT measures;"}]},
        ]},
        {"x0":110,"y0":285,"x1":530,"y1":315,"boxclass":"list-item","textlines":[{"spans":[{"text":"(f) Internal reports are evaluated;"}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    members = [item for item in result.pages[0].elements if item.text.startswith(("(d)", "(e)", "(f)"))]
    assert [item.text[:3] for item in members] == ["(d)", "(e)", "(f)"]
    assert len(members) == 3
    assert all("\n(e)" not in item.text for item in members)


def test_semantic_v24_main_body_unnumbered_topic_between_same_clause_family_is_local_group():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50,40,300,70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70,95,500,120], "8.1 Customer Due Diligence", 14),
        _text_block("p1-b2", 2, [70,155,530,190], "8.1.19 Previous requirement.", 11),
        _text_block("p1-b3", 3, [72,225,430,245], "CDD requirements for clubs, societies or charities", 11),
        _text_block("p1-b4", 4, [70,285,530,325], "8.1.20 A reporting institution must conduct CDD.", 11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":95,"x1":500,"y1":120,"boxclass":"section-header","textlines":[{"spans":[{"text":"8.1 Customer Due Diligence"}]}]},
        {"x0":70,"y0":155,"x1":530,"y1":190,"boxclass":"list-item","textlines":[{"spans":[{"text":"8.1.19 Previous requirement."}]}]},
        {"x0":72,"y0":225,"x1":430,"y1":245,"boxclass":"section-header","textlines":[{"spans":[{"text":"CDD requirements for clubs, societies or charities"}]}]},
        {"x0":70,"y0":285,"x1":530,"y1":325,"boxclass":"list-item","textlines":[{"spans":[{"text":"8.1.20 A reporting institution must conduct CDD."}]}]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    outline=next(item for item in result.pages[0].elements if item.text.startswith("8.1 Customer"))
    topic=next(item for item in result.pages[0].elements if item.text.startswith("CDD requirements"))
    clause=next(item for item in result.pages[0].elements if item.text.startswith("8.1.20"))
    assert topic.type == "group_header"
    assert topic.element_id not in {section.element_id for section in result.sections}
    outline_section=next(section for section in result.sections if section.element_id==outline.element_id)
    assert clause.section_id == outline_section.section_id
    assert any(r.type=="introduces" and r.source_element_id==topic.element_id and r.target_element_id==clause.element_id for r in result.relationships)


def test_semantic_v24_paragraph_intro_owns_following_contact_label_not_stale_previous_clause():
    record, extraction, layout = _two_page_base()
    p1=[
        _text_block("p1-b0",0,[50,30,300,60],"Sample Report",22),
        _text_block("p1-b1",1,[70,690,530,750],"6.2 A reporting institution should direct its customers to the Ministry.",11),
    ]
    p2=[
        _text_block("p2-b0",0,[70,45,530,80],"The contact point for the Ministry is:",11),
        _text_block("p2-b1",1,[72,110,360,135],"Secretary General Ministry of Home Affairs",11),
        _text_block("p2-b2",2,[72,155,530,220],"Level 10, Complex D, Putrajaya",10),
    ]
    extraction.pages=[_make_page(1,p1),_make_page(2,p2)]
    extraction.summary.page_count=2; extraction.summary.text_block_count=len(p1)+len(p2); extraction.summary.table_count=0
    layout["result"]["page_count"]=2; layout["result"]["toc"]=[]
    layout["result"]["pages"]=[
        {"page_number":1,"width":600,"height":800,"boxes":[
            {"x0":50,"y0":30,"x1":300,"y1":60,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
            {"x0":70,"y0":690,"x1":530,"y1":750,"boxclass":"list-item","textlines":[{"spans":[{"text":"6.2 A reporting institution should direct its customers to the Ministry."}]}]},
        ]},
        {"page_number":2,"width":600,"height":800,"boxes":[
            {"x0":70,"y0":45,"x1":530,"y1":80,"boxclass":"text","textlines":[{"spans":[{"text":"The contact point for the Ministry is:"}]}]},
            {"x0":72,"y0":110,"x1":360,"y1":135,"boxclass":"section-header","textlines":[{"spans":[{"text":"Secretary General Ministry of Home Affairs"}]}]},
            {"x0":72,"y0":155,"x1":530,"y1":220,"boxclass":"text","textlines":[{"spans":[{"text":"Level 10, Complex D, Putrajaya"}]}]},
        ]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    clause=next(item for item in result.pages[0].elements if item.text.startswith("6.2"))
    intro=next(item for item in result.pages[1].elements if item.text.startswith("The contact point"))
    label=next(item for item in result.pages[1].elements if item.text.startswith("Secretary General"))
    assert label.type == "group_header"
    assert any(r.type=="introduces" and r.source_element_id==intro.element_id and r.target_element_id==label.element_id for r in result.relationships)
    assert not any(r.type=="introduces" and r.source_element_id==clause.element_id and r.target_element_id==label.element_id for r in result.relationships)
    assert not any(r.type=="continues" and r.source_element_id==clause.element_id and r.target_element_id==intro.element_id for r in result.relationships)


def test_semantic_v24_figure_boundary_closes_stale_clause_group_scope():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,100,530,135],"1.2 There are three phases:",11),
        _text_block("p1-b2",2,[70,180,530,210],"An overview is set out in Illustration 1 below.",11),
        _text_block("p1-b3",3,[70,360,530,390],"Updated Guidance for Risk-Based Approach",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":530,"y1":135,"boxclass":"list-item","textlines":[{"spans":[{"text":"1.2 There are three phases:"}]}]},
        {"x0":70,"y0":180,"x1":530,"y1":210,"boxclass":"text","textlines":[{"spans":[{"text":"An overview is set out in Illustration 1 below."}]}]},
        {"x0":90,"y0":235,"x1":510,"y1":335,"boxclass":"picture","textlines":[]},
        {"x0":70,"y0":360,"x1":530,"y1":390,"boxclass":"section-header","textlines":[{"spans":[{"text":"Updated Guidance for Risk-Based Approach"}]}]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    clause=next(item for item in result.pages[0].elements if item.text.startswith("1.2"))
    source=next(item for item in result.pages[0].elements if item.text.startswith("Updated Guidance"))
    assert not any(r.type=="introduces" and r.source_element_id==clause.element_id and r.target_element_id==source.element_id for r in result.relationships)


def test_semantic_v24_modal_earlier_in_paragraph_does_not_turn_descriptive_tail_into_subclauses():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50,40,300,70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70,100,530,160], "Where control is identified, the assessment should be recorded. Such a situation may be observed through:", 11),
        _text_block("p1-b2", 2, [110,185,530,220], "(i) personal connections to persons in positions of power", 11),
        _text_block("p1-b3", 3, [110,240,530,275], "(ii) participation in financing of enterprises", 11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":530,"y1":160,"boxclass":"text","textlines":[{"spans":[{"text":"Where control is identified, the assessment should be recorded. Such a situation may be observed through:"}]}]},
        {"x0":110,"y0":185,"x1":530,"y1":220,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) personal connections to persons in positions of power"}]}]},
        {"x0":110,"y0":240,"x1":530,"y1":275,"boxclass":"list-item","textlines":[{"spans":[{"text":"(ii) participation in financing of enterprises"}]}]},
    ]
    result=build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    members=[item for item in result.pages[0].elements if item.text.startswith(("(i)","(ii)"))]
    assert len(members)==2
    assert all(item.type=="list_item" for item in members)


def test_semantic_v24_required_to_obtain_following_information_stays_descriptive_list():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,100,530,155],"8.1.6 A reporting institution is required to identify a customer, by obtaining at least the following information:",11),
        _text_block("p1-b2",2,[110,180,530,205],"(a) Full name;",11),
        _text_block("p1-b3",3,[110,225,530,250],"(b) Residential address;",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":530,"y1":155,"boxclass":"list-item","textlines":[{"spans":[{"text":"8.1.6 A reporting institution is required to identify a customer, by obtaining at least the following information:"}]}]},
        {"x0":110,"y0":180,"x1":530,"y1":205,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Full name;"}]}]},
        {"x0":110,"y0":225,"x1":530,"y1":250,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Residential address;"}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    members=[item for item in result.pages[0].elements if item.text.startswith(("(a)","(b)"))]
    assert len(members)==2
    assert all(item.type=="list_item" for item in members)


def test_semantic_v24_long_sentence_heading_that_introduces_list_is_body_paragraph():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    intro="Regulation 3 requires the following counter-proliferation financing measures to be taken in relation to designated countries and persons:"
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,95,220,120],"APPENDIX G",14),
        _text_block("p1-b2",2,[70,190,530,255],intro,11),
        _text_block("p1-b3",3,[110,280,530,315],"(a) Freezing of funds and other financial assets;",11),
        _text_block("p1-b4",4,[110,335,530,370],"(b) Prohibition of restricted investment.",11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":95,"x1":220,"y1":120,"boxclass":"section-header","textlines":[{"spans":[{"text":"APPENDIX G"}]}]},
        {"x0":70,"y0":190,"x1":530,"y1":255,"boxclass":"section-header","textlines":[{"spans":[{"text":intro}]}]},
        {"x0":110,"y0":280,"x1":530,"y1":315,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) Freezing of funds and other financial assets;"}]}]},
        {"x0":110,"y0":335,"x1":530,"y1":370,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) Prohibition of restricted investment."}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    intro_el=next(item for item in result.pages[0].elements if item.text.startswith("Regulation 3 requires"))
    assert intro_el.type=="paragraph"
    assert intro_el.element_id not in {section.element_id for section in result.sections}


def test_semantic_v24_duplicate_textual_picture_shell_is_removed_after_provenance_merge():
    record, extraction, layout = _fixture()
    raw=extraction.pages[0]
    text="A) Mr. W has 40% ownership of Company A and is a beneficial owner"
    raw.blocks=[
        _text_block("p1-b0",0,[50,40,300,70],"Sample Report",22),
        _text_block("p1-b1",1,[70,180,530,215],text,11),
    ]
    raw.tables=[]; extraction.summary.text_block_count=len(raw.blocks); extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":95,"y0":180,"x1":500,"y1":215,"boxclass":"picture","textlines":[{"spans":[{"text":"Mr. W has 40% ownership of Company A and is a beneficial owner"}]}]},
        {"x0":70,"y0":180,"x1":530,"y1":215,"boxclass":"list-item","textlines":[{"spans":[{"text":text}]}]},
    ]
    result=build_canonical_document(record=record,extraction=extraction,layout_artifact=layout)
    matching=[item for item in result.pages[0].elements if "Mr. W has 40% ownership" in item.text]
    assert len(matching)==1
    assert matching[0].type=="list_item"
    assert result.summary.figure_count==0


def test_semantic_v24_outer_subclause_sequence_resumes_after_nested_roman_list():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    raw.blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 95, 530, 145], "8.1.23 A reporting institution must apply the following controls:", 11),
        _text_block("p1-b2", 2, [108, 165, 530, 220], "(c) For non face-to-face onboarding, a reporting institution must undertake one or more of the following measures:", 11),
        _text_block("p1-b3", 3, [143, 235, 530, 270], "(i) Request additional identification information;", 11),
        _text_block("p1-b4", 4, [143, 285, 530, 320], "(ii) Contact the customer through a verified channel.", 11),
        _text_block("p1-b5", 5, [108, 345, 530, 400], "(d) Where those measures fail, the reporting institution must initiate face-to-face verification.", 11),
        _text_block("p1-b6", 6, [108, 420, 530, 465], "(e) Sub-paragraphs (a) to (d) are not applicable to:", 11),
        _text_block("p1-b7", 7, [143, 485, 530, 520], "(i) Foreign PEPs;", 11),
        _text_block("p1-b8", 8, [143, 535, 530, 570], "(ii) Higher-risk jurisdictions.", 11),
        _text_block("p1-b9", 9, [108, 600, 530, 650], "(f) A reporting institution must document the outcome.", 11),
    ]
    raw.tables = []
    extraction.summary.text_block_count = len(raw.blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":95,"x1":530,"y1":145,"boxclass":"list-item","textlines":[{"spans":[{"text":"8.1.23 A reporting institution must apply the following controls:"}]}]},
        {"x0":108,"y0":165,"x1":530,"y1":220,"boxclass":"list-item","textlines":[{"spans":[{"text":"(c) For non face-to-face onboarding, a reporting institution must undertake one or more of the following measures:"}]}]},
        {"x0":143,"y0":235,"x1":530,"y1":270,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) Request additional identification information;"}]}]},
        {"x0":143,"y0":285,"x1":530,"y1":320,"boxclass":"list-item","textlines":[{"spans":[{"text":"(ii) Contact the customer through a verified channel."}]}]},
        {"x0":108,"y0":345,"x1":530,"y1":400,"boxclass":"list-item","textlines":[{"spans":[{"text":"(d) Where those measures fail, the reporting institution must initiate face-to-face verification."}]}]},
        {"x0":108,"y0":420,"x1":530,"y1":465,"boxclass":"list-item","textlines":[{"spans":[{"text":"(e) Sub-paragraphs (a) to (d) are not applicable to:"}]}]},
        {"x0":143,"y0":485,"x1":530,"y1":520,"boxclass":"list-item","textlines":[{"spans":[{"text":"(i) Foreign PEPs;"}]}]},
        {"x0":143,"y0":535,"x1":530,"y1":570,"boxclass":"list-item","textlines":[{"spans":[{"text":"(ii) Higher-risk jurisdictions."}]}]},
        {"x0":108,"y0":600,"x1":530,"y1":650,"boxclass":"list-item","textlines":[{"spans":[{"text":"(f) A reporting institution must document the outcome."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    outer = [item for item in result.pages[0].elements if item.text.startswith(("(c)", "(d)", "(e)", "(f)"))]
    assert len(outer) == 4
    assert all(item.type == "subclause" for item in outer)
    assert len({item.parent_clause_id for item in outer}) == 1
    inner = [item for item in result.pages[0].elements if item.bbox[0] >= 140 and item.text.startswith(("(i)", "(ii)"))]
    assert inner
    assert all(item.type == "list_item" for item in inner)


def test_semantic_v24_long_must_determine_following_intro_creates_subclauses():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    intro = "2.6 A reporting institution must conduct due diligence on third-party deposits to determine the following:"
    raw.blocks = [
        _text_block("p1-b0", 0, [50,40,300,70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70,100,530,155], intro, 11),
        _text_block("p1-b2", 2, [110,180,530,215], "(a) The identity of the third-party payor;", 11),
        _text_block("p1-b3", 3, [110,230,530,265], "(b) The relationship between the customer and the third-party payor;", 11),
        _text_block("p1-b4", 4, [110,280,530,315], "(c) The reason for making the deposit.", 11),
    ]
    raw.tables=[]
    extraction.summary.text_block_count=len(raw.blocks)
    extraction.summary.table_count=0
    layout["result"]["toc"]=[]
    layout["result"]["pages"][0]["boxes"]=[
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":100,"x1":530,"y1":155,"boxclass":"list-item","textlines":[{"spans":[{"text":intro}]}]},
        {"x0":110,"y0":180,"x1":530,"y1":215,"boxclass":"list-item","textlines":[{"spans":[{"text":"(a) The identity of the third-party payor;"}]}]},
        {"x0":110,"y0":230,"x1":530,"y1":265,"boxclass":"list-item","textlines":[{"spans":[{"text":"(b) The relationship between the customer and the third-party payor;"}]}]},
        {"x0":110,"y0":280,"x1":530,"y1":315,"boxclass":"list-item","textlines":[{"spans":[{"text":"(c) The reason for making the deposit."}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    parent = next(item for item in result.pages[0].elements if item.text.startswith("2.6 "))
    members = [item for item in result.pages[0].elements if item.text.startswith(("(a)","(b)","(c)"))]
    assert parent.type == "clause"
    assert len(members) == 3
    assert all(item.type == "subclause" for item in members)
    assert all(item.parent_clause_id == parent.clause_id for item in members)


def test_semantic_v25_descriptive_parallel_family_stays_list_when_one_member_introduces_nested_list():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 95, 530, 145], "1.1 The Guidelines are issued pursuant to the following:", 11),
        _text_block("p1-b2", 2, [108, 165, 530, 215], "(a) in relation to anti-money laundering legislation;", 11),
        _text_block("p1-b3", 3, [108, 230, 530, 300], "(b) in relation to proliferation financing legislation which provides the legal basis for implementation under the following instruments:", 11),
        _text_block("p1-b4", 4, [143, 320, 530, 350], "(i) Strategic Trade Act 2010;", 11),
        _text_block("p1-b5", 5, [143, 365, 530, 395], "(ii) Strategic Trade Regulations 2010.", 11),
    ]
    raw.blocks = blocks
    raw.tables = []
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":95,"x1":530,"y1":145,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[1].text}]}]},
        {"x0":108,"y0":165,"x1":530,"y1":215,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[2].text}]}]},
        {"x0":108,"y0":230,"x1":530,"y1":300,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[3].text}]}]},
        {"x0":143,"y0":320,"x1":530,"y1":350,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[4].text}]}]},
        {"x0":143,"y0":365,"x1":530,"y1":395,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[5].text}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    parent = next(item for item in result.pages[0].elements if item.text.startswith("1.1 "))
    outer = [item for item in result.pages[0].elements if item.text.startswith(("(a)", "(b)")) and item.bbox[0] < 130]
    assert parent.type == "clause"
    assert len(outer) == 2
    assert all(item.type == "list_item" for item in outer)
    second = next(item for item in outer if item.text.startswith("(b)"))
    nested = [item for item in result.pages[0].elements if item.bbox[0] >= 140 and item.text.startswith(("(i)", "(ii)"))]
    assert len(nested) == 2
    assert all(item.type == "list_item" for item in nested)
    for item in nested:
        assert any(
            relation.type == "introduces"
            and relation.source_element_id == second.element_id
            and relation.target_element_id == item.element_id
            for relation in result.relationships
        )


def test_semantic_v25_numbered_heading_clause_intro_resolves_before_enumerated_children():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 90, 530, 120], "7.3 PF Risk assessment", 14),
        _text_block("p1-b2", 2, [70, 145, 530, 170], "7.3.5 A reporting institution is required to:", 11),
        _text_block("p1-b3", 3, [108, 190, 530, 225], "(a) have policies and controls to manage the risk;", 11),
        _text_block("p1-b4", 4, [108, 240, 530, 275], "(b) monitor implementation of those policies and controls; and", 11),
        _text_block("p1-b5", 5, [108, 290, 530, 320], "(c) take commensurate measures to manage and mitigate the risks:", 11),
        _text_block("p1-b6", 6, [143, 340, 530, 390], "(i) where higher risks are identified, the institution must ensure enhanced controls are applied;", 11),
        _text_block("p1-b7", 7, [143, 405, 530, 455], "(ii) where lower risks are identified, the institution must ensure measures are commensurate with the risk.", 11),
    ]
    raw.blocks = blocks
    raw.tables = []
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":90,"x1":530,"y1":120,"boxclass":"section-header","textlines":[{"spans":[{"text":"7.3 PF Risk assessment"}]}]},
        {"x0":70,"y0":145,"x1":530,"y1":170,"boxclass":"section-header","textlines":[{"spans":[{"text":blocks[2].text}]}]},
        {"x0":108,"y0":190,"x1":530,"y1":225,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[3].text}]}]},
        {"x0":108,"y0":240,"x1":530,"y1":275,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[4].text}]}]},
        {"x0":108,"y0":290,"x1":530,"y1":320,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[5].text}]}]},
        {"x0":143,"y0":340,"x1":530,"y1":390,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[6].text}]}]},
        {"x0":143,"y0":405,"x1":530,"y1":455,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[7].text}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    parent = next(item for item in result.pages[0].elements if item.text.startswith("7.3.5"))
    assert parent.type == "clause"
    outer = [item for item in result.pages[0].elements if item.bbox[0] < 130 and item.text.startswith(("(a)", "(b)", "(c)"))]
    assert len(outer) == 3
    assert all(item.type == "subclause" for item in outer)
    assert all(item.parent_clause_id == parent.clause_id for item in outer)
    third = next(item for item in outer if item.text.startswith("(c)"))
    nested = [item for item in result.pages[0].elements if item.bbox[0] >= 140 and item.text.startswith(("(i)", "(ii)"))]
    assert len(nested) == 2
    # These are complete conditional obligations in their own right ("where
    # ... the institution must ensure ..."), not merely dependent verb/noun
    # phrases.  They remain subclauses even when the whole nested run happens
    # to fit on one page.  This keeps semantic type independent of pagination.
    assert all(item.type == "subclause" for item in nested)
    assert all(item.parent_clause_id == third.clause_id for item in nested)
    relation_pairs = {(rel.source_element_id, rel.target_element_id, rel.type) for rel in result.relationships}
    assert all((third.element_id, item.element_id, "parent_of") in relation_pairs for item in nested)


def test_semantic_v25_nested_dependent_run_keeps_relative_modal_member_in_list_family():
    record, extraction, layout = _fixture()
    raw = extraction.pages[0]
    blocks = [
        _text_block("p1-b0", 0, [50, 40, 300, 70], "Sample Report", 22),
        _text_block("p1-b1", 1, [70, 95, 530, 140], "8.1.23 A reporting institution must apply the following controls:", 11),
        _text_block("p1-b2", 2, [115, 160, 530, 210], "(c) For verification, a reporting institution must undertake one or more of the following measures:", 11),
        _text_block("p1-b3", 3, [143, 225, 530, 255], "(i) Requesting additional identification information;", 11),
        _text_block("p1-b4", 4, [143, 270, 530, 300], "(ii) Substantiating the information with an independent source;", 11),
        _text_block("p1-b5", 5, [143, 315, 530, 345], "(iii) Contacting the customer through a verified channel;", 11),
        _text_block("p1-b6", 6, [143, 360, 530, 390], "(iv) Requesting a nominal payment from the customer's own account; or", 11),
        _text_block("p1-b7", 7, [143, 405, 530, 455], "(v) Using biometric technologies which should be linked incontrovertibly to the customer.", 11),
        _text_block("p1-b8", 8, [115, 480, 530, 530], "(d) Where those measures fail, the reporting institution must initiate face-to-face verification.", 11),
    ]
    raw.blocks = blocks
    raw.tables = []
    extraction.summary.text_block_count = len(blocks)
    extraction.summary.table_count = 0
    layout["result"]["toc"] = []
    layout["result"]["pages"][0]["boxes"] = [
        {"x0":50,"y0":40,"x1":300,"y1":70,"boxclass":"title","textlines":[{"spans":[{"text":"Sample Report"}]}]},
        {"x0":70,"y0":95,"x1":530,"y1":140,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[1].text}]}]},
        {"x0":115,"y0":160,"x1":530,"y1":210,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[2].text}]}]},
        {"x0":143,"y0":225,"x1":530,"y1":255,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[3].text}]}]},
        {"x0":143,"y0":270,"x1":530,"y1":300,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[4].text}]}]},
        {"x0":143,"y0":315,"x1":530,"y1":345,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[5].text}]}]},
        {"x0":143,"y0":360,"x1":530,"y1":390,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[6].text}]}]},
        {"x0":143,"y0":405,"x1":530,"y1":455,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[7].text}]}]},
        {"x0":115,"y0":480,"x1":530,"y1":530,"boxclass":"list-item","textlines":[{"spans":[{"text":blocks[8].text}]}]},
    ]
    result = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    outer_c = next(item for item in result.pages[0].elements if item.text.startswith("(c)"))
    nested = [item for item in result.pages[0].elements if item.bbox[0] >= 140 and item.text.startswith(("(i)", "(ii)", "(iii)", "(iv)", "(v)"))]
    assert outer_c.type == "subclause"
    assert len(nested) == 5
    assert all(item.type == "list_item" for item in nested)
    for item in nested:
        assert any(
            relation.type == "introduces"
            and relation.source_element_id == outer_c.element_id
            and relation.target_element_id == item.element_id
            for relation in result.relationships
        )
    outer_d = next(item for item in result.pages[0].elements if item.text.startswith("(d)"))
    assert outer_d.type == "subclause"
    assert outer_d.parent_clause_id == outer_c.parent_clause_id


def _canonical_test_element(element_id, type_, page, order, bbox, text, *, table=None, definition_entry_id=None):
    return CanonicalElement(
        element_id=element_id,
        type=type_,
        page_number=page,
        reading_order=order,
        document_order=order,
        bbox=bbox,
        text=text,
        definition_entry_id=definition_entry_id,
        role_source="test",
        table=table,
        source=CanonicalSourceTrace(layout_box_index=order, layout_box_class="text"),
    )


def test_regression_clause_suffix_letter_is_preserved_without_consuming_prose_initial():
    from app.services.canonical import _extract_clause_number, _normalize_structural_text
    from app.services.semantic.features import extract_clause_number

    assert _normalize_structural_text("11.6A A reporting institution is required") == "11.6A A reporting institution is required"
    assert _extract_clause_number("11.6A A reporting institution is required") == "11.6A"
    assert extract_clause_number("11.6A A reporting institution is required") == "11.6A"
    assert _extract_clause_number("3.1Unless otherwise defined") == "3.1"


def test_regression_repeated_cover_title_on_early_page_becomes_page_header():
    from app.services.canonical import _suppress_repeated_document_headers
    from app.schemas import StructuredPage

    title = _canonical_test_element("p1-e1", "title", 1, 0, [60, 60, 540, 120], "Sample Regulatory Guidelines")
    repeated = _canonical_test_element("p2-e1", "section_header", 2, 0, [60, 70, 540, 120], "Sample Regulatory Guidelines")
    pages = [
        StructuredPage(page_number=1, width=600, height=800, elements=[title], body_text=""),
        StructuredPage(page_number=2, width=600, height=800, elements=[repeated], body_text=""),
    ]
    elements = [title, repeated]
    assert _suppress_repeated_document_headers(elements, pages, title) == 1
    assert repeated.type == "page_header"
    assert repeated.heading_level is None


def test_regression_definition_rows_are_serialized_term_then_definition():
    from app.services.canonical import _reorder_definition_rows
    from app.schemas import StructuredPage

    t1 = _canonical_test_element("t1", "definition_term", 1, 0, [100, 100, 220, 120], "term one", definition_entry_id="def-1")
    t2 = _canonical_test_element("t2", "definition_term", 1, 1, [100, 150, 220, 170], "term two", definition_entry_id="def-2")
    d1 = _canonical_test_element("d1", "definition_text", 1, 2, [300, 100, 540, 130], "means first", definition_entry_id="def-1")
    d2 = _canonical_test_element("d2", "definition_text", 1, 3, [300, 150, 540, 180], "means second", definition_entry_id="def-2")
    page = StructuredPage(page_number=1, width=600, height=800, elements=[t1, t2, d1, d2], body_text="")
    elements = list(page.elements)
    assert _reorder_definition_rows(elements, [page]) == 1
    assert [item.element_id for item in page.elements] == ["t1", "d1", "t2", "d2"]


def test_regression_definition_spill_is_moved_to_next_row():
    from app.services.canonical import _repair_definition_row_boundaries
    from app.schemas import StructuredPage

    t1 = _canonical_test_element("t1", "definition_term", 1, 0, [100, 100, 220, 120], "UNSCR", definition_entry_id="def-1")
    d1 = _canonical_test_element("d1", "definition_text", 1, 1, [300, 100, 540, 180], "means United Nations Security Council Resolution. means any natural or legal person who is not", definition_entry_id="def-1")
    t2 = _canonical_test_element("t2", "definition_term", 1, 2, [100, 160, 250, 180], "Virtual Asset Service Provider", definition_entry_id="def-2")
    d2 = _canonical_test_element("d2", "definition_text", 1, 3, [300, 175, 540, 240], "covered elsewhere under the recommendations", definition_entry_id="def-2")
    page = StructuredPage(page_number=1, width=600, height=800, elements=[t1, d1, t2, d2], body_text="")
    elements = list(page.elements)
    assert _repair_definition_row_boundaries(elements, [page]) == 1
    assert d1.text == "means United Nations Security Council Resolution."
    assert d2.text.startswith("means any natural or legal person who is not covered elsewhere")


def test_regression_embedded_example_and_illustration_captions_are_split():
    from app.services.canonical import _split_embedded_captions
    from app.schemas import StructuredPage, CanonicalTable

    table = CanonicalTable(
        row_count=2,
        col_count=3,
        cells=[["Example 1:\nRisk Factor", "Examples", "Parameters"], ["Customer", "Example", "Value"]],
        markdown=None,
    )
    table_el = _canonical_test_element("tbl", "table", 1, 0, [80, 100, 520, 300], "Example 1:\nRisk Factor\tExamples\tParameters", table=table)
    intro = _canonical_test_element("intro", "paragraph", 1, 1, [70, 330, 500, 370], "An overview is shown below.\nIllustration 1:")
    fig = _canonical_test_element("fig", "figure", 1, 2, [70, 380, 520, 650], "")
    page = StructuredPage(page_number=1, width=600, height=800, elements=[table_el, intro, fig], body_text="")
    elements = list(page.elements)
    assert _split_embedded_captions(elements, [page]) == 2
    assert any(item.type == "caption" and item.text == "Example 1:" for item in page.elements)
    assert any(item.type == "caption" and item.text == "Illustration 1:" for item in page.elements)
    repaired_table = next(item for item in page.elements if item.element_id == "tbl")
    assert repaired_table.table.cells[0][0] == "Risk Factor"
    repaired_intro = next(item for item in page.elements if item.element_id == "intro")
    assert repaired_intro.text == "An overview is shown below."


def test_regression_secondary_toc_table_major_part_row_is_repaired_but_arbitrary_group_is_not():
    from app.services.canonical import _table_has_embedded_major_toc_heading, _repair_merged_toc_rows

    part_cells = [
        ["13.", "Compliance with Enforcement Orders", "58"],
        ["PART\n14.", "VII: COMBATING TERRORISM FINANCING\nIdentification and Designation", "59"],
        ["15.", "Definition and Interpretation", "61"],
        ["16.", "Maintenance of Sanctions List", "61"],
    ]
    group_cells = [
        ["GROUP\n9", "INTERNAL TEST SECTION\nUnrelated Entry", "70"],
        ["9.1", "Unrelated A", "71"],
        ["9.2", "Unrelated B", "72"],
        ["9.3", "Unrelated C", "73"],
    ]
    assert _table_has_embedded_major_toc_heading(part_cells)
    repaired, changed = _repair_merged_toc_rows(part_cells)
    assert changed and ["PART", "VII: COMBATING TERRORISM FINANCING", ""] in repaired
    assert not _table_has_embedded_major_toc_heading(group_cells)


def test_regression_article_a_after_decimal_clause_is_not_suffix():
    from app.services.canonical import _extract_clause_number, _normalize_structural_text
    from app.services.semantic.features import extract_clause_number, strip_clause_prefix

    cases = [
        ("11.8A reporting institution is required", "11.8", "A reporting institution is required"),
        ("7.1.1A reporting institution must take steps", "7.1.1", "A reporting institution must take steps"),
        ("10.1A reporting institution must keep records", "10.1", "A reporting institution must keep records"),
    ]
    for raw, expected_number, expected_prose in cases:
        normalized = _normalize_structural_text(raw)
        assert normalized.startswith(expected_number + " ")
        assert _extract_clause_number(normalized) == expected_number
        assert extract_clause_number(raw) == expected_number
        assert strip_clause_prefix(raw) == expected_prose

    # The real suffix case remains intact.
    assert _normalize_structural_text("11.6 A  A reporting institution is required") == "11.6A A reporting institution is required"
    assert _extract_clause_number("11.6A A reporting institution is required") == "11.6A"
    assert extract_clause_number("11.6A A reporting institution is required") == "11.6A"


def test_regression_toc_major_heading_merged_after_previous_entry_is_split():
    from app.services.canonical import _repair_merged_toc_rows, _table_has_embedded_major_toc_heading

    cells = [
        ["9", "Wire Transfer of Digital Assets", "47"],
        ["9.1", "General", "47"],
        ["9.2", "Ordering Institutions", "47"],
        ["9.3", "Beneficiary Institutions", "49"],
        ["9.4", "Sanctions Screening", "49"],
        ["9.5\nPART", "Identification and Due Diligence on Counterparty Virtual Asset Service\nProviders\nIV: RETENTION OF RECORDS", "50"],
        ["10.\nPART", "Record Keeping\nV: SUSPICIOUS TRANSACTIONS", "52"],
        ["11.", "Reporting of Suspicious Transactions", "54"],
        ["12.", "Confidentiality of Reporting", "57"],
    ]
    assert _table_has_embedded_major_toc_heading(cells)
    repaired, changed = _repair_merged_toc_rows(cells)
    assert changed
    assert ["9.5", "Identification and Due Diligence on Counterparty Virtual Asset Service\nProviders", "50"] in repaired
    assert ["PART", "IV: RETENTION OF RECORDS", ""] in repaired
    assert ["10.", "Record Keeping", "52"] in repaired
    assert ["PART", "V: SUSPICIOUS TRANSACTIONS", ""] in repaired
