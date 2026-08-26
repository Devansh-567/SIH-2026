import { useEffect, useRef } from "react";
import type { SpectrogramJSON } from "../lib/types";

// Same 5 stops as the CSS gradient, as RGB triples, so the canvas colormap
// and the confidence-bar/badge gradient are visually the same scale.
const STOPS: [number, [number, number, number]][] = [
  [0.0, [27, 20, 100]],
  [0.28, [10, 107, 168]],
  [0.5, [10, 166, 166]],
  [0.75, [255, 176, 0]],
  [1.0, [255, 68, 51]],
];

function colorFor(t: number): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  for (let i = 0; i < STOPS.length - 1; i++) {
    const [t0, c0] = STOPS[i];
    const [t1, c1] = STOPS[i + 1];
    if (clamped >= t0 && clamped <= t1) {
      const f = (clamped - t0) / (t1 - t0 || 1);
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * f),
        Math.round(c0[1] + (c1[1] - c0[1]) * f),
        Math.round(c0[2] + (c1[2] - c0[2]) * f),
      ];
    }
  }
  return STOPS[STOPS.length - 1][1];
}

export function Waterfall({ data }: { data: SpectrogramJSON | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const nTime = data.power_db.length;
    const nFreq = data.power_db[0]?.length ?? 0;
    if (nTime === 0 || nFreq === 0) return;

    canvas.width = nTime;
    canvas.height = nFreq;
    const imageData = ctx.createImageData(nTime, nFreq);
    const range = data.max_db - data.min_db || 1;

    for (let x = 0; x < nTime; x++) {
      for (let y = 0; y < nFreq; y++) {
        // flip y so low frequency is at the bottom, matching a conventional
        // spectrum-analyzer / waterfall orientation
        const freqIdx = nFreq - 1 - y;
        const db = data.power_db[x][freqIdx];
        const t = (db - data.min_db) / range;
        const [r, g, b] = colorFor(t);
        const idx = (y * nTime + x) * 4;
        imageData.data[idx] = r;
        imageData.data[idx + 1] = g;
        imageData.data[idx + 2] = b;
        imageData.data[idx + 3] = 255;
      }
    }
    ctx.putImageData(imageData, 0, 0);
  }, [data]);

  const nyquist = data ? data.sample_rate_hz / 2 : 0;

  return (
    <div className="panel scanline-accent" style={{ padding: "14px 16px", overflow: "hidden" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-tertiary)", textTransform: "uppercase" }}>
          Waterfall
        </div>
        {data && (
          <div className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)" }}>
            {data.min_db.toFixed(0)} to {data.max_db.toFixed(0)} dB
          </div>
        )}
      </div>

      {!data ? (
        <div
          style={{
            height: 220,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--text-tertiary)",
            fontSize: 12,
            background: "var(--bg-inset)",
            borderRadius: "var(--radius-md)",
          }}
        >
          No spectrogram data yet
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <div className="mono" style={{ fontSize: 10, color: "var(--text-tertiary)", writingMode: "vertical-rl", transform: "rotate(180deg)", textAlign: "center" }}>
              FREQUENCY
            </div>
            <canvas
              ref={canvasRef}
              style={{
                width: "100%",
                height: 260,
                imageRendering: "pixelated",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-hairline)",
              }}
            />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", paddingLeft: 18 }} className="mono">
            <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>-{(nyquist / 1000).toFixed(1)} kHz</span>
            <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>0</span>
            <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>+{(nyquist / 1000).toFixed(1)} kHz</span>
          </div>
          <div style={{ textAlign: "center", fontSize: 10, color: "var(--text-tertiary)" }} className="mono">
            TIME &rarr;
          </div>
        </div>
      )}
    </div>
  );
}
