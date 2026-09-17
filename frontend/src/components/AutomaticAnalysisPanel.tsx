import type { Parameter } from "../lib/types";
import { ParameterCard } from "./ParameterCard";

/* Findings are presented as a ledger: hairline-separated rows in a fixed
   column rhythm, so values line up and can be scanned vertically. A grid
   of identical cards would scatter the numbers and make comparison
   harder — measurements belong in a log. */
export function AutomaticAnalysisPanel({ parameters, analysisId }: { parameters: Parameter[]; analysisId?: string }) {
  const certain = parameters.filter((p) => p.status === "DETECTED" || p.status === "ESTIMATED").length;
  return (
    <div style={{ marginTop: 18 }}>
      <SectionHeader
        title="Findings"
        note={`${certain} of ${parameters.length} measured directly — the rest are inferred, and say so`}
      />
      <div className="panel">
        <div className="ledger-row" style={{ gridTemplateColumns: "minmax(150px,1.1fr) minmax(130px,1fr) 108px 74px 22px", gap: 14, padding: "8px 16px", background: "var(--bg-panel-raised)" }}>
          {["Parameter", "Value", "Basis", "Confidence", ""].map((h, i) => (
            <span key={h} style={{ fontSize: 10.5, color: "var(--text-tertiary)", textAlign: i === 3 ? "right" : "left" }}>{h}</span>
          ))}
        </div>
        {parameters.map((p) => <ParameterCard key={p.name} param={p} analysisId={analysisId} />)}
      </div>
    </div>
  );
}

export function SectionHeader({ title, subtitle, note }: { title: string; subtitle?: string; note?: string }) {
  return (
    <div style={{ marginBottom: 9, marginTop: 20 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 11 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, margin: 0, color: "var(--text-primary)", letterSpacing: "-0.005em" }}>{title}</h2>
        {subtitle && <span className="num" style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>{subtitle}</span>}
        <span style={{ flex: 1, height: 1, background: "var(--border-hairline)" }} />
      </div>
      {note && <div style={{ fontSize: 11.5, color: "var(--text-tertiary)", marginTop: 3 }}>{note}</div>}
    </div>
  );
}
