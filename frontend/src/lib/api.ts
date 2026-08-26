import type { AnalysisResultJSON, SpectrogramJSON } from "./types";

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

export async function uploadFile(file: File): Promise<{ file_id: string; filename: string; size_bytes: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload`, { method: "POST", body: form });
  return asJson(res);
}

export async function analyzeFile(
  fileId: string,
  opts: { sampleRateHz?: number; overrides?: Record<string, unknown> } = {}
): Promise<AnalysisResultJSON> {
  const res = await fetch(`${BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_id: fileId,
      sample_rate_hz: opts.sampleRateHz ?? null,
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
