from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator


PdfType = Literal["digital", "scanned", "mixed", "unknown"]
ValidationStatus = Literal["valid", "invalid"]
ExtractionStatus = Literal["not_started", "completed", "failed"]
StructureStatus = Literal["not_started", "completed", "failed"]
CanonicalElementType = Literal[
    "title",
    "subtitle",
    "document_metadata",
    "section_header",
    "group_header",
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
    span_id: str | None = None
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
    line_id: str | None = None
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
    schema_version: str = "1.1"
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
    stage3_line_ids: list[str] = Field(default_factory=list)
    stage3_span_ids: list[str] = Field(default_factory=list)
    stage3_table_ids: list[str] = Field(default_factory=list)


RelationProvenance = Literal["automatic", "manual", "derived"]


class StructuralRelation(BaseModel):
    relation_id: str
    type: RelationType
    source_element_id: str
    target_element_id: str
    evidence: str
    provenance: RelationProvenance = "automatic"


class SemanticTypeAlternative(BaseModel):
    type: CanonicalElementType
    score: float = Field(ge=0.0, le=1.0)


class SemanticClassification(BaseModel):
    selected_type: CanonicalElementType
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    evidence: list[str] = Field(default_factory=list)
    alternatives: list[SemanticTypeAlternative] = Field(default_factory=list)


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
    layout_role: str | None = None
    classification: SemanticClassification | None = None
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
    schema_version: str = "1.8"
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
    "link_definition",
    "unlink_definition",
    "assign_definition",
    "unassign_definition",
    "add_relationship",
    "remove_relationship",
    "span_rebuild",
    "set_structure",
]

CorrectionStructuralType = Literal["section_header", "clause", "subclause"]


class CorrectionStructureSpec(BaseModel):
    """Intent-level structural correction.

    Structural semantics are not ordinary labels: they carry canonical records
    and graph relationships.  The frontend submits the complete intended
    structure and the backend owns all derived record/relationship updates.
    """

    element_id: str
    type: CorrectionStructuralType
    section_id: str | None = None
    parent_section_id: str | None = None
    section_kind: Literal["section", "question"] = "section"
    heading_level: int | None = Field(default=None, ge=1, le=6)
    clause_id: str | None = None
    clause_number: str | None = None
    parent_clause_id: str | None = None
    subclause_marker: str | None = None


class IntegrityIssue(BaseModel):
    issue_id: str = ""
    code: str
    severity: Literal["error", "warning"]
    message: str
    element_ids: list[str] = Field(default_factory=list)
    record_ids: list[str] = Field(default_factory=list)
    requires_review: bool = False


class RelationshipIntegrityReport(BaseModel):
    status: Literal["pass", "fail", "unknown"]
    semantic_status: Literal["clear", "review_required", "blocked", "unknown"] = "unknown"
    errors: list[IntegrityIssue] = Field(default_factory=list)
    warnings: list[IntegrityIssue] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class RelationshipReviewState(BaseModel):
    status: Literal["not_reviewed", "needs_review", "approved", "blocked"] = "not_reviewed"
    approved_issue_ids: list[str] = Field(default_factory=list)
    pending_issue_ids: list[str] = Field(default_factory=list)
    approved_at: datetime | None = None
    note: str | None = None
    stage5_eligible: bool = False


class CorrectionElementSpec(BaseModel):
    element_id: str
    type: CanonicalElementType
    bbox: list[float] = Field(min_length=4, max_length=4)
    source_span_ids: list[str] = Field(default_factory=list)


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
    structure: CorrectionStructureSpec | None = None
    new_type: CanonicalElementType | None = None
    definition_id: str | None = None
    target_page_number: int | None = Field(default=None, ge=1)
    note: str | None = None
    created_at: datetime


class SaveCorrectionsRequest(BaseModel):
    base_structured_at: datetime
    operations: list[CorrectionOperation] = Field(default_factory=list)


class CorrectionArtifact(BaseModel):
    schema_version: str = "1.9"
    document_id: str
    source_sha256: str
    base_structure_schema_version: str
    base_structured_at: datetime
    operations: list[CorrectionOperation] = Field(default_factory=list)
    relationship_review: RelationshipReviewState = Field(default_factory=RelationshipReviewState)
    updated_at: datetime


class ResolvedStructureArtifact(BaseModel):
    schema_version: str = "1.5"
    document_id: str
    source_sha256: str
    base_structured_at: datetime
    correction_count: int
    resolved_at: datetime
    structure: StructuredDocument
    baseline_integrity: RelationshipIntegrityReport | None = None
    integrity: RelationshipIntegrityReport = Field(default_factory=lambda: RelationshipIntegrityReport(
        status="unknown",
        semantic_status="unknown",
        warnings=[IntegrityIssue(
            code="legacy_integrity_unchecked",
            severity="warning",
            message="This resolved artifact predates relationship-integrity validation. Re-validate corrections before relying on its graph status.",
            requires_review=True,
        )],
    ))
    review: RelationshipReviewState = Field(default_factory=RelationshipReviewState)
    warnings: list[str] = Field(default_factory=list)


class ValidateCorrectionsResponse(BaseModel):
    valid: bool
    resolved: ResolvedStructureArtifact | None = None
    errors: list[str] = Field(default_factory=list)


class SaveCorrectionsResponse(BaseModel):
    corrections: CorrectionArtifact
    resolved: ResolvedStructureArtifact


class ApproveRelationshipsRequest(BaseModel):
    base_structured_at: datetime
    correction_updated_at: datetime
    approved_issue_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class ApproveRelationshipsResponse(BaseModel):
    corrections: CorrectionArtifact
    resolved: ResolvedStructureArtifact


# Stage 5 — Retrieval preparation and semantic chunking
ChunkingStrategy = Literal["semantic_v1", "semantic_v2"]
CleaningAction = Literal["include", "context", "exclude"]


class RetrievalCleaningPolicy(BaseModel):
    exclude_page_headers: bool = True
    exclude_page_footers: bool = True
    exclude_margin_page_numbers: bool = True
    exclude_repeated_margin_text: bool = True
    deduplicate_overlapping_text: bool = True
    repeated_margin_min_pages: int = Field(default=3, ge=2, le=50)
    include_footnotes: bool = True
    include_document_metadata: bool = True
    include_figures_without_text: bool = False
    normalize_whitespace: bool = True
    # Conservative by default. Automatic dehyphenation can corrupt genuine
    # compounds such as ``anti-money`` when the source wraps at a line break.
    dehyphenate_line_breaks: bool = False


class ChunkingConfig(BaseModel):
    strategy: ChunkingStrategy = "semantic_v2"
    soft_min_tokens: int = Field(default=100, ge=20, le=2000)
    target_tokens: int = Field(default=450, ge=100, le=4000)
    max_tokens: int = Field(default=700, ge=150, le=8000)
    overlap_tokens: int = Field(default=60, ge=0, le=1000)
    keep_definitions_together: bool = True
    preserve_section_context: bool = True
    preserve_cross_page_continuations: bool = True
    group_dependent_children: bool = True
    attach_parent_context_on_split: bool = True
    pack_short_sibling_clauses: bool = True
    attach_contextual_notes: bool = True
    attach_group_headers_as_context: bool = True
    suppress_intro_only_figure_chunks: bool = True
    suppress_non_explanatory_figure_shells: bool = True
    exclude_navigation_sections: bool = True
    row_aware_table_splitting: bool = True
    cleaning: RetrievalCleaningPolicy = Field(default_factory=RetrievalCleaningPolicy)

    @model_validator(mode="after")
    def validate_token_limits(self):
        if self.soft_min_tokens > self.target_tokens:
            raise ValueError("soft_min_tokens must be less than or equal to target_tokens")
        if self.target_tokens > self.max_tokens:
            raise ValueError("target_tokens must be less than or equal to max_tokens")
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_tokens must be smaller than max_tokens")
        if not self.keep_definitions_together:
            raise ValueError("semantic chunking requires keep_definitions_together=true")
        if not self.preserve_cross_page_continuations:
            raise ValueError("semantic chunking requires preserve_cross_page_continuations=true")
        if self.cleaning.include_figures_without_text:
            raise ValueError("Textless figures cannot be retrieval chunks until image semantic extraction is implemented")
        return self


class GenerateChunksRequest(BaseModel):
    config: ChunkingConfig = Field(default_factory=ChunkingConfig)


class CleaningDecision(BaseModel):
    element_id: str
    page_number: int
    type: CanonicalElementType
    action: CleaningAction
    reason: str
    text_preview: str = ""


class RetrievalCleaningSummary(BaseModel):
    input_element_count: int
    included_element_count: int
    context_element_count: int
    excluded_element_count: int
    normalized_element_count: int = 0
    reason_counts: dict[str, int] = Field(default_factory=dict)
    decisions: list[CleaningDecision] = Field(default_factory=list)


class RetrievalChunk(BaseModel):
    chunk_id: str
    chunk_index: int = Field(ge=0)
    semantic_type: str
    text: str
    content_text: str
    context_text: str = ""
    token_count: int = Field(ge=1)
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)
    context_element_ids: list[str] = Field(default_factory=list)
    refinement_tags: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    source_table_ids: list[str] = Field(default_factory=list)
    relationship_ids: list[str] = Field(default_factory=list)
    split_part: int | None = Field(default=None, ge=1)
    split_total: int | None = Field(default=None, ge=1)


class ChunkingSummary(BaseModel):
    chunk_count: int
    estimated_token_count: int
    min_chunk_tokens: int
    max_chunk_tokens: int
    average_chunk_tokens: float
    semantic_type_counts: dict[str, int] = Field(default_factory=dict)
    pages_covered: list[int] = Field(default_factory=list)


class DeterministicChunkQualitySignal(BaseModel):
    code: str
    chunk_id: str
    message: str


class DeterministicChunkQualityReport(BaseModel):
    status: Literal["pass", "review"] = "pass"
    soft_min_tokens: int = 100
    tiny_chunk_count: int = 0
    orphan_child_count: int = 0
    dangling_intro_count: int = 0
    navigation_chunk_count: int = 0
    context_attached_chunk_count: int = 0
    dependency_group_chunk_count: int = 0
    continuation_merge_chunk_count: int = 0
    sibling_pack_chunk_count: int = 0
    table_split_chunk_count: int = 0
    note_attachment_chunk_count: int = 0
    caption_attachment_chunk_count: int = 0
    group_header_context_chunk_count: int = 0
    standalone_group_header_chunk_count: int = 0
    intro_only_figure_chunk_count: int = 0
    non_explanatory_figure_chunk_count: int = 0
    signals: list[DeterministicChunkQualitySignal] = Field(default_factory=list)


class ChunkingArtifact(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    source_sha256: str
    source_resolved_schema_version: str
    source_resolved_at: datetime
    base_structured_at: datetime
    strategy_version: str = "semantic-v2.1"
    token_count_method: str = "regex_estimate_v1"
    config: ChunkingConfig
    cleaning: RetrievalCleaningSummary
    summary: ChunkingSummary
    quality: DeterministicChunkQualityReport = Field(default_factory=DeterministicChunkQualityReport)
    chunks: list[RetrievalChunk] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime


class GenerateEmbeddingsRequest(BaseModel):
    embedding_model: str | None = None
    embedding_device: str | None = None
    force: bool = False
    batch_size: int | None = Field(default=None, ge=1, le=512)


class EmbeddingCompatibilityViolation(BaseModel):
    chunk_id: str
    chunk_index: int
    model_token_count: int
    model_max_seq_length: int


class EmbeddingCompatibilityResponse(BaseModel):
    document_id: str
    embedding_model: str
    requested_device: str
    resolved_device: str
    chunk_count: int
    compatible_chunk_count: int
    compatible: bool
    violation_count: int
    model_max_seq_length: int | None = None
    max_model_token_count: int | None = None
    longest_chunk_id: str | None = None
    longest_chunk_index: int | None = None
    violations: list[EmbeddingCompatibilityViolation] = Field(default_factory=list)


class EmbeddingStatusResponse(BaseModel):
    document_id: str
    embedding_model: str
    chunk_count: int
    embedded_chunk_count: int
    missing_chunk_count: int
    dimension: int | None = None
    complete: bool


class GenerateEmbeddingsResponse(EmbeddingStatusResponse):
    generated_count: int
    reused_count: int
    requested_device: str
    resolved_device: str


VisualAssetType = Literal["figure", "table"]
VisualRelation = Literal[
    "contains_visual",
    "figure_intro",
    "figure_caption",
    "figure_explanation",
    "figure_source",
    "nearby_explicit_reference",
    "table_content",
]


class VisualReference(BaseModel):
    """Read-only visual provenance attached to retrieved text evidence.

    Option-A visual support deliberately does not perform image understanding.
    These references only expose a PDF crop when canonical structure already
    establishes a deterministic relationship between the retrieved chunk and a
    figure/table (or a tightly bounded explicit-reference heuristic does so).
    """

    visual_id: str
    asset_type: VisualAssetType
    page_number: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    section_id: str | None = None
    label: str = ""
    relation: VisualRelation
    confidence: float = Field(ge=0.0, le=1.0)
    relation_element_ids: list[str] = Field(default_factory=list)


class DenseRetrievalRequest(BaseModel):
    document_id: str
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    embedding_model: str | None = None
    embedding_device: str | None = None
    semantic_types: list[str] = Field(default_factory=list)


class DenseRetrievalHit(BaseModel):
    rank: int
    chunk_id: str
    chunk_index: int
    semantic_type: str
    score: float
    distance: float
    text: str
    content_text: str
    token_count: int
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)
    visual_refs: list[VisualReference] = Field(default_factory=list)


class DenseRetrievalResponse(BaseModel):
    document_id: str
    query: str
    embedding_model: str
    requested_device: str
    resolved_device: str
    top_k: int
    embedded_chunk_count: int
    total_chunk_count: int
    hits: list[DenseRetrievalHit] = Field(default_factory=list)



class LexicalRetrievalRequest(BaseModel):
    document_id: str
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    semantic_types: list[str] = Field(default_factory=list)


class LexicalRetrievalHit(BaseModel):
    rank: int
    chunk_id: str
    chunk_index: int
    semantic_type: str
    score: float
    matched_term_count: int = 0
    term_coverage: float = 0.0
    text: str
    content_text: str
    token_count: int
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)
    visual_refs: list[VisualReference] = Field(default_factory=list)


class LexicalRetrievalResponse(BaseModel):
    document_id: str
    query: str
    top_k: int
    total_chunk_count: int
    search_config: str = "english"
    ranking_method: str = "postgresql_fts_term_coverage_then_ts_rank_cd"
    lexical_query_mode: str = "or_content_terms_v1"
    lexical_terms: list[str] = Field(default_factory=list)
    lexical_tsquery: str
    hits: list[LexicalRetrievalHit] = Field(default_factory=list)


class HybridRetrievalRequest(BaseModel):
    document_id: str
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    candidate_k: int = Field(default=20, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    dense_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    lexical_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    embedding_model: str | None = None
    embedding_device: str | None = None
    semantic_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_hybrid_limits(self):
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        if self.dense_weight == 0 and self.lexical_weight == 0:
            raise ValueError("At least one hybrid retrieval weight must be greater than zero")
        return self


class HybridRetrievalHit(BaseModel):
    rank: int
    chunk_id: str
    chunk_index: int
    semantic_type: str
    fusion_score: float
    dense_rank: int | None = None
    dense_score: float | None = None
    dense_distance: float | None = None
    dense_rrf_score: float = 0.0
    lexical_rank: int | None = None
    lexical_score: float | None = None
    lexical_matched_term_count: int = 0
    lexical_term_coverage: float = 0.0
    lexical_rrf_score: float = 0.0
    text: str
    content_text: str
    token_count: int
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)
    visual_refs: list[VisualReference] = Field(default_factory=list)


class HybridRetrievalResponse(BaseModel):
    document_id: str
    query: str
    embedding_model: str
    requested_device: str
    resolved_device: str
    top_k: int
    candidate_k: int
    embedded_chunk_count: int
    total_chunk_count: int
    fusion_method: str = "reciprocal_rank_fusion"
    rrf_k: int = 60
    dense_weight: float = 1.0
    lexical_weight: float = 1.0
    lexical_ranking_method: str = "postgresql_fts_term_coverage_then_ts_rank_cd"
    lexical_query_mode: str = "or_content_terms_v1"
    lexical_terms: list[str] = Field(default_factory=list)
    lexical_tsquery: str
    hits: list[HybridRetrievalHit] = Field(default_factory=list)


class RerankedRetrievalRequest(BaseModel):
    document_id: str
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    candidate_k: int = Field(default=20, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    dense_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    lexical_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    embedding_model: str | None = None
    embedding_device: str | None = None
    reranker_model: str | None = None
    reranker_device: str | None = None
    reranker_batch_size: int | None = Field(default=None, ge=1, le=128)
    semantic_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reranked_limits(self):
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        if self.dense_weight == 0 and self.lexical_weight == 0:
            raise ValueError("At least one hybrid retrieval weight must be greater than zero")
        return self


class RetrievalExperimentLockedComponentsV1(BaseModel):
    """System-owned component identities for controlled Stage 15 retrieval runs."""

    model_config = {"extra": "forbid"}

    embedding_model: Literal["BAAI/bge-m3"] = "BAAI/bge-m3"
    lexical_backend: Literal["postgresql_fts"] = "postgresql_fts"
    lexical_search_config: Literal["english"] = "english"
    lexical_ranking_method: Literal[
        "postgresql_fts_term_coverage_then_ts_rank_cd"
    ] = "postgresql_fts_term_coverage_then_ts_rank_cd"
    lexical_query_mode: Literal["or_content_terms_v1"] = "or_content_terms_v1"
    fusion_method: Literal["reciprocal_rank_fusion"] = "reciprocal_rank_fusion"
    reranker_model: Literal["BAAI/bge-reranker-v2-m3"] = "BAAI/bge-reranker-v2-m3"


RetrievalExperimentStrategy = Literal["dense", "hybrid", "hybrid_reranker"]


class RetrievalExperimentConfigV1(BaseModel):
    """Strict, versioned retrieval-quality configuration for Stage 15 experiments.

    Only architecture parameters already implemented by the project are
    user-controllable. Model, lexical, and fusion identities are locked so an
    experiment cannot silently become a different retrieval system.
    """

    model_config = {"extra": "forbid"}

    schema_version: Literal["retrieval_experiment_config_v1"] = "retrieval_experiment_config_v1"
    strategy: RetrievalExperimentStrategy
    top_k: int = Field(default=5, ge=1, le=50)

    # Hybrid-only parameters. They are normalized to frozen Retrieval v1
    # defaults for hybrid strategies and must be omitted for dense-only runs.
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    rrf_k: int | None = Field(default=None, ge=1, le=1000)
    dense_weight: float | None = Field(default=None, ge=0.0, le=10.0)
    lexical_weight: float | None = Field(default=None, ge=0.0, le=10.0)

    locked_components: RetrievalExperimentLockedComponentsV1 = Field(
        default_factory=RetrievalExperimentLockedComponentsV1
    )

    @model_validator(mode="after")
    def normalize_and_validate_strategy(self):
        hybrid_values = (
            self.candidate_k,
            self.rrf_k,
            self.dense_weight,
            self.lexical_weight,
        )

        if self.strategy == "dense":
            if any(value is not None for value in hybrid_values):
                raise ValueError(
                    "Dense experiments must omit candidate_k, rrf_k, dense_weight, "
                    "and lexical_weight because those stages are not executed"
                )
            return self

        if self.candidate_k is None:
            self.candidate_k = 20
        if self.rrf_k is None:
            self.rrf_k = 60
        if self.dense_weight is None:
            self.dense_weight = 1.0
        if self.lexical_weight is None:
            self.lexical_weight = 1.0

        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        if self.dense_weight == 0 and self.lexical_weight == 0:
            raise ValueError("At least one hybrid retrieval weight must be greater than zero")
        return self


class RerankedRetrievalHit(BaseModel):
    rank: int
    chunk_id: str
    chunk_index: int
    semantic_type: str
    reranker_score: float
    hybrid_candidate_rank: int
    fusion_score: float
    dense_rank: int | None = None
    dense_score: float | None = None
    dense_distance: float | None = None
    dense_rrf_score: float = 0.0
    lexical_rank: int | None = None
    lexical_score: float | None = None
    lexical_matched_term_count: int = 0
    lexical_term_coverage: float = 0.0
    lexical_rrf_score: float = 0.0
    text: str
    content_text: str
    token_count: int
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)
    visual_refs: list[VisualReference] = Field(default_factory=list)


class RetrievalTraceDenseCandidate(BaseModel):
    rank: int
    chunk_id: str
    chunk_index: int
    semantic_type: str
    score: float
    distance: float
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)


class RetrievalTraceLexicalCandidate(BaseModel):
    rank: int
    chunk_id: str
    chunk_index: int
    semantic_type: str
    score: float
    matched_term_count: int = 0
    term_coverage: float = 0.0
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)


class RetrievalTraceFusedCandidate(BaseModel):
    rank: int
    chunk_id: str
    chunk_index: int
    semantic_type: str
    fusion_score: float
    dense_rank: int | None = None
    dense_score: float | None = None
    dense_distance: float | None = None
    dense_rrf_score: float = 0.0
    lexical_rank: int | None = None
    lexical_score: float | None = None
    lexical_matched_term_count: int = 0
    lexical_term_coverage: float = 0.0
    lexical_rrf_score: float = 0.0
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)


class RetrievalTraceRerankedCandidate(RetrievalTraceFusedCandidate):
    reranker_rank: int
    reranker_score: float
    selected_as_context_seed: bool = False


class RetrievalExecutionTrace(BaseModel):
    trace_version: str = "retrieval_trace_v1"
    same_execution: bool = True
    dense_candidates: list[RetrievalTraceDenseCandidate] = Field(default_factory=list)
    lexical_candidates: list[RetrievalTraceLexicalCandidate] = Field(default_factory=list)
    fused_candidates: list[RetrievalTraceFusedCandidate] = Field(default_factory=list)
    reranked_candidates: list[RetrievalTraceRerankedCandidate] = Field(default_factory=list)
    lexical_terms: list[str] = Field(default_factory=list)
    lexical_tsquery: str = ""
    context_seed_chunk_ids: list[str] = Field(default_factory=list)
    context_attached_chunk_ids: list[str] = Field(default_factory=list)


class RerankedRetrievalResponse(BaseModel):
    document_id: str
    query: str
    embedding_model: str
    embedding_requested_device: str
    embedding_resolved_device: str
    reranker_model: str
    reranker_requested_device: str
    reranker_resolved_device: str
    reranker_batch_size: int
    reranker_max_length: int
    top_k: int
    candidate_k: int
    candidate_union_count: int
    embedded_chunk_count: int
    total_chunk_count: int
    candidate_strategy: str = "dense_lexical_union"
    ranking_method: str = "cross_encoder"
    fusion_method: str = "reciprocal_rank_fusion_trace"
    rrf_k: int = 60
    dense_weight: float = 1.0
    lexical_weight: float = 1.0
    lexical_ranking_method: str = "postgresql_fts_term_coverage_then_ts_rank_cd"
    lexical_query_mode: str = "or_content_terms_v1"
    lexical_terms: list[str] = Field(default_factory=list)
    lexical_tsquery: str
    retrieval_trace: RetrievalExecutionTrace | None = None
    hits: list[RerankedRetrievalHit] = Field(default_factory=list)

class StructuralContextChunk(BaseModel):
    context_order: int
    chunk_id: str
    chunk_index: int
    semantic_type: str
    source_rank: int
    ranked_seed_rank: int | None = None
    reasons: list[str] = Field(default_factory=list)
    attached_from_chunk_ids: list[str] = Field(default_factory=list)
    text: str
    content_text: str
    token_count: int
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)
    visual_refs: list[VisualReference] = Field(default_factory=list)


class ContextExpandedRetrievalRequest(RerankedRetrievalRequest):
    context_max_forward_neighbors_per_seed: int = Field(default=2, ge=0, le=4)
    context_max_backward_neighbors_per_seed: int = Field(default=1, ge=0, le=2)
    context_max_page_gap: int = Field(default=1, ge=0, le=3)
    context_max_chunks: int = Field(default=30, ge=1, le=100)

    @model_validator(mode="after")
    def validate_context_limits(self):
        if self.context_max_chunks < self.top_k:
            raise ValueError("context_max_chunks must be greater than or equal to top_k")
        return self


class ContextExpandedRetrievalResponse(RerankedRetrievalResponse):
    context_strategy: str = "structural_one_hop_v1"
    context_recursive: bool = False
    context_same_section_required: bool = True
    context_max_forward_neighbors_per_seed: int = 2
    context_max_backward_neighbors_per_seed: int = 1
    context_max_page_gap: int = 1
    context_max_chunks: int = 30
    context_chunk_count: int
    expanded_chunk_count: int
    context_chunks: list[StructuralContextChunk] = Field(default_factory=list)



# ---------------------------------------------------------------------------
# Stage 9 — grounded answer generation
# ---------------------------------------------------------------------------

class GroundedAnswerRequest(BaseModel):
    document_id: str
    question: str = Field(min_length=1, max_length=4000)


class GenerationEvidence(BaseModel):
    evidence_id: str
    chunk_id: str
    chunk_index: int
    semantic_type: str
    source_rank: int
    ranked_seed_rank: int | None = None
    reasons: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)
    content_text: str
    visual_refs: list[VisualReference] = Field(default_factory=list)


class CitationLocator(BaseModel):
    kind: Literal["clause", "subclause", "definition", "appendix", "section", "page"]
    label: str
    pages: list[int] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)


class SourceCitation(BaseModel):
    citation_id: str
    marker: str
    evidence_id: str
    chunk_id: str
    chunk_index: int
    source_filename: str
    display: str
    pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    source_element_ids: list[str] = Field(default_factory=list)
    locators: list[CitationLocator] = Field(default_factory=list)
    validation_status: Literal["valid"] = "valid"


class CitationValidationSummary(BaseModel):
    status: Literal["valid"] = "valid"
    citation_count: int = 0
    valid_citation_count: int = 0
    errors: list[str] = Field(default_factory=list)


class GroundedClaim(BaseModel):
    claim_id: str
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    citation_ids: list[str] = Field(default_factory=list)


class GenerationUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class GroundedAnswerResponse(BaseModel):
    document_id: str
    question: str
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    cited_answer: str = ""
    claims: list[GroundedClaim] = Field(default_factory=list)
    used_evidence_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    evidence: list[GenerationEvidence] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)
    citation_version: str = "deterministic_citations_v1_2"
    citation_validation: CitationValidationSummary = Field(default_factory=CitationValidationSummary)

    # Generation trace. The API never returns an API key.
    generation_provider: str
    generation_model: str
    prompt_version: str
    generation_temperature: float
    generation_max_tokens: int
    generation_json_mode: bool
    usage: GenerationUsage | None = None

    # Frozen Retrieval-v1 / Stage-8.2 production profile used to build evidence.
    retrieval_profile: str
    retrieval_top_k: int
    retrieval_candidate_k: int
    retrieval_rrf_k: int
    retrieval_dense_weight: float
    retrieval_lexical_weight: float
    context_strategy: str
    context_chunk_count: int
    expanded_chunk_count: int
    retrieval_trace: RetrievalExecutionTrace | None = None
