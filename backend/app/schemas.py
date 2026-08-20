from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


PdfType = Literal["digital", "scanned", "mixed", "unknown"]
ValidationStatus = Literal["valid", "invalid"]
ExtractionStatus = Literal["not_started", "completed", "failed"]
StructureStatus = Literal["not_started", "completed", "failed"]
CanonicalElementType = Literal[
    "title",
    "subtitle",
    "document_metadata",
    "section_header",
    "clause",
    "subclause",
    "definition_term",
    "definition_text",
    "paragraph",
    "list_item",
    "table",
    "figure",
    "caption",
    "page_header",
    "page_footer",
    "footnote",
    "formula",
    "unknown",
]
HeadingLevelSource = Literal["pdf_toc", "numbering", "font_rank", "unknown"]
RelationType = Literal[
    "parent_of",
    "continues",
    "introduces",
    "explains",
    "caption_of",
    "source_for",
    "belongs_to",
]


class DocumentClassification(BaseModel):
    document_family: str
    pdf_type: PdfType | None = None
    page_count: int | None = None
    text_pages: int | None = None
    image_pages: int | None = None
    has_text_layer: bool | None = None
    has_images: bool | None = None
    encrypted: bool | None = None


class DocumentRecord(BaseModel):
    document_id: str
    original_filename: str
    stored_filename: str
    extension: str
    detected_mime_type: str | None = None
    size_bytes: int
    sha256: str
    validation_status: ValidationStatus
    validation_errors: list[str] = Field(default_factory=list)
    classification: DocumentClassification
    ingested_at: datetime
    extraction_status: ExtractionStatus = "not_started"
    extraction_error: str | None = None
    extracted_at: datetime | None = None
    structure_status: StructureStatus = "not_started"
    structure_error: str | None = None
    structured_at: datetime | None = None


class UploadResponse(BaseModel):
    document: DocumentRecord


class ExtractorInfo(BaseModel):
    name: str
    version: str
    settings: dict[str, str | bool | int | float] = Field(default_factory=dict)


class TextSpan(BaseModel):
    text: str
    bbox: list[float]
    origin: list[float] | None = None
    font: str | None = None
    size: float | None = None
    flags: int | None = None
    color: int | None = None
    ascender: float | None = None
    descender: float | None = None


class TextLine(BaseModel):
    bbox: list[float]
    text: str
    writing_mode: int | None = None
    direction: list[float] | None = None
    spans: list[TextSpan]


class TextBlock(BaseModel):
    block_id: str
    type: Literal["text"] = "text"
    number: int
    bbox: list[float]
    text: str
    lines: list[TextLine]


class ImageBlock(BaseModel):
    block_id: str
    type: Literal["image"] = "image"
    number: int
    bbox: list[float]
    width: int | None = None
    height: int | None = None
    extension: str | None = None
    colorspace: int | None = None
    bits_per_component: int | None = None
    xres: int | None = None
    yres: int | None = None
    encoded_size_bytes: int | None = None


class TableExtraction(BaseModel):
    table_id: str
    bbox: list[float]
    row_count: int
    col_count: int
    cells: list[list[str | None]]


class PageExtraction(BaseModel):
    page_number: int
    width: float
    height: float
    rotation: int
    text: str
    text_char_count: int
    blocks: list[TextBlock | ImageBlock]
    tables: list[TableExtraction]
    warnings: list[str] = Field(default_factory=list)


class ExtractionSummary(BaseModel):
    page_count: int
    text_char_count: int
    text_block_count: int
    image_block_count: int
    table_count: int


class DocumentExtraction(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    source_filename: str
    source_sha256: str
    source_pdf_type: PdfType | None = None
    extraction_mode: str
    extractor: ExtractorInfo
    summary: ExtractionSummary
    pages: list[PageExtraction]
    warnings: list[str] = Field(default_factory=list)
    extracted_at: datetime


class LayoutEngineInfo(BaseModel):
    name: str
    version: str
    settings: dict[str, str | bool | int | float] = Field(default_factory=dict)


class CanonicalTable(BaseModel):
    row_count: int
    col_count: int
    cells: list[list[str | None]] = Field(default_factory=list)
    markdown: str | None = None


class CanonicalSourceTrace(BaseModel):
    layout_box_index: int
    layout_box_class: str
    stage3_block_ids: list[str] = Field(default_factory=list)
    stage3_table_ids: list[str] = Field(default_factory=list)


class StructuralRelation(BaseModel):
    relation_id: str
    type: RelationType
    source_element_id: str
    target_element_id: str
    evidence: str


class CanonicalElement(BaseModel):
    element_id: str
    type: CanonicalElementType
    page_number: int
    reading_order: int
    document_order: int
    bbox: list[float]
    text: str = ""
    section_id: str | None = None
    definition_entry_id: str | None = None
    clause_number: str | None = None
    clause_id: str | None = None
    parent_clause_id: str | None = None
    subclause_marker: str | None = None
    logical_table_id: str | None = None
    figure_id: str | None = None
    appendix_id: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    heading_level_source: HeadingLevelSource | None = None
    dominant_font_size: float | None = None
    role_source: str = "layout"
    table: CanonicalTable | None = None
    source: CanonicalSourceTrace


class StructuredPage(BaseModel):
    page_number: int
    width: float
    height: float
    elements: list[CanonicalElement]
    body_text: str


class SectionRecord(BaseModel):
    section_id: str
    title: str
    level: int | None = Field(default=None, ge=1, le=6)
    page_number: int
    element_id: str
    parent_section_id: str | None = None
    level_source: HeadingLevelSource = "unknown"
    kind: Literal["section", "question", "appendix"] = "section"
    content_element_ids: list[str] = Field(default_factory=list)


class DefinitionSubItem(BaseModel):
    marker: str
    text: str


class DefinitionEntry(BaseModel):
    definition_id: str
    term: str
    section_id: str | None = None
    term_element_id: str | None = None
    source_table_element_id: str | None = None
    source_kind: Literal["layout_columns", "table_rows"] = "layout_columns"
    definition_text: str = ""
    items: list[DefinitionSubItem] = Field(default_factory=list)
    definition_element_ids: list[str] = Field(default_factory=list)
    start_page: int
    end_page: int
    spans_multiple_pages: bool = False
    continues_to_next_page: bool = False




class ClauseRecord(BaseModel):
    clause_id: str
    number: str
    kind: Literal["clause", "subclause"]
    element_id: str
    page_number: int
    section_id: str | None = None
    parent_clause_id: str | None = None


class AppendixRecord(BaseModel):
    appendix_id: str
    label: str
    label_element_id: str
    title: str | None = None
    title_element_id: str | None = None
    start_page: int
    end_page: int


class LogicalTable(BaseModel):
    logical_table_id: str
    fragment_element_ids: list[str]
    start_page: int
    end_page: int
    spans_multiple_pages: bool
    row_count: int
    col_count: int
    cells: list[list[str | None]] = Field(default_factory=list)
    section_id: str | None = None
    merge_source: Literal["single_fragment", "cross_page_geometry"] = "single_fragment"


class FigureRecord(BaseModel):
    figure_id: str
    element_id: str
    page_number: int
    section_id: str | None = None
    intro_element_ids: list[str] = Field(default_factory=list)
    caption_element_ids: list[str] = Field(default_factory=list)
    explanation_element_ids: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)

class StructureSummary(BaseModel):
    page_count: int
    element_count: int
    body_text_char_count: int
    section_count: int
    definition_count: int = 0
    clause_count: int = 0
    appendix_count: int = 0
    logical_table_count: int = 0
    figure_count: int = 0
    relation_count: int = 0
    element_counts: dict[str, int] = Field(default_factory=dict)


class StructuredDocument(BaseModel):
    schema_version: str = "1.4"
    document_id: str
    source_filename: str
    source_sha256: str
    source_extraction_schema_version: str
    layout_engine: LayoutEngineInfo
    title: str
    title_source: str
    subtitle: str | None = None
    subtitle_source: str | None = None
    outline_root_element_id: str | None = None
    metadata_element_ids: list[str] = Field(default_factory=list)
    summary: StructureSummary
    sections: list[SectionRecord]
    definitions: list[DefinitionEntry] = Field(default_factory=list)
    clauses: list[ClauseRecord] = Field(default_factory=list)
    appendices: list[AppendixRecord] = Field(default_factory=list)
    tables: list[LogicalTable] = Field(default_factory=list)
    figures: list[FigureRecord] = Field(default_factory=list)
    relationships: list[StructuralRelation] = Field(default_factory=list)
    pages: list[StructuredPage]
    body_text: str
    warnings: list[str] = Field(default_factory=list)
    structured_at: datetime


# Stage 4.5 — Human-in-the-Loop page-region corrections
CorrectionOperationType = Literal[
    "move_resize",
    "relabel",
    "split",
    "merge",
    "draw",
    "delete",
    "add_relationship",
    "remove_relationship",
]


class CorrectionElementSpec(BaseModel):
    element_id: str
    type: CanonicalElementType
    bbox: list[float] = Field(min_length=4, max_length=4)


class CorrectionRelationshipSpec(BaseModel):
    """Auditable relationship snapshot used by Stage 4.5 corrections.

    Page numbers are stored alongside element IDs so the correction JSON remains
    self-describing in the frontend even before the backend resolves the final
    canonical graph.
    """

    relation_id: str
    type: RelationType
    source_element_id: str
    target_element_id: str
    source_page_number: int = Field(ge=1)
    target_page_number: int = Field(ge=1)
    evidence: str = "manual relationship correction"


class CorrectionOperation(BaseModel):
    operation_id: str
    operation: CorrectionOperationType
    page_number: int = Field(ge=1)
    source_element_ids: list[str] = Field(default_factory=list)
    result_elements: list[CorrectionElementSpec] = Field(default_factory=list)
    relationships: list[CorrectionRelationshipSpec] = Field(default_factory=list)
    new_type: CanonicalElementType | None = None
    created_at: datetime


class SaveCorrectionsRequest(BaseModel):
    base_structured_at: datetime
    operations: list[CorrectionOperation] = Field(default_factory=list)


class CorrectionArtifact(BaseModel):
    schema_version: str = "1.1"
    document_id: str
    source_sha256: str
    base_structure_schema_version: str
    base_structured_at: datetime
    operations: list[CorrectionOperation] = Field(default_factory=list)
    updated_at: datetime


class ResolvedStructureArtifact(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    source_sha256: str
    base_structured_at: datetime
    correction_count: int
    resolved_at: datetime
    structure: StructuredDocument
    warnings: list[str] = Field(default_factory=list)


class SaveCorrectionsResponse(BaseModel):
    corrections: CorrectionArtifact
    resolved: ResolvedStructureArtifact
