import type { BitstreamAnalysisJSON } from "../lib/types";
import { SectionHeader } from "./AutomaticAnalysisPanel";
import { EmptyState } from "./DemodPanel";

function chunk(str: string, size: number): string[] {
  const out: string[] = [];
  for (let i = 0; i < str.length; i += size) out.push(str.slice(i, i + size));
  return out;
}

export function BitstreamPanel({ bitstream }: { bitstream: BitstreamAnalysisJSON | null }) {
  if (!bitstream) {
    return (
      <div>
        <SectionHeader title="Bit Stream Analysis" />
        <EmptyState text="No bitstream analysis available -- demodulation did not produce enough bits to analyze." />
      </div>
    );
  }

  const hexLines = chunk(bitstream.hex_preview, 32);

  return (
    <div>
      <SectionHeader title="Bit Stream Analysis" subtitle={`${bitstream.length_bits.toLocaleString()} bits`} />
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 14 }}>
        <div className="panel" style={{ padding: 16 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 8, color: "var(--text-primary)" }}>
            Hex / ASCII (byte-aligned at offset {bitstream.best_byte_alignment})
          </div>
          <div
            className="mono"
            style={{
              background: "var(--bg-inset)",
              border: "1px solid var(--border-hairline)",
              borderRadius: "var(--radius-md)",
              padding: 10,
              fontSize: 11.5,
              maxHeight: 220,
              overflowY: "auto",
              lineHeight: 1.7,
            }}
          >
            {hexLines.map((line, i) => (
              <div key={i} style={{ display: "flex", gap: 14 }}>
                <span style={{ color: "var(--text-tertiary)", minWidth: 44 }}>
                  {(i * 16).toString(16).padStart(4, "0")}
                </span>
                <span style={{ color: "var(--status-estimated)", letterSpacing: "0.05em" }}>
                  {chunk(line, 2).join(" ")}
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 8 }}>ASCII preview</div>
          <div
            className="mono"
            style={{
              background: "var(--bg-inset)",
              border: "1px solid var(--border-hairline)",
              borderRadius: "var(--radius-md)",
              padding: "8px 10px",
              fontSize: 12,
              marginTop: 4,
              color: "var(--text-secondary)",
              wordBreak: "break-all",
            }}
          >
            {bitstream.ascii_preview || <span style={{ color: "var(--text-tertiary)" }}>(no printable content)</span>}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel" style={{ padding: 16 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 8, color: "var(--text-primary)" }}>
              Sync word / preamble matches
            </div>
            {bitstream.preamble_matches.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {bitstream.preamble_matches.map((m, i) => (
                  <div key={i} className="mono" style={{ fontSize: 11.5, display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--status-detected)" }}>{m.name}</span>
                    <span style={{ color: "var(--text-tertiary)" }}>
                      bit {m.position}, {m.hamming_distance} bit error{m.hamming_distance === 1 ? "" : "s"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No known sync words matched.</span>
            )}
          </div>

          <div className="panel" style={{ padding: 16 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 8, color: "var(--text-primary)" }}>
              Framing hypotheses
            </div>
            {bitstream.framing_hypotheses.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {bitstream.framing_hypotheses.map((f, i) => (
                  <div key={i} className="mono" style={{ fontSize: 11.5, display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)" }}>{f.frame_length_bits} bits</span>
                    <span style={{ color: "var(--status-inferred)" }}>{(f.confidence * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No periodic framing detected.</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
