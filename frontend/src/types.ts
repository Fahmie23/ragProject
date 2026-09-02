export type PdfType = "digital" | "scanned" | "mixed" | "unknown";
export type ExtractionStatus = "not_started" | "completed" | "failed";
export type StructureStatus = "not_started" | "completed" | "failed";
export type CanonicalElementType =
  | "title"
  | "subtitle"
  | "document_metadata"
  | "section_header"
  | "group_header"
  | "clause"
  | "subclause"
  | "definition_term"
  | "definition_text"
  | "paragraph"
  | "list_item"
  | "table"
  | "figure"
  | "caption"
  | "page_header"
  | "page_footer"
  | "footnote"
  | "formula"
  | "unknown";

export interface DocumentClassification {
  document_family: string;
  pdf_type?: PdfType | null;
  page_count?: number | null;
  text_pages?: number | null;
  image_pages?: number | null;
  has_text_layer?: boolean | null;
  has_images?: boolean | null;
  encrypted?: boolean | null;
}

export interface DocumentRecord {
  document_id: string;
  original_filename: string;
  stored_filename: string;
  extension: string;
  detected_mime_type?: string | null;
  size_bytes: number;
  sha256: string;
  validation_status: "valid" | "invalid";
  validation_errors: string[];
  classification: DocumentClassification;
  ingested_at: string;
  extraction_status: ExtractionStatus;
  extraction_error?: string | null;
  extracted_at?: string | null;
  structure_status: StructureStatus;
  structure_error?: string | null;
  structured_at?: string | null;
}

export interface TextSpan {
  span_id?: string | null;
  text: string;
  bbox: number[];
  origin?: number[] | null;
  font?: string | null;
  size?: number | null;
  flags?: number | null;
  color?: number | null;
  ascender?: number | null;
  descender?: number | null;
}

export interface TextLine {
  line_id?: string | null;
  bbox: number[];
  text: string;
  writing_mode?: number | null;
  direction?: number[] | null;
  spans: TextSpan[];
}

export interface TextBlock {
  block_id: string;
  type: "text";
  number: number;
  bbox: number[];
  text: string;
  lines: TextLine[];
}

export interface ImageBlock {
  block_id: string;
  type: "image";
  number: number;
  bbox: number[];
  width?: number | null;
  height?: number | null;
  extension?: string | null;
  colorspace?: number | null;
  bits_per_component?: number | null;
  xres?: number | null;
  yres?: number | null;
  encoded_size_bytes?: number | null;
}

export type ExtractionBlock = TextBlock | ImageBlock;

export interface TableExtraction {
  table_id: string;
  bbox: number[];
  row_count: number;
  col_count: number;
  cells: (string | null)[][];
}

export interface PageExtraction {
  page_number: number;
  width: number;
  height: number;
  rotation: number;
  text: string;
  text_char_count: number;
  blocks: ExtractionBlock[];
  tables: TableExtraction[];
  warnings: string[];
}

export interface DocumentExtraction {
  schema_version: string;
  document_id: string;
  source_filename: string;
  source_sha256: string;
  source_pdf_type?: PdfType | null;
  extraction_mode: string;
  extractor: {
    name: string;
    version: string;
    settings: Record<string, string | boolean | number>;
  };
  summary: {
    page_count: number;
    text_char_count: number;
    text_block_count: number;
    image_block_count: number;
    table_count: number;
  };
  pages: PageExtraction[];
  warnings: string[];
  extracted_at: string;
}

export interface CanonicalTable {
  row_count: number;
  col_count: number;
  cells: (string | null)[][];
  markdown?: string | null;
}

export interface CanonicalSourceTrace {
  layout_box_index: number;
  layout_box_class: string;
  stage3_block_ids: string[];
  stage3_line_ids?: string[];
  stage3_span_ids?: string[];
  stage3_table_ids: string[];
}


export interface SemanticTypeAlternative {
  type: CanonicalElementType;
  score: number;
}

export interface SemanticClassification {
  selected_type: CanonicalElementType;
  confidence: number;
  source: string;
  evidence: string[];
  alternatives: SemanticTypeAlternative[];
}

export interface CanonicalElement {
  element_id: string;
  type: CanonicalElementType;
  page_number: number;
  reading_order: number;
  document_order: number;
  bbox: number[];
  text: string;
  section_id?: string | null;
  definition_entry_id?: string | null;
  clause_number?: string | null;
  clause_id?: string | null;
  parent_clause_id?: string | null;
  subclause_marker?: string | null;
  logical_table_id?: string | null;
  figure_id?: string | null;
  appendix_id?: string | null;
  heading_level?: number | null;
  heading_level_source?: "pdf_toc" | "numbering" | "font_rank" | "unknown" | null;
  dominant_font_size?: number | null;
  layout_role?: string | null;
  classification?: SemanticClassification | null;
  role_source: string;
  table?: CanonicalTable | null;
  source: CanonicalSourceTrace;
}

export interface StructuredPage {
  page_number: number;
  width: number;
  height: number;
  elements: CanonicalElement[];
  body_text: string;
}

export interface SectionRecord {
  section_id: string;
  title: string;
  level?: number | null;
  page_number: number;
  element_id: string;
  parent_section_id?: string | null;
  level_source: "pdf_toc" | "numbering" | "font_rank" | "unknown";
  kind: "section" | "question" | "appendix";
  content_element_ids: string[];
}

export interface DefinitionSubItem {
  marker: string;
  text: string;
}

export interface DefinitionEntry {
  definition_id: string;
  term: string;
  section_id?: string | null;
  term_element_id?: string | null;
  source_table_element_id?: string | null;
  source_kind: "layout_columns" | "table_rows";
  definition_text: string;
  items: DefinitionSubItem[];
  definition_element_ids: string[];
  start_page: number;
  end_page: number;
  spans_multiple_pages: boolean;
  continues_to_next_page: boolean;
}


export interface ClauseRecord {
  clause_id: string;
  number: string;
  kind: "clause" | "subclause";
  element_id: string;
  page_number: number;
  section_id?: string | null;
  parent_clause_id?: string | null;
}

export interface AppendixRecord {
  appendix_id: string;
  label: string;
  label_element_id: string;
  title?: string | null;
  title_element_id?: string | null;
  start_page: number;
  end_page: number;
}

export interface LogicalTable {
  logical_table_id: string;
  fragment_element_ids: string[];
  start_page: number;
  end_page: number;
  spans_multiple_pages: boolean;
  row_count: number;
  col_count: number;
  cells: (string | null)[][];
  section_id?: string | null;
  merge_source: "single_fragment" | "cross_page_geometry";
}

export interface FigureRecord {
  figure_id: string;
  element_id: string;
  page_number: number;
  section_id?: string | null;
  intro_element_ids: string[];
  caption_element_ids: string[];
  explanation_element_ids: string[];
  source_element_ids: string[];
}

export interface StructuralRelation {
  relation_id: string;
  type: "parent_of" | "continues" | "introduces" | "explains" | "caption_of" | "source_for" | "belongs_to";
  source_element_id: string;
  target_element_id: string;
  evidence: string;
  provenance?: "automatic" | "manual" | "derived";
}

export interface StructuredDocument {
  schema_version: string;
  document_id: string;
  source_filename: string;
  source_sha256: string;
  source_extraction_schema_version: string;
  layout_engine: {
    name: string;
    version: string;
    settings: Record<string, string | boolean | number>;
  };
  title: string;
  title_source: string;
  subtitle?: string | null;
  subtitle_source?: string | null;
  outline_root_element_id?: string | null;
  metadata_element_ids: string[];
  summary: {
    page_count: number;
    element_count: number;
    body_text_char_count: number;
    section_count: number;
    definition_count: number;
    clause_count: number;
    appendix_count: number;
    logical_table_count: number;
    figure_count: number;
    relation_count: number;
    element_counts: Record<string, number>;
  };
  sections: SectionRecord[];
  definitions: DefinitionEntry[];
  clauses: ClauseRecord[];
  appendices: AppendixRecord[];
  tables: LogicalTable[];
  figures: FigureRecord[];
  relationships: StructuralRelation[];
  pages: StructuredPage[];
  body_text: string;
  warnings: string[];
  structured_at: string;
}

export type LayoutArtifact = Record<string, unknown>;

export type CorrectionOperationType =
  | "move_resize"
  | "relabel"
  | "split"
  | "merge"
  | "draw"
  | "delete"
  | "link_definition"
  | "unlink_definition"
  | "assign_definition"
  | "unassign_definition"
  | "add_relationship"
  | "remove_relationship"
  | "span_rebuild"
  | "set_structure";

export type CorrectionStructuralType = "section_header" | "clause" | "subclause";

export interface CorrectionStructureSpec {
  element_id: string;
  type: CorrectionStructuralType;
  section_id?: string | null;
  parent_section_id?: string | null;
  section_kind?: "section" | "question";
  heading_level?: number | null;
  clause_id?: string | null;
  clause_number?: string | null;
  parent_clause_id?: string | null;
  subclause_marker?: string | null;
}

export interface IntegrityIssue {
  issue_id: string;
  code: string;
  severity: "error" | "warning";
  message: string;
  element_ids: string[];
  record_ids: string[];
  requires_review: boolean;
}

export interface RelationshipIntegrityReport {
  status: "pass" | "fail" | "unknown";
  semantic_status: "clear" | "review_required" | "blocked" | "unknown";
  errors: IntegrityIssue[];
  warnings: IntegrityIssue[];
  counts: Record<string, number>;
}

export interface RelationshipReviewState {
  status: "not_reviewed" | "needs_review" | "approved" | "blocked";
  approved_issue_ids: string[];
  pending_issue_ids: string[];
  approved_at?: string | null;
  note?: string | null;
  stage5_eligible: boolean;
}

export interface CorrectionElementSpec {
  element_id: string;
  type: CanonicalElementType;
  bbox: number[];
  source_span_ids?: string[];
}

export interface CorrectionRelationshipSpec {
  relation_id: string;
  type: StructuralRelation["type"];
  source_element_id: string;
  target_element_id: string;
  source_page_number: number;
  target_page_number: number;
  evidence: string;
}

export interface CorrectionOperation {
  operation_id: string;
  operation: CorrectionOperationType;
  page_number: number;
  source_element_ids: string[];
  result_elements: CorrectionElementSpec[];
  relationships: CorrectionRelationshipSpec[];
  structure?: CorrectionStructureSpec | null;
  new_type?: CanonicalElementType | null;
  definition_id?: string | null;
  target_page_number?: number | null;
  note?: string | null;
  created_at: string;
}

export interface CorrectionArtifact {
  schema_version: string;
  document_id: string;
  source_sha256: string;
  base_structure_schema_version: string;
  base_structured_at: string;
  operations: CorrectionOperation[];
  relationship_review: RelationshipReviewState;
  updated_at: string;
}

export interface ResolvedStructureArtifact {
  schema_version: string;
  document_id: string;
  source_sha256: string;
  base_structured_at: string;
  correction_count: number;
  resolved_at: string;
  structure: StructuredDocument;
  baseline_integrity?: RelationshipIntegrityReport | null;
  integrity: RelationshipIntegrityReport;
  review: RelationshipReviewState;
  warnings: string[];
}

export interface ValidateCorrectionsResponse {
  valid: boolean;
  resolved?: ResolvedStructureArtifact | null;
  errors: string[];
}

export interface SaveCorrectionsRequest {
  base_structured_at: string;
  operations: CorrectionOperation[];
}

export interface SaveCorrectionsResponse {
  corrections: CorrectionArtifact;
  resolved: ResolvedStructureArtifact;
}

export interface RetrievalCleaningPolicy {
  exclude_page_headers: boolean;
  exclude_page_footers: boolean;
  exclude_margin_page_numbers: boolean;
  exclude_repeated_margin_text: boolean;
  deduplicate_overlapping_text: boolean;
  repeated_margin_min_pages: number;
  include_footnotes: boolean;
  include_document_metadata: boolean;
  include_figures_without_text: boolean;
  normalize_whitespace: boolean;
  dehyphenate_line_breaks: boolean;
}

export interface ChunkingConfig {
  strategy: "semantic_v1" | "semantic_v2";
  soft_min_tokens: number;
  target_tokens: number;
  max_tokens: number;
  overlap_tokens: number;
  keep_definitions_together: boolean;
  preserve_section_context: boolean;
  preserve_cross_page_continuations: boolean;
  group_dependent_children: boolean;
  attach_parent_context_on_split: boolean;
  pack_short_sibling_clauses: boolean;
  attach_contextual_notes: boolean;
  attach_group_headers_as_context: boolean;
  suppress_intro_only_figure_chunks: boolean;
  suppress_non_explanatory_figure_shells: boolean;
  exclude_navigation_sections: boolean;
  row_aware_table_splitting: boolean;
  cleaning: RetrievalCleaningPolicy;
}

export interface CleaningDecision {
  element_id: string;
  page_number: number;
  type: CanonicalElementType;
  action: "include" | "context" | "exclude";
  reason: string;
  text_preview: string;
}

export interface RetrievalCleaningSummary {
  input_element_count: number;
  included_element_count: number;
  context_element_count: number;
  excluded_element_count: number;
  normalized_element_count: number;
  reason_counts: Record<string, number>;
  decisions: CleaningDecision[];
}

export interface RetrievalChunk {
  chunk_id: string;
  chunk_index: number;
  semantic_type: string;
  text: string;
  content_text: string;
  context_text: string;
  token_count: number;
  pages: number[];
  section_path: string[];
  source_element_ids: string[];
  context_element_ids: string[];
  refinement_tags: string[];
  source_span_ids: string[];
  source_block_ids: string[];
  source_table_ids: string[];
  relationship_ids: string[];
  split_part?: number | null;
  split_total?: number | null;
}

export interface ChunkingSummary {
  chunk_count: number;
  estimated_token_count: number;
  min_chunk_tokens: number;
  max_chunk_tokens: number;
  average_chunk_tokens: number;
  semantic_type_counts: Record<string, number>;
  pages_covered: number[];
}


export interface DeterministicChunkQualitySignal {
  code: string;
  chunk_id: string;
  message: string;
}

export interface DeterministicChunkQualityReport {
  status: "pass" | "review";
  soft_min_tokens: number;
  tiny_chunk_count: number;
  orphan_child_count: number;
  dangling_intro_count: number;
  navigation_chunk_count: number;
  context_attached_chunk_count: number;
  dependency_group_chunk_count: number;
  continuation_merge_chunk_count: number;
  sibling_pack_chunk_count: number;
  table_split_chunk_count: number;
  note_attachment_chunk_count: number;
  caption_attachment_chunk_count: number;
  group_header_context_chunk_count: number;
  standalone_group_header_chunk_count: number;
  intro_only_figure_chunk_count: number;
  non_explanatory_figure_chunk_count: number;
  signals: DeterministicChunkQualitySignal[];
}

export interface ChunkingArtifact {
  schema_version: string;
  document_id: string;
  source_sha256: string;
  source_resolved_schema_version: string;
  source_resolved_at: string;
  base_structured_at: string;
  strategy_version: string;
  token_count_method: string;
  config: ChunkingConfig;
  cleaning: RetrievalCleaningSummary;
  summary: ChunkingSummary;
  quality: DeterministicChunkQualityReport;
  chunks: RetrievalChunk[];
  warnings: string[];
  generated_at: string;
}

export interface EmbeddingCudaDevice {
  index: number;
  name: string;
}

export interface EmbeddingSystemStatus {
  embedding_model: string;
  configured_device: string;
  resolved_device?: string | null;
  embedding_batch_size: number;
  torch_available: boolean;
  cuda_available: boolean;
  cuda_device_count: number;
  cuda_devices: EmbeddingCudaDevice[];
  resolution_error?: string | null;
}

export interface EmbeddingStatus {
  document_id: string;
  embedding_model: string;
  chunk_count: number;
  embedded_chunk_count: number;
  missing_chunk_count: number;
  dimension?: number | null;
  complete: boolean;
}

export interface GenerateEmbeddingsRequest {
  embedding_model?: string | null;
  embedding_device?: string | null;
  force?: boolean;
  batch_size?: number | null;
}

export interface GenerateEmbeddingsResponse extends EmbeddingStatus {
  generated_count: number;
  reused_count: number;
  requested_device: string;
  resolved_device: string;
}

export interface EmbeddingCompatibilityViolation {
  chunk_id: string;
  chunk_index: number;
  model_token_count: number;
  model_max_seq_length: number;
}

export interface EmbeddingCompatibilityResponse {
  document_id: string;
  embedding_model: string;
  requested_device: string;
  resolved_device: string;
  chunk_count: number;
  compatible_chunk_count: number;
  compatible: boolean;
  violation_count: number;
  model_max_seq_length?: number | null;
  max_model_token_count?: number | null;
  longest_chunk_id?: string | null;
  longest_chunk_index?: number | null;
  violations: EmbeddingCompatibilityViolation[];
}


export interface DenseRetrievalRequest {
  document_id: string;
  query: string;
  top_k?: number;
  embedding_model?: string | null;
  embedding_device?: string | null;
  semantic_types?: string[];
}

export interface DenseRetrievalHit {
  rank: number;
  chunk_id: string;
  chunk_index: number;
  semantic_type: string;
  score: number;
  distance: number;
  text: string;
  content_text: string;
  token_count: number;
  pages: number[];
  section_path: string[];
  source_element_ids: string[];
}

export interface DenseRetrievalResponse {
  document_id: string;
  query: string;
  embedding_model: string;
  requested_device: string;
  resolved_device: string;
  top_k: number;
  embedded_chunk_count: number;
  total_chunk_count: number;
  hits: DenseRetrievalHit[];
}

export interface HybridRetrievalRequest extends DenseRetrievalRequest {
  candidate_k?: number;
  rrf_k?: number;
  dense_weight?: number;
  lexical_weight?: number;
}

export interface HybridRetrievalHit {
  rank: number;
  chunk_id: string;
  chunk_index: number;
  semantic_type: string;
  fusion_score: number;
  dense_rank?: number | null;
  dense_score?: number | null;
  dense_distance?: number | null;
  dense_rrf_score: number;
  lexical_rank?: number | null;
  lexical_score?: number | null;
  lexical_matched_term_count: number;
  lexical_term_coverage: number;
  lexical_rrf_score: number;
  text: string;
  content_text: string;
  token_count: number;
  pages: number[];
  section_path: string[];
  source_element_ids: string[];
}

export interface HybridRetrievalResponse {
  document_id: string;
  query: string;
  embedding_model: string;
  requested_device: string;
  resolved_device: string;
  top_k: number;
  candidate_k: number;
  embedded_chunk_count: number;
  total_chunk_count: number;
  fusion_method: "reciprocal_rank_fusion" | string;
  rrf_k: number;
  dense_weight: number;
  lexical_weight: number;
  lexical_ranking_method: string;
  lexical_query_mode: string;
  lexical_terms: string[];
  lexical_tsquery: string;
  hits: HybridRetrievalHit[];
}

export interface RerankedRetrievalRequest extends HybridRetrievalRequest {
  reranker_model?: string | null;
  reranker_device?: string | null;
  reranker_batch_size?: number | null;
}

export interface RerankedRetrievalHit {
  rank: number;
  chunk_id: string;
  chunk_index: number;
  semantic_type: string;
  reranker_score: number;
  hybrid_candidate_rank: number;
  fusion_score: number;
  dense_rank?: number | null;
  dense_score?: number | null;
  dense_distance?: number | null;
  dense_rrf_score: number;
  lexical_rank?: number | null;
  lexical_score?: number | null;
  lexical_matched_term_count: number;
  lexical_term_coverage: number;
  lexical_rrf_score: number;
  text: string;
  content_text: string;
  token_count: number;
  pages: number[];
  section_path: string[];
  source_element_ids: string[];
}

export interface RerankedRetrievalResponse {
  document_id: string;
  query: string;
  embedding_model: string;
  embedding_requested_device: string;
  embedding_resolved_device: string;
  reranker_model: string;
  reranker_requested_device: string;
  reranker_resolved_device: string;
  reranker_batch_size: number;
  reranker_max_length: number;
  top_k: number;
  candidate_k: number;
  candidate_union_count: number;
  embedded_chunk_count: number;
  total_chunk_count: number;
  candidate_strategy: string;
  ranking_method: string;
  fusion_method: string;
  rrf_k: number;
  dense_weight: number;
  lexical_weight: number;
  lexical_ranking_method: string;
  lexical_query_mode: string;
  lexical_terms: string[];
  lexical_tsquery: string;
  hits: RerankedRetrievalHit[];
}

export interface StructuralContextChunk {
  context_order: number;
  chunk_id: string;
  chunk_index: number;
  semantic_type: string;
  source_rank: number;
  ranked_seed_rank?: number | null;
  reasons: string[];
  attached_from_chunk_ids: string[];
  text: string;
  content_text: string;
  token_count: number;
  pages: number[];
  section_path: string[];
  source_element_ids: string[];
}

export interface ContextExpandedRetrievalRequest extends RerankedRetrievalRequest {
  context_max_forward_neighbors_per_seed?: number;
  context_max_backward_neighbors_per_seed?: number;
  context_max_page_gap?: number;
  context_max_chunks?: number;
}

export interface ContextExpandedRetrievalResponse extends RerankedRetrievalResponse {
  context_strategy: string;
  context_recursive: boolean;
  context_same_section_required: boolean;
  context_max_forward_neighbors_per_seed: number;
  context_max_backward_neighbors_per_seed: number;
  context_max_page_gap: number;
  context_max_chunks: number;
  context_chunk_count: number;
  expanded_chunk_count: number;
  context_chunks: StructuralContextChunk[];
}



export interface GroundedAnswerRequest {
  document_id: string;
  question: string;
}

export interface GenerationEvidence {
  evidence_id: string;
  chunk_id: string;
  chunk_index: number;
  semantic_type: string;
  source_rank: number;
  ranked_seed_rank?: number | null;
  reasons: string[];
  pages: number[];
  section_path: string[];
  source_element_ids: string[];
  content_text: string;
}

export interface CitationLocator {
  kind: "clause" | "subclause" | "definition" | "appendix" | "section" | "page";
  label: string;
  pages: number[];
  source_element_ids: string[];
}

export interface SourceCitation {
  citation_id: string;
  marker: string;
  evidence_id: string;
  chunk_id: string;
  chunk_index: number;
  source_filename: string;
  display: string;
  pages: number[];
  section_path: string[];
  source_element_ids: string[];
  locators: CitationLocator[];
  validation_status: "valid";
}

export interface CitationValidationSummary {
  status: "valid";
  citation_count: number;
  valid_citation_count: number;
  errors: string[];
}

export interface GroundedClaim {
  claim_id: string;
  text: string;
  evidence_ids: string[];
  citation_ids: string[];
}

export interface GenerationUsage {
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
}

export interface GroundedAnswerResponse {
  document_id: string;
  question: string;
  status: "answered" | "insufficient_evidence";
  answer: string;
  cited_answer: string;
  claims: GroundedClaim[];
  used_evidence_ids: string[];
  missing_information: string[];
  evidence: GenerationEvidence[];
  citations: SourceCitation[];
  citation_version: string;
  citation_validation: CitationValidationSummary;
  generation_provider: string;
  generation_model: string;
  prompt_version: string;
  generation_temperature: number;
  generation_max_tokens: number;
  generation_json_mode: boolean;
  usage?: GenerationUsage | null;
  retrieval_profile: string;
  retrieval_top_k: number;
  retrieval_candidate_k: number;
  retrieval_rrf_k: number;
  retrieval_dense_weight: number;
  retrieval_lexical_weight: number;
  context_strategy: string;
  context_chunk_count: number;
  expanded_chunk_count: number;
}
