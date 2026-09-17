import type { Status } from "../lib/types";

const STATUS_META: Record<Status, { color: string; dim: string; label: string }> = {
  DETECTED: { color: "var(--status-detected)", dim: "var(--status-detected-dim)", label: "DETECTED" },
  ESTIMATED: { color: "var(--status-estimated)", dim: "var(--status-estimated-dim)", label: "ESTIMATED" },
  INFERRED: { color: "var(--status-inferred)", dim: "var(--status-inferred-dim)", label: "INFERRED" },
  HYPOTHESIZED: { color: "var(--status-hypothesized)", dim: "var(--status-hypothesized-dim)", label: "HYPOTHESIZED" },
  UNKNOWN: { color: "var(--status-unknown)", dim: "var(--status-unknown-dim)", label: "UNKNOWN" },
};

export function StatusBadge({ status }: { status: Status }) {
  const meta = STATUS_META[status];
  return (
    <span
      className="mono"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "1px 0",
        borderRadius: 0,
        fontSize: 10.5,
        fontWeight: 500,
        letterSpacing: "0.005em",
        color: meta.color,
        background: "transparent",
        border: "none",
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: meta.color, flexShrink: 0 }} />
      {meta.label}
    </span>
  );
}

export function statusColor(status: Status): string {
  return STATUS_META[status].color;
}
