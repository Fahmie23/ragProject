import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import {
  ApiRequestError,
  generateEmbeddings,
  getEmbeddingStatus,
  getEmbeddingSystemStatus,
  resetEmbeddings,
  validateEmbeddingCompatibility,
} from "../api";
import type {
  ChunkingArtifact,
  DocumentRecord,
  EmbeddingCompatibilityResponse,
  EmbeddingStatus,
  EmbeddingSystemStatus,
  GenerateEmbeddingsResponse,
} from "../types";

type Props = {
  document: DocumentRecord;
  chunking: ChunkingArtifact | null;
  status: EmbeddingStatus | null;
  onStatusChange: (status: EmbeddingStatus | null) => void;
};

type BusyAction = "runtime" | "validate" | "generate" | "delete" | "refresh" | null;

function statusLabel(status: EmbeddingStatus | null, chunking: ChunkingArtifact | null) {
  if (!chunking) return "Waiting for knowledge";
  if (!status) return "Not generated";
  if (status.complete) return "Ready";
  if (status.embedded_chunk_count > 0) return "Partial";
  return "Not generated";
}

function errorDetail(error: unknown): { message: string; detail?: Record<string, unknown> } {
  if (error instanceof ApiRequestError) {
    const detail = error.detail && typeof error.detail === "object" ? error.detail as Record<string, unknown> : undefined;
    return { message: error.message, detail };
  }
  return { message: error instanceof Error ? error.message : "Unexpected embedding error." };
}

function DeviceBadge({ runtime }: { runtime: EmbeddingSystemStatus | null }) {
  if (!runtime) return <span className="index-status-pill neutral">Runtime unavailable</span>;
  if (runtime.resolution_error) return <span className="index-status-pill danger">Device error</span>;
  if (runtime.resolved_device?.startsWith("cuda")) return <span className="index-status-pill success">CUDA ready</span>;
  return <span className="index-status-pill neutral">CPU ready</span>;
}

export function IndexPage({ document, chunking, status, onStatusChange }: Props) {
  const [runtime, setRuntime] = useState<EmbeddingSystemStatus | null>(null);
  const [device, setDevice] = useState("auto");
  const [batchSize, setBatchSize] = useState(8);
  const [compatibility, setCompatibility] = useState<EmbeddingCompatibilityResponse | null>(null);
  const [lastRun, setLastRun] = useState<GenerateEmbeddingsResponse | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [error, setError] = useState<{ message: string; detail?: Record<string, unknown> } | null>(null);

  const model = runtime?.embedding_model ?? status?.embedding_model ?? "BAAI/bge-m3";
  const chunkCount = chunking?.summary.chunk_count ?? status?.chunk_count ?? 0;
  const embeddedCount = status?.embedded_chunk_count ?? 0;
  const complete = Boolean(status?.complete && chunkCount > 0);
  const canRun = Boolean(chunking && chunking.quality.status === "pass" && chunkCount > 0 && !busy);
  const gpuName = runtime?.cuda_devices?.[0]?.name ?? null;

  const deviceOptions = useMemo(() => {
    const options = [
      { value: "auto", label: "Auto (recommended)" },
      { value: "cpu", label: "CPU" },
    ];
    if (runtime?.cuda_available) {
      options.push({ value: "cuda", label: gpuName ? `GPU — ${gpuName}` : "GPU — CUDA" });
      runtime.cuda_devices.forEach((item) => options.push({ value: `cuda:${item.index}`, label: `GPU ${item.index} — ${item.name}` }));
    }
    return options;
  }, [runtime, gpuName]);

  useEffect(() => {
    let cancelled = false;
    setBusy("runtime");
    setError(null);
    setCompatibility(null);
    setLastRun(null);
    getEmbeddingSystemStatus()
      .then((next) => {
        if (cancelled) return;
        setRuntime(next);
        setDevice(next.configured_device || "auto");
        setBatchSize(next.embedding_batch_size || 8);
      })
      .catch((nextError) => {
        if (!cancelled) setError(errorDetail(nextError));
      })
      .finally(() => {
        if (!cancelled) setBusy((current) => current === "runtime" ? null : current);
      });
    return () => { cancelled = true; };
  }, [document.document_id]);

  useEffect(() => {
    setCompatibility(null);
    setLastRun(null);
  }, [device, batchSize, model]);

  async function refreshStatus() {
    if (!chunking) return;
    setBusy("refresh");
    setError(null);
    try {
      const next = await getEmbeddingStatus(document.document_id, model);
      onStatusChange(next);
    } catch (nextError) {
      setError(errorDetail(nextError));
    } finally {
      setBusy(null);
    }
  }

  async function runCompatibilityCheck() {
    if (!chunking) return;
    setBusy("validate");
    setError(null);
    try {
      const result = await validateEmbeddingCompatibility(document.document_id, {
        embedding_model: model,
        embedding_device: device,
        batch_size: batchSize,
        force: false,
      });
      setCompatibility(result);
    } catch (nextError) {
      setCompatibility(null);
      setError(errorDetail(nextError));
    } finally {
      setBusy(null);
    }
  }

  async function runGeneration(force: boolean) {
    if (!chunking) return;
    setBusy("generate");
    setError(null);
    try {
      const result = await generateEmbeddings(document.document_id, {
        embedding_model: model,
        embedding_device: device,
        batch_size: batchSize,
        force,
      });
      setLastRun(result);
      onStatusChange(result);
      if (!compatibility) {
        const checked = await validateEmbeddingCompatibility(document.document_id, {
          embedding_model: model,
          embedding_device: device,
          batch_size: batchSize,
          force: false,
        }).catch(() => null);
        if (checked) setCompatibility(checked);
      }
    } catch (nextError) {
      setLastRun(null);
      setError(errorDetail(nextError));
    } finally {
      setBusy(null);
    }
  }

  async function deleteIndex() {
    if (!status || !window.confirm(`Delete ${status.embedded_chunk_count} stored embeddings for ${model}?`)) return;
    setBusy("delete");
    setError(null);
    try {
      await resetEmbeddings(document.document_id, model);
      const next = await getEmbeddingStatus(document.document_id, model);
      onStatusChange(next);
      setLastRun(null);
    } catch (nextError) {
      setError(errorDetail(nextError));
    } finally {
      setBusy(null);
    }
  }

  const errorCode = typeof error?.detail?.code === "string" ? error.detail.code : null;
  const rawViolations = Array.isArray(error?.detail?.violations) ? error.detail.violations : [];

  return (
    <div className="index-page">
      <div className="index-heading">
        <div>
          <span className="eyebrow">Search readiness</span>
          <h2>Vector index</h2>
          <p>Validate the exact embedding tokenizer, generate vectors in the FastAPI backend, and persist them in PostgreSQL + pgvector.</p>
        </div>
        <div className="index-heading-actions">
          <span className={`index-status-pill ${complete ? "success" : status?.embedded_chunk_count ? "warning" : "neutral"}`}>{statusLabel(status, chunking)}</span>
          <button type="button" className="secondary-button" disabled={!chunking || Boolean(busy)} onClick={refreshStatus}>{busy === "refresh" ? "Refreshing…" : "Refresh"}</button>
        </div>
      </div>

      {!chunking && <div className="index-gate warning"><strong>Knowledge preparation is required.</strong><span>Prepare and validate knowledge chunks before creating the search index.</span></div>}
      {chunking && chunking.quality.status !== "pass" && <div className="index-gate warning"><strong>Knowledge quality is under review.</strong><span>Resolve chunk-quality signals before indexing.</span></div>}

      {error && <div className="index-error">
        <div><strong>{errorCode ?? "Embedding error"}</strong><span>{error.message}</span></div>
        {rawViolations.slice(0, 5).map((item, index) => <code key={index}>{JSON.stringify(item)}</code>)}
      </div>}

      <div className="index-metrics-grid">
        <article><span>Knowledge chunks</span><strong>{chunkCount.toLocaleString()}</strong><small>{chunking?.strategy_version ?? "not available"}</small></article>
        <article><span>Stored embeddings</span><strong>{embeddedCount.toLocaleString()} / {chunkCount.toLocaleString()}</strong><small>{status?.missing_chunk_count ?? chunkCount} missing</small></article>
        <article><span>Embedding dimension</span><strong>{status?.dimension ?? "—"}</strong><small>{model}</small></article>
        <article><span>Database state</span><strong>{complete ? "Ready" : embeddedCount > 0 ? "Partial" : "Empty"}</strong><small>PostgreSQL + pgvector</small></article>
      </div>

      <div className="index-main-grid">
        <section className="index-card">
          <div className="index-card-head"><div><span className="eyebrow">Runtime</span><h3>Embedding execution</h3></div><DeviceBadge runtime={runtime} /></div>
          <div className="index-runtime-list">
            <div><span>Model</span><strong>{model}</strong></div>
            <div><span>Configured device</span><strong>{runtime?.configured_device ?? "—"}</strong></div>
            <div><span>Resolved device</span><strong>{runtime?.resolved_device ?? "—"}</strong></div>
            <div><span>GPU</span><strong>{gpuName ?? (runtime?.cuda_available ? "CUDA available" : "Not detected")}</strong></div>
          </div>
          {runtime?.resolution_error && <div className="index-inline-error">{runtime.resolution_error}</div>}
          <p className="index-help-copy">The browser only triggers and monitors the operation. BGE-M3 still runs inside FastAPI on the selected CPU/GPU device.</p>
        </section>

        <section className="index-card">
          <div className="index-card-head"><div><span className="eyebrow">Preflight</span><h3>Exact tokenizer compatibility</h3></div>{compatibility && <span className={`index-status-pill ${compatibility.compatible ? "success" : "danger"}`}>{compatibility.compatible ? "Compatible" : "Needs split"}</span>}</div>
          {compatibility ? <>
            <div className="index-compat-summary">
              <div><span>Compatible</span><strong>{compatibility.compatible_chunk_count} / {compatibility.chunk_count}</strong></div>
              <div><span>Longest chunk</span><strong>{compatibility.max_model_token_count ?? "—"}</strong><small>model tokens</small></div>
              <div><span>Model limit</span><strong>{compatibility.model_max_seq_length ?? "—"}</strong><small>tokens</small></div>
            </div>
            {compatibility.longest_chunk_index != null && <p className="index-help-copy">Longest input: chunk {compatibility.longest_chunk_index + 1} · <code>{compatibility.longest_chunk_id}</code></p>}
            {compatibility.violations.length > 0 && <div className="index-violation-list">{compatibility.violations.map((item) => <div key={item.chunk_id}><strong>Chunk {item.chunk_index + 1}</strong><span>{item.model_token_count} / {item.model_max_seq_length} tokens</span></div>)}</div>}
          </> : <div className="index-empty-copy"><strong>Not checked yet</strong><span>Load tokenizer/config metadata and count every Stage 5 input before indexing. No model weights or vectors are loaded during this check.</span></div>}
          <button type="button" className="secondary-button" disabled={!canRun} onClick={runCompatibilityCheck}>{busy === "validate" ? "Loading tokenizer & checking…" : "Check compatibility"}</button>
        </section>
      </div>

      <section className="index-card index-controls-card">
        <div className="index-card-head"><div><span className="eyebrow">Execution settings</span><h3>CPU / GPU controls</h3></div><span className="index-muted">Advanced</span></div>
        <div className="index-control-grid">
          <label><span>Device</span><select value={device} disabled={Boolean(busy)} onChange={(event: ChangeEvent<HTMLSelectElement>) => setDevice(event.target.value)}>{deviceOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select><small>Auto prefers CUDA and safely falls back to CPU.</small></label>
          <label><span>Batch size</span><input type="number" min={1} max={512} value={batchSize} disabled={Boolean(busy)} onChange={(event: ChangeEvent<HTMLInputElement>) => setBatchSize(Math.max(1, Math.min(512, Number(event.target.value) || 1)))} /><small>Start at 8 for BGE-M3; lower it if GPU memory is constrained.</small></label>
        </div>
      </section>

      <section className="index-card index-action-card">
        <div>
          <span className="eyebrow">Index operation</span>
          <h3>{complete ? "Vector index is ready" : "Generate document embeddings"}</h3>
          <p>{busy === "generate" ? `BGE-M3 is encoding ${chunkCount} chunks on ${device}. This is a real backend operation; the UI does not show a fake percentage.` : complete ? `${embeddedCount} embeddings are stored and ready for dense retrieval.` : "The backend validates tokenizer limits again before writing any vector, so incompatible chunks are never silently truncated."}</p>
          {lastRun && <div className="index-run-result"><span>Generated <strong>{lastRun.generated_count}</strong></span><span>Reused <strong>{lastRun.reused_count}</strong></span><span>Device <strong>{lastRun.resolved_device}</strong></span></div>}
        </div>
        <div className="index-action-buttons">
          <button type="button" className="primary-button" disabled={!canRun} onClick={() => runGeneration(complete)}>{busy === "generate" ? <><span className="index-spinner" /> Generating…</> : complete ? "Regenerate embeddings" : "Generate embeddings"}</button>
          {embeddedCount > 0 && <button type="button" className="secondary-button danger" disabled={Boolean(busy)} onClick={deleteIndex}>{busy === "delete" ? "Deleting…" : "Delete embeddings"}</button>}
        </div>
      </section>
    </div>
  );
}
