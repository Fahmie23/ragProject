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


def test_generic_cross_page_hierarchy_links_bullet_siblings_in_same_section():
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
    relation = next(r for r in result.relationships if r.type == "continues" and r.source_element_id == source.element_id and r.target_element_id == target.element_id)
    assert "bullet marker continues" in relation.evidence


def test_generic_cross_page_hierarchy_detects_nested_marker_child():
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
    relation = next(r for r in result.relationships if r.type == "continues" and r.source_element_id == source.element_id and r.target_element_id == target.element_id)
    assert "child hierarchy continuation" in relation.evidence


def test_generic_cross_page_hierarchy_links_numbered_siblings_under_same_section():
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
    relation = next(r for r in result.relationships if r.type == "continues" and r.source_element_id == source.element_id and r.target_element_id == target.element_id)
    assert "marker sequence advances" in relation.evidence


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
