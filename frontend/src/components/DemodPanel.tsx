import type { DemodResultJSON } from "../lib/types";
import { SectionHeader } from "./AutomaticAnalysisPanel";

function Gauge({ label, value, max, good }: { label: string; value: number; max: number; good: "low" | "high" }) {
  const pct = Math.max(0, Math.min(1, value / max));
  const quality = good === "low" ? 1 - pct : pct;
  const color = quality > 0.7 ? "var(--status-detected)" : quality > 0.4 ? "var(--status-inferred)" : "var(--semantic-error)";
  return (
    <div style={{ flex: 1, minWidth: 120 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4 }}>
        <span>{label}</span>
        <span className="mono" style={{ color }}>{value.toFixed(2)}{good === "low" ? "%" : ""}</span>
      </div>
      <div style={{ height: 5, borderRadius: 3, background: "var(--bg-inset)", border: "1px solid var(--border-hairline)", overflow: "hidden" }}>
        <div style={{ width: `${pct * 100}%`, height: "100%", background: color, transition: "width 300ms" }} />
      </div>
    </div>
  );
}

export function DemodPanel({ demod }: { demod: DemodResultJSON | null }) {
  if (!demod) {
    return (
      <div>
        <SectionHeader title="Demodulation" />
        <EmptyState text="No demodulation was attempted -- modulation confidence was below the usable threshold, or no symbol-rate estimate was available." />
      </div>
    );
  }

  return (
    <div>
      <SectionHeader title="Demodulation" subtitle={demod.modulation.toUpperCase()} />
      <div className="panel" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <Gauge label="EVM" value={demod.evm_percent} max={50} good="low" />
          <Gauge label="Lock quality" value={demod.lock_quality * 100} max={100} good="high" />
          <div style={{ minWidth: 120 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4 }}>Recovered bits</div>
            <div className="mono" style={{ fontSize: 13, color: "var(--text-primary)" }}>
              {demod.num_bits.toLocaleString()}
            </div>
          </div>
          <div style={{ minWidth: 120 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4 }}>Samples/symbol</div>
            <div className="mono" style={{ fontSize: 13, color: "var(--text-primary)" }}>
              {demod.samples_per_symbol_used}
            </div>
          </div>
        </div>

        <div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 6 }}>Bit preview (first 64)</div>
          <div
            className="mono"
            style={{
              background: "var(--bg-inset)",
              border: "1px solid var(--border-hairline)",
              borderRadius: "var(--radius-md)",
              padding: 10,
              fontSize: 12,
              wordBreak: "break-all",
              color: "var(--status-estimated)",
              lineHeight: 1.6,
            }}
          >
            {demod.bits_preview.join("")}
          </div>
        </div>

        {demod.notes.length > 0 && (
          <div>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4 }}>Method notes</div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>
              {demod.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div
      className="panel"
      style={{
        padding: 20,
        color: "var(--text-tertiary)",
        fontSize: 12.5,
        lineHeight: 1.6,
        borderStyle: "dashed",
      }}
    >
      {text}
    </div>
  );
}
