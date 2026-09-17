import { useState } from "react";
import { exportReport } from "../lib/api";
import type { AnalysisResultJSON } from "../lib/types";

const FORMATS: { key: "json" | "csv" | "pdf" | "sigmf"; label: string }[] = [
  { key: "pdf", label: "PDF" },
  { key: "json", label: "JSON" },
  { key: "csv", label: "CSV" },
  { key: "sigmf", label: "SigMF" },
];

export function ReportExportPanel({ result, filenameHint }: { result: AnalysisResultJSON; filenameHint: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async (format: "json" | "csv" | "pdf" | "sigmf") => {
    setBusy(format);
    setError(null);
    try {
      await exportReport(result, format, filenameHint);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="panel" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 9, fontWeight: 500 }}>
        Save a report
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {FORMATS.map((f) => (
          <button
            key={f.key}
            onClick={() => handleExport(f.key)}
            disabled={busy !== null}
            style={{
              padding: "7px 8px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border-hairline-bright)",
              background: "var(--bg-panel-raised)",
              color: busy === f.key ? "var(--status-detected)" : "var(--text-secondary)",
              fontSize: 11.5,
              fontFamily: "var(--font-mono)",
              cursor: busy !== null ? "default" : "pointer",
              opacity: busy !== null && busy !== f.key ? 0.5 : 1,
            }}
          >
            {busy === f.key ? "\u2026" : f.label}
          </button>
        ))}
      </div>
      {error && (
        <div style={{ marginTop: 8, fontSize: 10.5, color: "var(--semantic-error)", lineHeight: 1.4 }}>
          {error}
        </div>
      )}
    </div>
  );
}
