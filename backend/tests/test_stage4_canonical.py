from datetime import datetime, timezone

from app.schemas import (
    DocumentClassification,
    DocumentExtraction,
    DocumentRecord,
    ExtractionSummary,
    ExtractorInfo,
    PageExtraction,
    TableExtraction,
    TextBlock,
    TextLine,
    TextSpan,
)
from app.services.canonical import build_canonical_document


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

    assert result.schema_version == "1.3"
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
    assert result.schema_version == "1.3"
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
