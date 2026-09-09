import { useState } from "react";
import type { Parameter } from "../lib/types";
import { StatusBadge } from "./StatusBadge";
import { ConfidenceBar } from "./ConfidenceBar";

function formatValue(value: unknown, unit: string | null): string {
  if (value === null || value === undefined) return "\u2014";
  if (typeof value === "number") {
    const formatted = Number.isInteger(value) ? value.toString() : value.toFixed(3);
    return unit ? `${formatted} ${unit}` : formatted;
  }
  return String(value);
}

function prettyName(name: string): string {
  return name
    .replace(/_hz$/, "")
    .replace(/_db$/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ParameterCard({ param }: { param: Parameter }) {
  const [expanded, setExpanded] = useState(false);
  const hasEvidence = param.evidence.length > 0;
  const hasAlternatives = param.alternatives.length > 0;
  const canExpand = hasEvidence || hasAlternatives;

  return (
    <div
      className="panel"
      style={{
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        cursor: canExpand ? "pointer" : "default",
      }}
      onClick={() => canExpand && setExpanded((e) => !e)}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", letterSpacing: "0.04em", textTransform: "uppercase" }}>
            {prettyName(param.name)}
          </div>
          <div className="mono" style={{ fontSize: 18, fontWeight: 600, marginTop: 2, color: "var(--text-primary)" }}>
            {formatValue(param.value, param.unit)}
          </div>
        </div>
        <StatusBadge status={param.status} />
      </div>

      {param.status !== "UNKNOWN" && param.status !== "DETECTED" && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ConfidenceBar confidence={param.confidence} />
          <span className="mono" style={{ fontSize: 11, color: "var(--text-secondary)", minWidth: 34, textAlign: "right" }}>
            {(param.confidence * 100).toFixed(0)}%
          </span>
        </div>
      )}

      {canExpand && (
        <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ transform: expanded ? "rotate(90deg)" : "none", transition: "transform 150ms", display: "inline-block" }}>
            &#8250;
          </span>
          {expanded ? "hide evidence" : `why? (${param.evidence.length} evidence item${param.evidence.length === 1 ? "" : "s"})`}
        </div>
      )}

      {expanded && (
        <div style={{ borderTop: "1px solid var(--border-hairline)", paddingTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
          {hasAlternatives && (
            <div>
              <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Alternative hypotheses
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {param.alternatives.map((alt, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }} className="mono">
                    <span style={{ color: "var(--text-secondary)" }}>{String(alt.value)}</span>
                    <span style={{ color: "var(--text-tertiary)" }}>{(alt.confidence * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {hasEvidence && (
            <div>
              <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Evidence
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {param.evidence.map((ev, i) => (
                  <div key={i} style={{ fontSize: 12, lineHeight: 1.45 }}>
                    <span className="mono" style={{ color: "var(--status-estimated)", fontSize: 10.5 }}>
                      {ev.source}
                    </span>
                    <div style={{ color: "var(--text-secondary)" }}>{ev.description}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
