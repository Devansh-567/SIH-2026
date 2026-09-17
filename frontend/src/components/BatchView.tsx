import { useState } from "react";
import { batchAnalyze, uploadFiles } from "../lib/api";
import type { BatchAnalyzeResponse } from "../lib/types";
import { FileDropzone } from "./FileDropzone";

export function BatchView({ onOpenAnalysis }: { onOpenAnalysis: (analysisId: string) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [sampleRateHz, setSampleRateHz] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchAnalyzeResponse | null>(null);
  const [progress, setProgress] = useState<string>("");

  const handleFilesSelected = (selected: File[]) => {
    setFiles((prev) => [...prev, ...selected]);
    setResult(null);
    setError(null);
  };

  const removeFile = (idx: number) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const runBatch = async () => {
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fileIds: string[] = [];
      for (let i = 0; i < files.length; i++) {
        setProgress(`Uploading ${i + 1}/${files.length}: ${files[i].name}`);
        const res = await uploadFiles([files[i]]);
        fileIds.push(res.uploads[0].file_id);
      }
      setProgress(`Analyzing ${fileIds.length} file(s)\u2026`);
      const sr = sampleRateHz ? Number(sampleRateHz) : undefined;
      const batchResult = await batchAnalyze(fileIds, sr);
      setResult(batchResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setProgress("");
    }
  };

  const reset = () => {
    setFiles([]);
    setResult(null);
    setError(null);
  };

  return (
    <div>
      <h2 style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, margin: "0 0 4px 0", color: "var(--text-primary)" }}>
        Batch Analysis
      </h2>
      <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginBottom: 16 }}>
        Analyze up to 20 recordings in one run. Each file is analyzed independently and saved to history --
        one failure doesn't stop the rest.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 18 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <FileDropzone onFilesSelected={handleFilesSelected} selectedNames={[]} disabled={busy} />

          {files.length > 0 && (
            <div className="panel" style={{ padding: 12, maxHeight: 260, overflowY: "auto" }}>
              {files.map((f, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0", fontSize: 12 }}>
                  <span className="mono" style={{ color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
                  <button onClick={() => removeFile(i)} disabled={busy} style={{ background: "none", border: "none", color: "var(--text-tertiary)", cursor: "pointer" }}>&times;</button>
                </div>
              ))}
            </div>
          )}

          <div className="panel" style={{ padding: "12px 14px" }}>
            <label style={{ display: "block", fontSize: 10.5, color: "var(--text-tertiary)", marginBottom: 3 }}>
              Sample rate override (Hz, applies to all files without their own metadata)
            </label>
            <input
              type="number" placeholder="auto-detect per file" value={sampleRateHz}
              onChange={(e) => setSampleRateHz(e.target.value)} disabled={busy}
              style={{ width: "100%", padding: "6px 8px", background: "var(--bg-inset)", border: "1px solid var(--border-hairline)", borderRadius: "var(--radius-sm)", color: "var(--text-primary)", fontSize: 12, fontFamily: "var(--font-mono)" }}
            />
          </div>

          <button
            onClick={runBatch} disabled={busy || files.length === 0}
            style={{
              padding: "10px 14px", borderRadius: "var(--radius-md)", border: "none",
              background: busy || files.length === 0 ? "var(--bg-panel-raised)" : "var(--status-estimated)",
              color: busy || files.length === 0 ? "var(--text-tertiary)" : "#0b1620",
              fontWeight: 500, fontSize: 13, cursor: busy || files.length === 0 ? "default" : "pointer",
              fontFamily: "var(--font-display)",
            }}
          >
            {busy ? (progress || "Working\u2026") : `\u25B6 Analyze ${files.length || ""} File${files.length === 1 ? "" : "s"}`}
          </button>

          {result && (
            <button onClick={reset} style={{ padding: "8px 12px", borderRadius: "var(--radius-md)", border: "1px solid var(--border-hairline-bright)", background: "var(--bg-panel-raised)", color: "var(--text-secondary)", fontSize: 12, cursor: "pointer" }}>
              New Batch
            </button>
          )}

          {error && (
            <div style={{ padding: 12, borderRadius: "var(--radius-md)", background: "rgba(255,77,94,0.1)", border: "1px solid rgba(255,77,94,0.3)", color: "var(--semantic-error)", fontSize: 12 }}>
              {error}
            </div>
          )}
        </div>

        <div>
          {!result ? (
            <div className="panel" style={{ padding: 32, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13, borderStyle: "dashed", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
              Results will appear here once the batch completes.
            </div>
          ) : (
            <div className="panel" style={{ overflow: "hidden" }}>
              <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border-hairline)", display: "flex", gap: 16, fontSize: 12.5 }}>
                <span style={{ color: "var(--status-detected)" }}>{result.num_ok} succeeded</span>
                {result.num_failed > 0 && <span style={{ color: "var(--semantic-error)" }}>{result.num_failed} failed</span>}
              </div>
              <table className="mono" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr>
                    {["Status", "Modulation", "Signals", "Detail"].map((h) => (
                      <th key={h} style={{ textAlign: "left", padding: "8px 14px", color: "var(--text-tertiary)", fontSize: 10, borderBottom: "1px solid var(--border-hairline)" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.results.map((r, i) => (
                    <tr
                      key={i}
                      onClick={() => r.analysis_id && onOpenAnalysis(r.analysis_id)}
                      style={{ cursor: r.analysis_id ? "pointer" : "default" }}
                    >
                      <td style={{ padding: "8px 14px", borderBottom: "1px solid var(--border-hairline)", color: r.status === "ok" ? "var(--status-detected)" : "var(--semantic-error)" }}>
                        {r.status === "ok" ? "\u2713 ok" : "\u2715 error"}
                      </td>
                      <td style={{ padding: "8px 14px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-primary)" }}>{r.modulation ?? "\u2014"}</td>
                      <td style={{ padding: "8px 14px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-secondary)" }}>{r.num_signals ?? "\u2014"}</td>
                      <td style={{ padding: "8px 14px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-tertiary)", fontSize: 11 }}>{r.error ?? "click to open"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
