import { useEffect, useState } from "react";
import { getSimilarSignals } from "../lib/api";
import type { SimilarSignalEntry } from "../lib/types";

export function SimilarSignalsPanel({ analysisId, onOpen }: { analysisId: string; onOpen: (analysisId: string) => void }) {
  const [results, setResults] = useState<SimilarSignalEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setResults(null);
    setError(null);
    getSimilarSignals(analysisId, 0, 5)
      .then((r) => setResults(r.results))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [analysisId]);

  if (error) return null; // quietly hide -- e.g. no fingerprint available, not worth alarming the analyst

  return (
    <div className="panel" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 9, fontWeight: 500 }}>
        Similar signals seen before
      </div>
      {results === null ? (
        <div style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>Searching\u2026</div>
      ) : results.length === 0 ? (
        <div style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>No other analyzed signals yet.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {results.map((r) => (
            <div
              key={r.signal_id}
              onClick={() => onOpen(r.analysis_id)}
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", padding: "4px 0" }}
            >
              <span className="mono" style={{ fontSize: 12, color: "var(--text-primary)" }}>
                {r.modulation ?? "unknown"}
              </span>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)" }}>
                distance {r.distance.toFixed(3)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
