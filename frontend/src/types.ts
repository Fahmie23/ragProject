export type PdfType = "digital" | "scanned" | "mixed" | "unknown";
export type ExtractionStatus = "not_started" | "completed" | "failed";
export type StructureStatus = "not_started" | "completed" | "failed";
export type CanonicalElementType =
  | "title"
  | "subtitle"
  | "document_metadata"
  | "section_header"
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
  stage3_table_ids: string[];
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
  | "delete";

export interface CorrectionElementSpec {
  element_id: string;
  type: CanonicalElementType;
  bbox: number[];
}

export interface CorrectionOperation {
  operation_id: string;
  operation: CorrectionOperationType;
  page_number: number;
  source_element_ids: string[];
  result_elements: CorrectionElementSpec[];
  new_type?: CanonicalElementType | null;
  created_at: string;
}

export interface CorrectionArtifact {
  schema_version: string;
  document_id: string;
  source_sha256: string;
  base_structure_schema_version: string;
  base_structured_at: string;
  operations: CorrectionOperation[];
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
  warnings: string[];
}

export interface SaveCorrectionsRequest {
  base_structured_at: string;
  operations: CorrectionOperation[];
}

export interface SaveCorrectionsResponse {
  corrections: CorrectionArtifact;
  resolved: ResolvedStructureArtifact;
}
