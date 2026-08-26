import type { AnalysisResultJSON } from "../lib/types";
import { SectionHeader } from "./AutomaticAnalysisPanel";
import { EmptyState } from "./DemodPanel";

function HypothesisTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: (string | number)[][];
}) {
  return (
    <table className="mono" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr>
          {headers.map((h) => (
            <th
              key={h}
              style={{
                textAlign: "left",
                padding: "6px 10px",
                color: "var(--text-tertiary)",
                fontWeight: 500,
                borderBottom: "1px solid var(--border-hairline)",
                fontSize: 10.5,
                textTransform: "uppercase",
                letterSpacing: "0.03em",
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} style={{ background: i === 0 ? "var(--status-detected-dim)" : "transparent" }}>
            {row.map((cell, j) => (
              <td
                key={j}
                style={{
                  padding: "6px 10px",
                  color: i === 0 ? "var(--status-detected)" : "var(--text-secondary)",
                  borderBottom: "1px solid var(--border-hairline)",
                }}
              >
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function FecInterleavePanel({ result }: { result: AnalysisResultJSON }) {
  const conv = result.fec_hypotheses.convolutional ?? [];
  const block = result.deinterleave_hypotheses.block ?? [];
  const pnNote = result.deinterleave_hypotheses.pseudo_random_note;

  const hasAny = conv.length > 0 || block.length > 0;

  return (
    <div>
      <SectionHeader title="FEC &amp; De-interleaving" />
      {!hasAny ? (
        <EmptyState text="No FEC or de-interleaving hypotheses were tested -- insufficient demodulated bits were available (this stage requires a successful demodulation first)." />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
          <div className="panel" style={{ padding: 16 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 8, color: "var(--text-primary)" }}>
              Convolutional FEC hypotheses
            </div>
            {conv.length > 0 ? (
              <HypothesisTable
                headers={["Preset", "Re-encode distance"]}
                rows={conv.map((c) => [c.preset, c.reencode_distance_fraction.toFixed(4)])}
              />
            ) : (
              <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No candidates evaluated.</span>
            )}
            <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 8, lineHeight: 1.5 }}>
              Ranked by re-encode Hamming-distance fraction (lower = the decoded bits, when
              re-encoded, match the received bits more closely -- strong self-verifying evidence
              this preset is correct). Highlighted row is the best hypothesis.
            </div>
          </div>

          <div className="panel" style={{ padding: 16 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 8, color: "var(--text-primary)" }}>
              Block de-interleaving hypotheses
            </div>
            {block.length > 0 ? (
              <HypothesisTable
                headers={["Rows", "Cols", "Structure score"]}
                rows={block.map((b) => [b.rows, b.cols, b.structure_score.toFixed(4)])}
              />
            ) : (
              <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No candidates evaluated.</span>
            )}
            {pnNote && (
              <div
                style={{
                  marginTop: 10,
                  padding: 10,
                  fontSize: 11.5,
                  lineHeight: 1.5,
                  color: "var(--status-hypothesized)",
                  background: "var(--status-hypothesized-dim)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--status-hypothesized)33",
                }}
              >
                <strong>Pseudo-random interleaving:</strong> {pnNote}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
