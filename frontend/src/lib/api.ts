import type {
  AnalysisResultJSON, AnnotationEntry, BatchAnalyzeResponse, CompareResult, FeedbackEntry,
  HistoryListResponse, SampleListResponse, SampleLoadResponse, SimilarSignalsResponse,
  SpectrogramJSON, UploadResponse,
} from "./types";

const BASE = "/api";

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore parse failure, fall back to statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

/**
 * Uploads one or more files in a single request. Pass both halves of a
 * SigMF pair together (e.g. [dataFile, metaFile]) so the backend can
 * auto-pair them by filename stem into one recording -- see
 * rfplatform/api/main.py::upload_files for the pairing logic. A single
 * standalone file (.wav, .cf32, etc.) works the same way as a one-element
 * array.
 */
export async function uploadFiles(files: File[]): Promise<UploadResponse> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await fetch(`${BASE}/upload`, { method: "POST", body: form });
  return asJson(res);
}

export async function analyzeFile(
  fileId: string,
  opts: { sampleRateHz?: number; centerFreqHz?: number; overrides?: Record<string, unknown> } = {}
): Promise<AnalysisResultJSON> {
  const res = await fetch(`${BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_id: fileId,
      sample_rate_hz: opts.sampleRateHz ?? null,
      center_freq_hz: opts.centerFreqHz ?? null,
      overrides: opts.overrides ?? {},
    }),
  });
  return asJson(res);
}

export async function fetchSpectrogram(
  fileId: string,
  opts: { sampleRateHz?: number; timeBins?: number; freqBins?: number } = {}
): Promise<SpectrogramJSON> {
  const res = await fetch(`${BASE}/spectrogram`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_id: fileId,
      sample_rate_hz: opts.sampleRateHz ?? null,
      time_bins: opts.timeBins ?? 220,
      freq_bins: opts.freqBins ?? 220,
    }),
  });
  return asJson(res);
}

export async function deleteUpload(fileId: string): Promise<void> {
  await fetch(`${BASE}/upload/${fileId}`, { method: "DELETE" });
}

const EXPORT_FILENAME_EXTENSIONS: Record<string, string> = {
  json: "json", csv: "csv", pdf: "pdf", sigmf: "sigmf-meta",
};

/**
 * Requests a report export and triggers a real browser download -- the
 * backend returns the file with a Content-Disposition header; this just
 * turns that response into a client-side download via a temporary <a>.
 */
export async function exportReport(
  analysis: unknown,
  format: "json" | "csv" | "pdf" | "sigmf",
  filenameHint = "rf_analysis_report",
  analysisId?: string
): Promise<void> {
  const res = await fetch(`${BASE}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, analysis: analysisId ? undefined : analysis, analysis_id: analysisId, filename_hint: filenameHint }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${filenameHint}.${EXPORT_FILENAME_EXTENSIONS[format]}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// --- History / batch / comparison / feedback / annotations / similarity ---

export async function listHistory(limit = 50, offset = 0): Promise<HistoryListResponse> {
  const res = await fetch(`${BASE}/analyses?limit=${limit}&offset=${offset}`);
  return asJson(res);
}

export async function getHistoryEntry(analysisId: string): Promise<AnalysisResultJSON> {
  const res = await fetch(`${BASE}/analyses/${analysisId}`);
  return asJson(res);
}

export async function deleteHistoryEntry(analysisId: string): Promise<void> {
  await fetch(`${BASE}/analyses/${analysisId}`, { method: "DELETE" });
}

export async function compareHistoryEntries(idA: string, idB: string): Promise<CompareResult> {
  const res = await fetch(`${BASE}/analyses/compare?a=${encodeURIComponent(idA)}&b=${encodeURIComponent(idB)}`);
  return asJson(res);
}

export async function batchAnalyze(fileIds: string[], sampleRateHz?: number): Promise<BatchAnalyzeResponse> {
  const res = await fetch(`${BASE}/batch/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_ids: fileIds, sample_rate_hz: sampleRateHz ?? null }),
  });
  return asJson(res);
}

export async function submitFeedback(
  analysisId: string, parameterName: string, correctedValue: unknown, note?: string
): Promise<{ feedback_id: number }> {
  const res = await fetch(`${BASE}/analyses/${analysisId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parameter_name: parameterName, corrected_value: correctedValue, note: note ?? null }),
  });
  return asJson(res);
}

export async function getFeedback(analysisId: string): Promise<{ feedback: FeedbackEntry[] }> {
  const res = await fetch(`${BASE}/analyses/${analysisId}/feedback`);
  return asJson(res);
}

export async function addAnnotation(
  analysisId: string, opts: { startS: number; endS?: number; freqHz?: number; label?: string; note?: string }
): Promise<{ annotation_id: number }> {
  const res = await fetch(`${BASE}/analyses/${analysisId}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start_s: opts.startS, end_s: opts.endS ?? null, freq_hz: opts.freqHz ?? null,
      label: opts.label ?? null, note: opts.note ?? null,
    }),
  });
  return asJson(res);
}

export async function listAnnotations(analysisId: string): Promise<{ annotations: AnnotationEntry[] }> {
  const res = await fetch(`${BASE}/analyses/${analysisId}/annotations`);
  return asJson(res);
}

export async function deleteAnnotation(annotationId: number): Promise<void> {
  await fetch(`${BASE}/annotations/${annotationId}`, { method: "DELETE" });
}

export async function getSimilarSignals(analysisId: string, signalIndex = 0, topK = 5): Promise<SimilarSignalsResponse> {
  const res = await fetch(`${BASE}/analyses/${analysisId}/similar?signal_index=${signalIndex}&top_k=${topK}`);
  return asJson(res);
}

// --- Demo sample catalog ---

export async function listSamples(): Promise<SampleListResponse> {
  const res = await fetch(`${BASE}/samples`);
  return asJson(res);
}

export async function loadSample(sampleId: string): Promise<SampleLoadResponse> {
  const res = await fetch(`${BASE}/samples/${sampleId}/load`, { method: "POST" });
  return asJson(res);
}
