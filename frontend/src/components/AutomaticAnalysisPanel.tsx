import type { Parameter } from "../lib/types";
import { ParameterCard } from "./ParameterCard";

export function AutomaticAnalysisPanel({ parameters, analysisId }: { parameters: Parameter[]; analysisId?: string }) {
  return (
    <div>
      <SectionHeader title="Automatic Analysis" subtitle={`${parameters.length} parameters extracted`} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
          gap: 10,
        }}
      >
        {parameters.map((p) => (
          <ParameterCard key={p.name} param={p} analysisId={analysisId} />
        ))}
      </div>
    </div>
  );
}

export function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10, marginTop: 22 }}>
      <h2 style={{ fontFamily: "var(--font-display)", fontSize: 15, fontWeight: 600, margin: 0, color: "var(--text-primary)" }}>
        {title}
      </h2>
      {subtitle && (
        <span className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
          {subtitle}
        </span>
      )}
      <div style={{ flex: 1, height: 1, background: "var(--border-hairline)" }} />
    </div>
  );
}
