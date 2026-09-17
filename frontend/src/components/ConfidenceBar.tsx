export function ConfidenceBar({ confidence, height = 5 }: { confidence: number; height?: number }) {
  const pct = Math.max(0, Math.min(1, confidence)) * 100;
  return (
    <div
      style={{
        width: "100%",
        height,
        borderRadius: height / 2,
        background: "var(--bg-inset)",
        overflow: "hidden",
        border: "1px solid var(--border-hairline)",
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: "var(--status-estimated)",
          backgroundSize: "220% 100%",
          backgroundPosition: "0% 0%",
          transition: "width 400ms ease",
        }}
      />
    </div>
  );
}
