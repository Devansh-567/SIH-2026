import type { SignalViewJSON } from "../lib/types";

const W = 900;
const H = 220;
const PAD_L = 52;
const PAD_R = 12;
const PAD_T = 14;
const PAD_B = 28;

function buildPath(values: number[], xs: number[], xMin: number, xMax: number, yMin: number, yMax: number): string {
  if (values.length === 0) return "";
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;
  const px = (x: number) => PAD_L + ((x - xMin) / xSpan) * (W - PAD_L - PAD_R);
  const py = (y: number) => PAD_T + (1 - (y - yMin) / ySpan) * (H - PAD_T - PAD_B);
  return values.map((v, i) => `${i === 0 ? "M" : "L"}${px(xs[i]).toFixed(1)},${py(v).toFixed(1)}`).join("");
}

function Axes({ yMin, yMax, xMin, xMax, yUnit, xUnit, fmtX }: {
  yMin: number; yMax: number; xMin: number; xMax: number;
  yUnit: string; xUnit: string; fmtX: (v: number) => string;
}) {
  const yTicks = [yMin, (yMin + yMax) / 2, yMax];
  const xTicks = [xMin, (xMin + xMax) / 2, xMax];
  const ySpan = yMax - yMin || 1;
  const xSpan = xMax - xMin || 1;
  return (
    <g>
      {yTicks.map((t, i) => {
        const y = PAD_T + (1 - (t - yMin) / ySpan) * (H - PAD_T - PAD_B);
        return (
          <g key={`y${i}`}>
            <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y} stroke="rgba(255,255,255,0.06)" strokeWidth={1} />
            <text x={PAD_L - 7} y={y + 3.5} textAnchor="end" fontSize={9.5} fill="#5A6570" fontFamily="monospace">
              {Math.abs(t) >= 1000 ? t.toExponential(1) : t.toFixed(2)}
            </text>
          </g>
        );
      })}
      {xTicks.map((t, i) => {
        const x = PAD_L + ((t - xMin) / xSpan) * (W - PAD_L - PAD_R);
        return (
          <text key={`x${i}`} x={x} y={H - 8} textAnchor="middle" fontSize={9.5} fill="#5A6570" fontFamily="monospace">
            {fmtX(t)}
          </text>
        );
      })}
      <text x={10} y={PAD_T + 8} fontSize={9} fill="#5A6570" fontFamily="monospace">{yUnit}</text>
      <text x={W - PAD_R} y={H - 8} textAnchor="end" fontSize={9} fill="#5A6570" fontFamily="monospace">{xUnit}</text>
    </g>
  );
}

export function TimeDomainPlot({ view }: { view: SignalViewJSON }) {
  const { time_s, i, q, envelope } = view.time_domain;
  const all = [...i, ...q];
  const yMax = Math.max(...all.map(Math.abs)) * 1.1 || 1;
  const yMin = -yMax;
  const xMin = time_s[0] ?? 0;
  const xMax = time_s[time_s.length - 1] ?? 1;
  const fmtX = (v: number) => (xMax < 0.01 ? `${(v * 1e6).toFixed(0)}\u00B5s` : `${(v * 1e3).toFixed(2)}ms`);

  return (
    <div className="panel" style={{ padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-primary)" }}>Time Domain &mdash; I / Q / Envelope</div>
        <div className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)" }}>
          {view.num_samples_returned.toLocaleString()} pts
          {view.decimation > 1 && ` (every ${view.decimation}${ordinal(view.decimation)} sample)`}
          {" \u00B7 "}{view.total_samples.toLocaleString()} total
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <Axes yMin={yMin} yMax={yMax} xMin={xMin} xMax={xMax} yUnit="amplitude" xUnit="time" fmtX={fmtX} />
        <path d={buildPath(i, time_s, xMin, xMax, yMin, yMax)} fill="none" stroke="#38A3E8" strokeWidth={1.1} opacity={0.9} />
        <path d={buildPath(q, time_s, xMin, xMax, yMin, yMax)} fill="none" stroke="#FF8A3D" strokeWidth={1.1} opacity={0.85} />
        <path d={buildPath(envelope, time_s, xMin, xMax, yMin, yMax)} fill="none" stroke="#4FD1C5" strokeWidth={1.4} opacity={0.95} />
      </svg>
      <Legend items={[["I (in-phase)", "#38A3E8"], ["Q (quadrature)", "#FF8A3D"], ["Envelope |IQ|", "#4FD1C5"]]} />
    </div>
  );
}

export function SpectrumPlot({ view }: { view: SignalViewJSON }) {
  const { freqs_hz, psd_db, is_absolute_frequency, peak_freq_hz, peak_psd_db } = view.spectrum;
  const yMax = Math.max(...psd_db) + 4;
  const yMin = Math.min(...psd_db) - 2;
  const xMin = freqs_hz[0] ?? 0;
  const xMax = freqs_hz[freqs_hz.length - 1] ?? 1;
  const fmtX = (v: number) =>
    Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : v.toFixed(0);

  const xSpan = xMax - xMin || 1;
  const peakX = PAD_L + ((peak_freq_hz - xMin) / xSpan) * (W - PAD_L - PAD_R);
  const ySpan = yMax - yMin || 1;
  const peakY = PAD_T + (1 - (peak_psd_db - yMin) / ySpan) * (H - PAD_T - PAD_B);

  return (
    <div className="panel" style={{ padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-primary)" }}>
          Frequency Domain &mdash; Power Spectral Density
        </div>
        <div className="mono" style={{ fontSize: 10.5, color: is_absolute_frequency ? "var(--text-tertiary)" : "var(--status-hypothesized)" }}>
          {is_absolute_frequency ? "absolute RF frequency" : "baseband-relative (no center freq known)"}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <Axes yMin={yMin} yMax={yMax} xMin={xMin} xMax={xMax} yUnit="dB" xUnit="Hz" fmtX={fmtX} />
        <path d={buildPath(psd_db, freqs_hz, xMin, xMax, yMin, yMax)} fill="none" stroke="#FFB300" strokeWidth={1.2} />
        <line x1={peakX} y1={PAD_T} x2={peakX} y2={H - PAD_B} stroke="#4FD1C5" strokeWidth={1} strokeDasharray="3 3" opacity={0.7} />
        <circle cx={peakX} cy={peakY} r={3.2} fill="#4FD1C5" />
        <text x={Math.min(peakX + 7, W - 130)} y={peakY - 7} fontSize={9.5} fill="#4FD1C5" fontFamily="monospace">
          peak {fmtX(peak_freq_hz)}Hz @ {peak_psd_db.toFixed(0)}dB
        </text>
      </svg>
      <Legend items={[["PSD (Welch)", "#FFB300"], ["Detected peak", "#4FD1C5"]]} />
    </div>
  );
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <div style={{ display: "flex", gap: 16, marginTop: 6, flexWrap: "wrap" }}>
      {items.map(([label, color]) => (
        <span key={label} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10.5, color: "var(--text-tertiary)" }}>
          <span style={{ width: 14, height: 2.5, background: color, borderRadius: 2 }} />
          {label}
        </span>
      ))}
    </div>
  );
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return s[(v - 20) % 10] || s[v] || s[0];
}
