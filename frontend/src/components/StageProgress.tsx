import type { StageInfo } from "../lib/types";

const ICON: Record<StageInfo["status"], { symbol: string; color: string }> = {
  ok: { symbol: "\u2713", color: "var(--status-detected)" },
  skipped: { symbol: "\u2013", color: "var(--text-tertiary)" },
  error: { symbol: "\u2715", color: "var(--semantic-error)" },
};

function prettyStageName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function StageProgress({ stages }: { stages: StageInfo[] }) {
  return (
    <div className="panel" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 9, fontWeight: 500 }}>
        Pipeline stages
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {stages.map((s, i) => {
          const icon = ICON[s.status];
          return (
            <div
              key={s.name}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 0",
                position: "relative",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 14 }}>
                <span
                  className="mono"
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: "50%",
                    border: `1.5px solid ${icon.color}`,
                    color: icon.color,
                    fontSize: 9,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                    background: "var(--bg-panel)",
                    zIndex: 1,
                  }}
                >
                  {icon.symbol}
                </span>
                {i < stages.length - 1 && (
                  <div style={{ width: 1, flex: 1, minHeight: 8, background: "var(--border-hairline)" }} />
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0, paddingBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 12, color: s.status === "skipped" ? "var(--text-tertiary)" : "var(--text-secondary)" }}>
                    {prettyStageName(s.name)}
                  </span>
                  <span className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)" }}>
                    {(s.duration_s * 1000).toFixed(0)}ms
                  </span>
                </div>
                {(s.status === "skipped" || s.status === "error") && typeof s.detail?.reason === "string" && (
                  <div style={{ fontSize: 10.5, color: s.status === "error" ? "var(--semantic-error)" : "var(--text-tertiary)", marginTop: 2, lineHeight: 1.4 }}>
                    {s.detail.reason}
                  </div>
                )}
                {s.status === "error" && typeof s.detail?.error === "string" && (
                  <div style={{ fontSize: 10.5, color: "var(--semantic-error)", marginTop: 2, lineHeight: 1.4 }}>
                    {s.detail.error}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
