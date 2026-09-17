import { useEffect, useState } from "react";
import { compareHistoryEntries, listHistory } from "../lib/api";
import type { CompareResult, HistoryEntry } from "../lib/types";

const STATUS_COLOR: Record<string, string> = {
  same: "var(--text-tertiary)",
  changed: "var(--status-inferred)",
  only_in_a: "var(--status-estimated)",
  only_in_b: "var(--status-hypothesized)",
};

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return "\u2014";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  return String(v);
}

export function CompareView({ initialSelection }: { initialSelection: string[] }) {
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [idA, setIdA] = useState<string>(initialSelection[0] ?? "");
  const [idB, setIdB] = useState<string>(initialSelection[1] ?? "");
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listHistory(100).then((r) => setHistory(r.analyses)).catch(() => {});
  }, []);

  useEffect(() => {
    if (initialSelection[0]) setIdA(initialSelection[0]);
    if (initialSelection[1]) setIdB(initialSelection[1]);
  }, [initialSelection]);

  const runCompare = async () => {
    if (!idA || !idB) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await compareHistoryEntries(idA, idB));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const labelFor = (id: string) => {
    const entry = history.find((h) => h.id === id);
    return entry ? `${entry.primary_modulation ?? "?"} \u2014 ${entry.input_file?.split("/").pop() ?? id.slice(0, 8)}` : id;
  };

  return (
    <div>
      <h2 style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, margin: "0 0 4px 0", color: "var(--text-primary)" }}>
        Compare Analyses
      </h2>
      <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginBottom: 16 }}>
        Pick two entries from history (or select them in the History tab first) to see a parameter-by-parameter diff.
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 18, alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <label style={{ display: "block", fontSize: 10.5, color: "var(--status-estimated)", marginBottom: 4 }}>Recording A</label>
          <select value={idA} onChange={(e) => setIdA(e.target.value)} style={selectStyle}>
            <option value="">select an analysis\u2026</option>
            {history.map((h) => <option key={h.id} value={h.id}>{labelFor(h.id)}</option>)}
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={{ display: "block", fontSize: 10.5, color: "var(--status-hypothesized)", marginBottom: 4 }}>Recording B</label>
          <select value={idB} onChange={(e) => setIdB(e.target.value)} style={selectStyle}>
            <option value="">select an analysis\u2026</option>
            {history.map((h) => <option key={h.id} value={h.id}>{labelFor(h.id)}</option>)}
          </select>
        </div>
        <button
          onClick={runCompare} disabled={busy || !idA || !idB}
          style={{ padding: "9px 18px", borderRadius: "var(--radius-md)", border: "none", background: busy || !idA || !idB ? "var(--bg-panel-raised)" : "var(--status-estimated)", color: busy || !idA || !idB ? "var(--text-tertiary)" : "#0b1620", fontWeight: 500, fontSize: 13, cursor: busy || !idA || !idB ? "default" : "pointer" }}
        >
          Compare
        </button>
      </div>

      {error && (
        <div style={{ padding: 12, borderRadius: "var(--radius-md)", background: "rgba(255,77,94,0.1)", border: "1px solid rgba(255,77,94,0.3)", color: "var(--semantic-error)", fontSize: 12, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {result && (
        <div className="panel" style={{ overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border-hairline)", fontSize: 12.5, color: "var(--text-secondary)" }}>
            <span style={{ color: "var(--status-inferred)", fontWeight: 600 }}>{result.num_parameters_changed}</span> of{" "}
            <span style={{ color: "var(--text-primary)" }}>{result.num_parameters_compared}</span> primary-signal parameters differ
          </div>
          <table className="mono" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["Parameter", "A", "B", ""].map((h) => (
                  <th key={h} style={{ textAlign: "left", padding: "8px 14px", color: "var(--text-tertiary)", fontSize: 10, borderBottom: "1px solid var(--border-hairline)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.parameters.map((p) => (
                <tr key={p.name}>
                  <td style={{ padding: "7px 14px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-primary)" }}>{p.name}</td>
                  <td style={{ padding: "7px 14px", borderBottom: "1px solid var(--border-hairline)", color: p.status === "changed" ? "var(--status-estimated)" : "var(--text-secondary)" }}>{fmtVal(p.value_a)}</td>
                  <td style={{ padding: "7px 14px", borderBottom: "1px solid var(--border-hairline)", color: p.status === "changed" ? "var(--status-hypothesized)" : "var(--text-secondary)" }}>{fmtVal(p.value_b)}</td>
                  <td style={{ padding: "7px 14px", borderBottom: "1px solid var(--border-hairline)", color: STATUS_COLOR[p.status], fontSize: 10.5 }}>{p.status.replace(/_/g, " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  width: "100%", padding: "8px 10px", background: "var(--bg-inset)", border: "1px solid var(--border-hairline)",
  borderRadius: "var(--radius-sm)", color: "var(--text-primary)", fontSize: 12.5, fontFamily: "var(--font-mono)",
};
