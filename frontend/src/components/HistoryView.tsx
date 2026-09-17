import { useEffect, useState } from "react";
import { deleteHistoryEntry, listHistory } from "../lib/api";
import type { HistoryEntry, Status } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function fmtHz(hz: number | null): string {
  if (hz === null) return "\u2014";
  if (hz >= 1e6) return `${(hz / 1e6).toFixed(3)} MHz`;
  if (hz >= 1e3) return `${(hz / 1e3).toFixed(1)} kHz`;
  return `${hz.toFixed(0)} Hz`;
}

export function HistoryView({
  onOpen, onCompareSelectionChange,
}: {
  onOpen: (analysisId: string) => void;
  onCompareSelectionChange: (ids: string[]) => void;
}) {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  const refresh = () => {
    setError(null);
    listHistory(100).then((r) => setEntries(r.analyses)).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refresh();
  }, []);

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-2);
      onCompareSelectionChange(next);
      return next;
    });
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await deleteHistoryEntry(id);
    refresh();
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
        <div>
          <h2 style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, margin: 0, color: "var(--text-primary)" }}>
            Analysis History
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 4 }}>
            {selected.length > 0
              ? `${selected.length} selected for comparison${selected.length === 2 ? " \u2014 open the Compare tab" : ", pick one more"}`
              : "Click a row to reopen it. Select two rows (checkboxes) to compare."}
          </div>
        </div>
        <button onClick={refresh} style={{ padding: "6px 12px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-hairline-bright)", background: "var(--bg-panel-raised)", color: "var(--text-secondary)", fontSize: 12, cursor: "pointer" }}>
          Refresh
        </button>
      </div>

      {error && (
        <div style={{ padding: 12, borderRadius: "var(--radius-md)", background: "rgba(255,77,94,0.1)", border: "1px solid rgba(255,77,94,0.3)", color: "var(--semantic-error)", fontSize: 12, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {entries === null ? (
        <div style={{ color: "var(--text-tertiary)", fontSize: 13 }}>Loading\u2026</div>
      ) : entries.length === 0 ? (
        <div className="panel" style={{ padding: 32, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13, borderStyle: "dashed" }}>
          No analyses yet. Run one from the Analyze tab and it will show up here.
        </div>
      ) : (
        <div className="panel" style={{ overflow: "hidden" }}>
          <table className="mono" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
            <thead>
              <tr>
                {["", "When", "File", "Format", "Sample Rate", "Center Freq", "Modulation", "Signals", ""].map((h) => (
                  <th key={h} style={{ textAlign: "left", padding: "10px 12px", color: "var(--text-tertiary)", fontWeight: 500, borderBottom: "1px solid var(--border-hairline)", fontSize: 10.5, textTransform: "uppercase" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => onOpen(row.id)}
                  style={{ cursor: "pointer", background: selected.includes(row.id) ? "var(--status-estimated-dim)" : "transparent" }}
                >
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)" }} onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.includes(row.id)} onChange={() => toggleSelect(row.id)} />
                  </td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-secondary)" }}>{fmtDate(row.created_at)}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-secondary)", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {row.input_file?.split("/").pop() ?? "\u2014"}
                  </td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-tertiary)" }}>{row.source_format ?? "\u2014"}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-secondary)" }}>{fmtHz(row.sample_rate_hz)}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-secondary)" }}>{fmtHz(row.center_freq_hz)}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)" }}>
                    {row.primary_modulation ? (
                      <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{row.primary_modulation}</span>
                        {row.primary_status && <StatusBadge status={row.primary_status as Status} />}
                      </span>
                    ) : "\u2014"}
                  </td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)", color: "var(--text-secondary)" }}>{row.num_signals}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-hairline)" }} onClick={(e) => e.stopPropagation()}>
                    <button onClick={(e) => handleDelete(row.id, e)} style={{ background: "none", border: "none", color: "var(--text-tertiary)", cursor: "pointer", fontSize: 13 }} title="Delete">
                      &times;
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
