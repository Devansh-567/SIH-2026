import type { AnalysisResultJSON, SpectrogramJSON, UploadResponse } from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL || "/api";

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
  filenameHint = "rf_analysis_report"
): Promise<void> {
  const res = await fetch(`${BASE}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, analysis, filename_hint: filenameHint }),
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
