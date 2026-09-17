import { useEffect, useRef } from "react";
import type { DemodResultJSON } from "../lib/types";

/**
 * Canvas (not SVG) on purpose: a constellation is up to ~2000 scattered
 * points, and 2000 SVG <circle> nodes is a lot of DOM for something that
 * is conceptually one image. Canvas also lets us additively blend
 * overlapping points so density is visible -- tight clusters read as
 * bright cores, which is exactly the visual cue an analyst uses to judge
 * lock quality by eye.
 */
export function ConstellationPlot({ demod }: { demod: DemodResultJSON }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const points = demod.constellation ?? [];

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const SIZE = 460;
    canvas.width = SIZE;
    canvas.height = SIZE;
    ctx.clearRect(0, 0, SIZE, SIZE);

    // scale so the densest useful area fills the plot: use a robust
    // percentile rather than max, so a single outlier can't squash
    // everything else into the middle
    const mags = points.map(([i, q]) => Math.hypot(i, q)).sort((a, b) => a - b);
    const p98 = mags[Math.floor(mags.length * 0.98)] || 1;
    const limit = p98 * 1.25;
    const toPx = (v: number) => (v / limit) * (SIZE / 2 - 24) + SIZE / 2;

    // grid + axes
    ctx.strokeStyle = "rgba(255,255,255,0.055)";
    ctx.lineWidth = 1;
    for (let g = -1; g <= 1; g += 0.5) {
      if (g === 0) continue;
      const p = toPx(g * limit * 0.66);
      ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, SIZE); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(SIZE, p); ctx.stroke();
    }
    ctx.strokeStyle = "rgba(255,255,255,0.16)";
    const mid = SIZE / 2;
    ctx.beginPath(); ctx.moveTo(mid, 0); ctx.lineTo(mid, SIZE); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(SIZE, mid); ctx.stroke();

    // points, additively blended so cluster density shows
    ctx.globalCompositeOperation = "lighter";
    ctx.fillStyle = "rgba(79, 209, 197, 0.5)";
    for (const [i, q] of points) {
      const x = toPx(i);
      const y = SIZE - toPx(q); // flip so +Q is up, conventional orientation
      ctx.beginPath();
      ctx.arc(x, y, 1.7, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
  }, [points]);

  if (points.length === 0) return null;

  const evmColor = demod.evm_percent < 10 ? "var(--status-detected)"
    : demod.evm_percent < 25 ? "var(--status-inferred)" : "var(--semantic-error)";

  return (
    <div className="panel" style={{ padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-primary)" }}>
          Constellation &mdash; {demod.modulation.toUpperCase()}
        </div>
        <div className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)" }}>
          {points.length.toLocaleString()} of {(demod.constellation_total_symbols ?? points.length).toLocaleString()} symbols
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
        <canvas
          ref={canvasRef}
          style={{
            width: 340, height: 340, maxWidth: "100%",
            background: "var(--bg-inset)", borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-hairline)",
          }}
        />
        <div style={{ flex: 1, minWidth: 180, display: "flex", flexDirection: "column", gap: 12 }}>
          <Metric label="EVM" value={`${demod.evm_percent.toFixed(2)}%`} color={evmColor}
                  hint="Error vector magnitude vs. the ideal constellation. Lower is tighter." />
          <Metric label="Lock quality" value={`${(demod.lock_quality * 100).toFixed(0)}%`}
                  color={demod.lock_quality > 0.7 ? "var(--status-detected)" : "var(--status-inferred)"}
                  hint="How tightly the recovered symbols cluster." />
          <Metric label="Samples / symbol" value={String(demod.samples_per_symbol_used)}
                  color="var(--text-primary)" hint="Used by the timing recovery stage." />
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", lineHeight: 1.5 }}>
            Points are additively blended &mdash; brighter cores mean more symbols landed there. Distinct,
            tight clusters indicate a clean lock; a smeared ring or blur indicates residual carrier or
            timing error.
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, color, hint }: { label: string; value: string; color: string; hint: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--text-tertiary)", letterSpacing: "0.005em" }}>
        {label}
      </div>
      <div className="mono" style={{ fontSize: 19, fontWeight: 600, color, lineHeight: 1.25 }}>{value}</div>
      <div style={{ fontSize: 9.5, color: "var(--text-tertiary)", lineHeight: 1.4 }}>{hint}</div>
    </div>
  );
}
