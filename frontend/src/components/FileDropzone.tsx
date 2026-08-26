import { useCallback, useRef, useState } from "react";

const ACCEPTED = ".iq,.wav,.cf32,.cs16,.cs8,.cu8,.sigmf-data";

export function FileDropzone({
  onFileSelected,
  selectedName,
  disabled,
}: {
  onFileSelected: (file: File) => void;
  selectedName: string | null;
  disabled?: boolean;
}) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const file = e.dataTransfer.files?.[0];
      if (file) onFileSelected(file);
    },
    [onFileSelected, disabled]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className="panel"
      style={{
        padding: "22px 16px",
        textAlign: "center",
        cursor: disabled ? "default" : "pointer",
        borderStyle: "dashed",
        borderColor: dragOver ? "var(--waterfall-stop-3)" : "var(--border-hairline)",
        background: dragOver ? "rgba(10, 166, 166, 0.06)" : "var(--bg-panel)",
        transition: "border-color 150ms, background 150ms",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        style={{ display: "none" }}
        disabled={disabled}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFileSelected(file);
        }}
      />
      <div style={{ fontSize: 22, marginBottom: 6, opacity: 0.7 }}>&#8595;</div>
      {selectedName ? (
        <div className="mono" style={{ fontSize: 12.5, color: "var(--status-detected)", wordBreak: "break-all" }}>
          {selectedName}
        </div>
      ) : (
        <>
          <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            Drop a recording here, or click to browse
          </div>
          <div className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 4 }}>
            .iq &middot; .wav &middot; .cf32 &middot; .cs16 &middot; .cs8 &middot; .cu8 &middot; .sigmf-data
          </div>
        </>
      )}
    </div>
  );
}
