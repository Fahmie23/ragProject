import type {
  ChunkingArtifact,
  ChunkingConfig,
  DocumentExtraction,
  DocumentRecord,
  CorrectionArtifact,
  LayoutArtifact,
  ResolvedStructureArtifact,
  SaveCorrectionsRequest,
  SaveCorrectionsResponse,
  StructuredDocument,
  ValidateCorrectionsResponse,
} from "./types";

export const API_BASE = "http://localhost:8000";

export class ApiRequestError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown = null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
  }
}

async function apiError(response: Response, fallback: string): Promise<Error> {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return new ApiRequestError(data.detail, response.status, data.detail);
    if (data.detail && typeof data.detail === "object") {
      const detail = data.detail as { message?: unknown; integrity?: { errors?: Array<{ message?: string }> } };
      const message = typeof detail.message === "string" ? detail.message : fallback;
      const firstIntegrityError = detail.integrity?.errors?.[0]?.message;
      return new ApiRequestError(firstIntegrityError ? `${message} ${firstIntegrityError}` : message, response.status, data.detail);
    }
    return new ApiRequestError(fallback, response.status, data.detail ?? null);
  } catch {
    return new ApiRequestError(fallback, response.status, null);
  }
}

export async function uploadDocument(file: File): Promise<DocumentRecord> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`${API_BASE}/api/documents/upload`, { method: "POST", body });
  if (!response.ok) throw await apiError(response, "Upload failed");
  const data = await response.json();
  return data.document;
}

export async function listDocuments(): Promise<DocumentRecord[]> {
  const response = await fetch(`${API_BASE}/api/documents`);
  if (!response.ok) throw await apiError(response, "Failed to load documents");
  return response.json();
}

export async function getDocument(documentId: string): Promise<DocumentRecord> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}`);
  if (!response.ok) throw await apiError(response, "Failed to load document");
  return response.json();
}

export async function runExtraction(documentId: string): Promise<DocumentExtraction> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/extract`, { method: "POST" });
  if (!response.ok) throw await apiError(response, "Extraction failed");
  return response.json();
}

export async function getExtraction(documentId: string): Promise<DocumentExtraction | null> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/extraction`);
  if (response.status === 404) return null;
  if (!response.ok) throw await apiError(response, "Failed to load extraction");
  return response.json();
}

export async function runStructure(documentId: string): Promise<StructuredDocument> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/structure`, { method: "POST" });
  if (!response.ok) throw await apiError(response, "Structure reconstruction failed");
  return response.json();
}

export async function getStructure(documentId: string): Promise<StructuredDocument | null> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/structure`);
  if (response.status === 404) return null;
  if (!response.ok) throw await apiError(response, "Failed to load structure");
  return response.json();
}

export async function getLayout(documentId: string): Promise<LayoutArtifact | null> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/layout`);
  if (response.status === 404) return null;
  if (!response.ok) throw await apiError(response, "Failed to load layout artifact");
  return response.json();
}

export function pagePreviewUrl(documentId: string, pageNumber: number) {
  return `${API_BASE}/api/documents/${documentId}/pages/${pageNumber}/preview`;
}

export function rawFileUrl(documentId: string) {
  return `${API_BASE}/api/documents/${documentId}/file`;
}


export async function getCorrections(documentId: string): Promise<CorrectionArtifact | null> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/corrections`);
  if (response.status === 404) return null;
  if (!response.ok) throw await apiError(response, "Failed to load Stage 4.5 corrections");
  return response.json();
}

export async function getResolvedStructure(documentId: string): Promise<ResolvedStructureArtifact | null> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/resolved-structure`);
  if (response.status === 404) return null;
  if (!response.ok) throw await apiError(response, "Failed to load resolved structure");
  return response.json();
}

export async function saveCorrections(documentId: string, payload: SaveCorrectionsRequest): Promise<SaveCorrectionsResponse> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/corrections`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await apiError(response, "Failed to save Stage 4.5 corrections");
  return response.json();
}

export async function validateCorrections(documentId: string, payload: SaveCorrectionsRequest): Promise<ValidateCorrectionsResponse> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/corrections/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await apiError(response, "Failed to validate Stage 4.5 corrections");
  return response.json();
}

export async function resetCorrections(documentId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/corrections`, { method: "DELETE" });
  if (!response.ok && response.status !== 204) throw await apiError(response, "Failed to reset Stage 4.5 corrections");
}


export async function getChunks(documentId: string): Promise<ChunkingArtifact | null> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/chunks`);
  if (response.status === 404) return null;
  if (response.status === 409) return null;
  if (!response.ok) throw await apiError(response, "Failed to load Stage 5 chunks");
  return response.json();
}

export async function generateChunks(documentId: string, config: ChunkingConfig): Promise<ChunkingArtifact> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/chunks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  if (!response.ok) throw await apiError(response, "Stage 5 chunking failed");
  return response.json();
}

export async function resetChunks(documentId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/chunks`, { method: "DELETE" });
  if (!response.ok && response.status !== 204) throw await apiError(response, "Failed to reset Stage 5 chunks");
}
