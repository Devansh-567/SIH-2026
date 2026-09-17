import { useState } from "react";
import type { Parameter, Status } from "../lib/types";
import { submitFeedback } from "../lib/api";

/* A finding rendered as a ledger row, not a card.

   The central design idea lives here: certainty is carried by the type
   itself. A DETECTED value is solid and full-weight; an INFERRED one is
   slightly lighter; an UNKNOWN one is hollow and italic. You can scan a
   column of findings and see what the system is sure of without reading
   a single status label. The label is confirmation, not the signal. */

const CERTAINTY_CLASS: Record<Status, string> = {
  DETECTED: "value-measured",
  ESTIMATED: "value-measured",
  INFERRED: "value-inferred",
  HYPOTHESIZED: "value-uncertain",
  UNKNOWN: "value-unknown",
};

const STATUS_COLOR: Record<Status, string> = {
  DETECTED: "var(--status-detected)",
  ESTIMATED: "var(--status-estimated)",
  INFERRED: "var(--status-inferred)",
  HYPOTHESIZED: "var(--status-hypothesized)",
  UNKNOWN: "var(--status-unknown)",
};

function formatValue(value: unknown, unit: string | null): string {
  if (value === null || value === undefined) return "not determined";
  if (typeof value === "number") {
    const abs = Math.abs(value);
    let out: string;
    if (unit === "Hz" && abs >= 1e6) out = `${(value / 1e6).toFixed(3)} MHz`;
    else if (unit === "Hz" && abs >= 1e3) out = `${(value / 1e3).toFixed(2)} kHz`;
    else { out = Number.isInteger(value) ? String(value) : value.toFixed(3); return unit ? `${out} ${unit}` : out; }
    return out;
  }
  return String(value);
}

function label(name: string): string {
  const map: Record<string, string> = {
    sample_rate_hz: "Sample rate",
    center_frequency_hz: "Center frequency",
    absolute_peak_frequency_hz: "Peak frequency (absolute)",
    peak_frequency_hz: "Peak frequency (baseband)",
    occupied_bandwidth_hz: "Occupied bandwidth",
    symbol_rate_hz: "Symbol rate",
    noise_floor_db: "Noise floor",
    snr_db: "Signal-to-noise ratio",
    spectral_entropy: "Spectral entropy",
    modulation: "Modulation",
  };
  return map[name] ?? name.replace(/_hz$|_db$/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Confidence as a discrete tick scale — an instrument reads in
 *  graduations, not a smooth marketing progress bar. */
function ConfidenceScale({ confidence, color }: { confidence: number; color: string }) {
  const filled = Math.round(Math.max(0, Math.min(1, confidence)) * 10);
  return (
    <span style={{ display: "inline-flex", gap: 1.5, alignItems: "center" }} aria-label={`Confidence ${Math.round(confidence * 100)} percent`}>
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} style={{
          width: 3, height: i < filled ? 11 : 6, background: i < filled ? color : "var(--border-hairline-bright)",
          borderRadius: 0.5, transition: "height 150ms ease",
        }} />
      ))}
    </span>
  );
}

export function ParameterCard({ param, analysisId }: { param: Parameter; analysisId?: string }) {
  const [open, setOpen] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [val, setVal] = useState("");
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);

  const color = STATUS_COLOR[param.status];
  const hasDetail = param.evidence.length > 0 || param.alternatives.length > 0 || !!analysisId;

  const send = async () => {
    if (!analysisId || !val.trim()) return;
    await submitFeedback(analysisId, param.name, val.trim(), note.trim() || undefined);
    setSent(true); setCorrecting(false);
  };

  return (
    <div className="ledger-row" style={{ gridTemplateColumns: "minmax(150px,1.1fr) minmax(130px,1fr) 108px 74px 22px", gap: 14, padding: "11px 16px", cursor: hasDetail ? "pointer" : "default" }}
         onClick={() => hasDetail && setOpen((o) => !o)}>
      <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{label(param.name)}</span>

      <span className={`num ${CERTAINTY_CLASS[param.status]}`} style={{ fontSize: 14.5 }}>
        {formatValue(param.value, param.unit)}
      </span>

      <span style={{ fontSize: 11, color, letterSpacing: "0.01em" }}>
        {param.status === "DETECTED" ? "measured"
          : param.status === "ESTIMATED" ? "estimated"
          : param.status === "INFERRED" ? "inferred"
          : param.status === "HYPOTHESIZED" ? "hypothesis"
          : "not determined"}
      </span>

      <span style={{ display: "flex", justifyContent: "flex-end" }}>
        {param.status !== "UNKNOWN" && param.status !== "DETECTED"
          ? <ConfidenceScale confidence={param.confidence} color={color} />
          : <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{param.status === "DETECTED" ? "exact" : "—"}</span>}
      </span>

      <span style={{ color: "var(--text-tertiary)", fontSize: 11, textAlign: "right",
                     transform: open ? "rotate(90deg)" : "none", transition: "transform 140ms" }}>
        {hasDetail ? "›" : ""}
      </span>

      {open && (
        <div style={{ gridColumn: "1 / -1", paddingTop: 12, marginTop: 4, borderTop: "1px solid var(--border-hairline)",
                      display: "flex", flexDirection: "column", gap: 12 }} onClick={(e) => e.stopPropagation()}>
          {param.evidence.length > 0 && (
            <div>
              <div style={{ fontSize: 11.5, color: "var(--text-secondary)", marginBottom: 6 }}>
                Why the system reports this
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                {param.evidence.map((ev, i) => (
                  <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, lineHeight: 1.5 }}>
                    <span className="num" style={{ color: "var(--status-estimated)", fontSize: 10.5, minWidth: 148, opacity: 0.85 }}>
                      {ev.source}
                    </span>
                    <span style={{ color: "var(--text-secondary)", flex: 1 }}>{ev.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {param.alternatives.length > 0 && (
            <div>
              <div style={{ fontSize: 11.5, color: "var(--text-secondary)", marginBottom: 6 }}>
                Other candidates considered
              </div>
              {param.alternatives.map((a, i) => (
                <div key={i} className="num" style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "2px 0", maxWidth: 320 }}>
                  <span style={{ color: "var(--text-secondary)" }}>{String(a.value)}</span>
                  <span style={{ color: "var(--text-tertiary)" }}>{(a.confidence * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}

          {analysisId && (sent ? (
            <div style={{ fontSize: 11.5, color: "var(--status-detected)" }}>Correction saved.</div>
          ) : correcting ? (
            <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
              <input autoFocus placeholder="Correct value" value={val} onChange={(e) => setVal(e.target.value)} style={inp(150)} />
              <input placeholder="Why (optional)" value={note} onChange={(e) => setNote(e.target.value)} style={inp(230)} />
              <button onClick={send} disabled={!val.trim()} style={btnPrimary}>Save correction</button>
              <button onClick={() => setCorrecting(false)} style={btnQuiet}>Cancel</button>
            </div>
          ) : (
            <button onClick={() => setCorrecting(true)} style={{ ...btnQuiet, alignSelf: "flex-start" }}>
              This is wrong — correct it
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const inp = (w: number): React.CSSProperties => ({
  width: w, padding: "5px 8px", background: "var(--bg-inset)", border: "1px solid var(--border-hairline-bright)",
  borderRadius: "var(--radius-control)", color: "var(--text-primary)", fontSize: 12, fontFamily: "var(--font-mono)",
});
const btnPrimary: React.CSSProperties = {
  padding: "5px 11px", borderRadius: "var(--radius-control)", border: "none",
  background: "var(--status-estimated)", color: "#0b1620", fontSize: 12, fontWeight: 500, cursor: "pointer",
};
const btnQuiet: React.CSSProperties = {
  padding: "5px 11px", borderRadius: "var(--radius-control)", border: "1px solid var(--border-hairline-bright)",
  background: "transparent", color: "var(--text-secondary)", fontSize: 12, cursor: "pointer",
};
