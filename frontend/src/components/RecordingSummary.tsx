import type { RecordingSummary as RecordingSummaryT } from "../lib/types";

function Row({ label, value, dim }: { label: string; value: string; dim?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "4px 0" }}>
      <span style={{ color: "var(--text-tertiary)" }}>{label}</span>
      <span className="mono" style={{ color: dim ? "var(--text-tertiary)" : "var(--text-primary)" }}>
        {value}
      </span>
    </div>
  );
}

function formatHz(hz: number | null): string {
  if (hz === null) return "\u2014";
  if (hz >= 1e6) return `${(hz / 1e6).toFixed(3)} MHz`;
  if (hz >= 1e3) return `${(hz / 1e3).toFixed(3)} kHz`;
  return `${hz.toFixed(1)} Hz`;
}

export function RecordingSummary({ summary }: { summary: RecordingSummaryT }) {
  const metadataTrusted = summary.metadata_status === "trusted_metadata" || summary.metadata_status === "sidecar_sigmf";
  return (
    <div className="panel" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-tertiary)", marginBottom: 6, textTransform: "uppercase" }}>
        Recording
      </div>
      <div style={{ borderTop: "1px solid var(--border-hairline)" }}>
        <Row label="Format" value={summary.source_format} />
        <Row label="Samples" value={summary.num_samples.toLocaleString()} />
        <Row label="Sample rate" value={formatHz(summary.sample_rate_hz)} />
        <Row label="Duration" value={summary.duration_s ? `${summary.duration_s.toFixed(3)} s` : "\u2014"} />
        <Row
          label="Metadata"
          value={metadataTrusted ? "trusted" : "assumed default"}
          dim={!metadataTrusted}
        />
      </div>
    </div>
  );
}
