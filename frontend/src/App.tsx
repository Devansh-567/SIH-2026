import { useCallback, useState } from "react";
import { analyzeFile, deleteUpload, fetchSpectrogram, uploadFiles } from "./lib/api";
import type { AnalysisResultJSON, SpectrogramJSON, UploadEntry } from "./lib/types";
import { FileDropzone } from "./components/FileDropzone";
import { RecordingSummary } from "./components/RecordingSummary";
import { StageProgress } from "./components/StageProgress";
import { ReportExportPanel } from "./components/ReportExportPanel";import { Waterfall } from "./components/Waterfall";
import { AutomaticAnalysisPanel } from "./components/AutomaticAnalysisPanel";
import { DemodPanel } from "./components/DemodPanel";
import { FecInterleavePanel } from "./components/FecInterleavePanel";
import { BitstreamPanel } from "./components/BitstreamPanel";

type Phase = "idle" | "uploading" | "ready" | "analyzing" | "done" | "error";

export default function App() {
  const [files, setFiles] = useState<File[]>([]);
  const [upload, setUpload] = useState<UploadEntry | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResultJSON | null>(null);
  const [spectrogram, setSpectrogram] = useState<SpectrogramJSON | null>(null);
  const [spectrogramError, setSpectrogramError] = useState<string | null>(null);
  const [sampleRateOverride, setSampleRateOverride] = useState<string>("");
  const [centerFreqOverride, setCenterFreqOverride] = useState<string>("");
  const [modulationOverride, setModulationOverride] = useState<string>("");

  const fileId = upload?.file_id ?? null;

  const handleFilesSelected = useCallback(async (selected: File[]) => {
    setFiles(selected);
    setResult(null);
    setSpectrogram(null);
    setSpectrogramError(null);
    setError(null);
    setPhase("uploading");
    try {
      const res = await uploadFiles(selected);
      if (res.uploads.length === 0) throw new Error("Upload returned no recordings");
      setUpload(res.uploads[0]);
      setPhase("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, []);

  const runAnalysis = useCallback(async () => {
    if (!fileId) return;
    setPhase("analyzing");
    setError(null);
    setSpectrogramError(null);
    const overrides: Record<string, unknown> = {};
    if (modulationOverride) overrides.modulation = modulationOverride;
    if (centerFreqOverride) overrides.center_freq_hz = Number(centerFreqOverride);
    const sr = sampleRateOverride ? Number(sampleRateOverride) : undefined;
    if (sr) overrides.sample_rate_hz = sr;
    try {
      const analysisRes = await analyzeFile(fileId, { sampleRateHz: sr, overrides });
      setResult(analysisRes);
      try {
        const specRes = await fetchSpectrogram(fileId, { sampleRateHz: sr });
        setSpectrogram(specRes);
      } catch (specErr) {
        // Sample rate being unknown is a legitimate, informative reason the
        // waterfall can't render -- surface it rather than a bare blank panel.
        setSpectrogram(null);
        setSpectrogramError(specErr instanceof Error ? specErr.message : String(specErr));
      }
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, [fileId, modulationOverride, sampleRateOverride, centerFreqOverride]);

  const reset = useCallback(async () => {
    if (fileId) await deleteUpload(fileId).catch(() => {});
    setFiles([]);
    setUpload(null);
    setResult(null);
    setSpectrogram(null);
    setSpectrogramError(null);
    setError(null);
    setPhase("idle");
    setSampleRateOverride("");
    setCenterFreqOverride("");
    setModulationOverride("");
  }, [fileId]);

  const busy = phase === "uploading" || phase === "analyzing";

  return (
    <div style={{ minHeight: "100%", display: "flex", flexDirection: "column" }}>
      <Header />

      <div style={{ display: "flex", flex: 1, maxWidth: 1440, margin: "0 auto", width: "100%", padding: "20px 24px", gap: 20 }}>
        {/* Left rail */}
        <div style={{ width: 300, flexShrink: 0, display: "flex", flexDirection: "column", gap: 14 }}>
          <FileDropzone onFilesSelected={handleFilesSelected} selectedNames={files.map((f) => f.name)} disabled={busy} />

          {upload && upload.kind === "sigmf" && (
            <div
              className="mono"
              style={{
                fontSize: 10.5,
                padding: "6px 10px",
                borderRadius: "var(--radius-sm)",
                background: upload.sigmf_pair_complete ? "var(--status-detected-dim)" : "var(--status-hypothesized-dim)",
                color: upload.sigmf_pair_complete ? "var(--status-detected)" : "var(--status-hypothesized)",
              }}
            >
              {upload.sigmf_pair_complete
                ? "SigMF pair detected: .sigmf-data + .sigmf-meta"
                : "Only .sigmf-data received -- upload the matching .sigmf-meta too, or set fmt/sample rate manually"}
            </div>
          )}

          {phase !== "idle" && phase !== "error" && result === null && (
            <button
              onClick={runAnalysis}
              disabled={busy || !fileId}
              style={primaryButtonStyle(busy)}
            >
              {phase === "uploading" ? "Uploading\u2026" : phase === "analyzing" ? "Analyzing\u2026" : "\u25B6 Analyze Signal"}
            </button>
          )}

          {error && (
            <div
              style={{
                padding: 12,
                borderRadius: "var(--radius-md)",
                background: "rgba(255, 77, 94, 0.1)",
                border: "1px solid rgba(255, 77, 94, 0.3)",
                color: "var(--semantic-error)",
                fontSize: 12,
                lineHeight: 1.5,
              }}
            >
              {error}
            </div>
          )}

          {result && <RecordingSummary summary={result.recording_summary} />}

          {(phase === "ready" || phase === "error") && !result && (
            <OverridePanel
              sampleRateOverride={sampleRateOverride}
              setSampleRateOverride={setSampleRateOverride}
              centerFreqOverride={centerFreqOverride}
              setCenterFreqOverride={setCenterFreqOverride}
              modulationOverride={modulationOverride}
              setModulationOverride={setModulationOverride}
            />
          )}

          {result && (
            <>
              <AnalystOverrideResult result={result} onRerun={runAnalysis} />
              <StageProgress stages={result.stages} />
              {result.manifest.warnings.length > 0 && <WarningsPanel warnings={result.manifest.warnings} />}
              <ReportExportPanel result={result} filenameHint={files[0]?.name.replace(/\.[^.]+$/, "") || "rf_analysis_report"} />
              <button onClick={reset} style={secondaryButtonStyle}>
                New Analysis
              </button>
            </>
          )}
        </div>

        {/* Main content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <Waterfall data={spectrogram} errorMessage={spectrogramError} />

          {result ? (
            <>
              <AutomaticAnalysisPanel parameters={result.parameters} />
              <DemodPanel demod={result.demod_result} />
              <FecInterleavePanel result={result} />
              <BitstreamPanel bitstream={result.bitstream_analysis} />
            </>
          ) : (
            <div
              className="panel"
              style={{
                marginTop: 22,
                padding: 40,
                textAlign: "center",
                color: "var(--text-tertiary)",
                fontSize: 13,
                borderStyle: "dashed",
              }}
            >
              Load a recording and click Analyze Signal to run the full detection, classification,
              demodulation, de-interleaving, FEC, and bitstream-correlation pipeline.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Header() {
  return (
    <header
      style={{
        borderBottom: "1px solid var(--border-hairline)",
        background: "var(--bg-panel)",
      }}
    >
      <div style={{ height: 2, background: "var(--grad-waterfall)" }} />
      <div style={{ maxWidth: 1440, margin: "0 auto", padding: "14px 24px", display: "flex", alignItems: "baseline", gap: 14 }}>
        <h1 style={{ fontFamily: "var(--font-display)", fontSize: 17, fontWeight: 600, margin: 0, letterSpacing: "0.01em" }}>
          RF SIGNAL ANALYSIS PLATFORM
        </h1>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
          SIH 26147 &middot; NTRO &middot; Automated .IQ/.WAV Parameter Extraction
        </span>
      </div>
    </header>
  );
}

function OverridePanel({
  sampleRateOverride, setSampleRateOverride, centerFreqOverride, setCenterFreqOverride,
  modulationOverride, setModulationOverride,
}: {
  sampleRateOverride: string;
  setSampleRateOverride: (v: string) => void;
  centerFreqOverride: string;
  setCenterFreqOverride: (v: string) => void;
  modulationOverride: string;
  setModulationOverride: (v: string) => void;
}) {
  return (
    <div className="panel" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-tertiary)", marginBottom: 8, textTransform: "uppercase" }}>
        Optional overrides
      </div>
      <label style={labelStyle}>Sample rate (Hz)</label>
      <input
        type="number"
        placeholder="auto-detect from SigMF/WAV metadata"
        value={sampleRateOverride}
        onChange={(e) => setSampleRateOverride(e.target.value)}
        style={inputStyle}
      />
      <label style={{ ...labelStyle, marginTop: 8 }}>Center frequency (Hz)</label>
      <input
        type="number"
        placeholder="auto-detect from SigMF metadata"
        value={centerFreqOverride}
        onChange={(e) => setCenterFreqOverride(e.target.value)}
        style={inputStyle}
      />
      <label style={{ ...labelStyle, marginTop: 8 }}>Modulation</label>
      <select value={modulationOverride} onChange={(e) => setModulationOverride(e.target.value)} style={inputStyle}>
        <option value="">auto-classify</option>
        {["bpsk", "qpsk", "8psk", "16qam", "64qam", "2fsk", "4fsk"].map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
    </div>
  );
}

function AnalystOverrideResult({ result, onRerun }: { result: AnalysisResultJSON; onRerun: () => void }) {
  const usedOverrides = Object.keys(result.manifest.parameters_used).length > 0;
  return (
    <div className="panel" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-tertiary)", marginBottom: 8, textTransform: "uppercase" }}>
        Analyst-in-the-loop
      </div>
      {usedOverrides ? (
        <div style={{ fontSize: 12, color: "var(--status-detected)", marginBottom: 8 }}>
          {Object.entries(result.manifest.parameters_used).map(([k, v]) => (
            <div key={k} className="mono">{k} = {String(v)}</div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 11.5, color: "var(--text-tertiary)", marginBottom: 8, lineHeight: 1.5 }}>
          No overrides applied -- this is a fully automatic result. Disagree with a value? Reset
          and re-analyze with an override to correct it.
        </div>
      )}
      <button onClick={onRerun} style={secondaryButtonStyle}>Re-run pipeline</button>
    </div>
  );
}

function WarningsPanel({ warnings }: { warnings: string[] }) {
  return (
    <div
      className="panel"
      style={{
        padding: "12px 14px",
        borderColor: "var(--status-hypothesized)55",
        background: "var(--status-hypothesized-dim)",
      }}
    >
      <div style={{ fontSize: 11, color: "var(--status-hypothesized)", marginBottom: 6, fontWeight: 600 }}>
        &#9888; Warnings
      </div>
      {warnings.map((w, i) => (
        <div key={i} style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5, marginBottom: 4 }}>
          {w}
        </div>
      ))}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 10.5,
  color: "var(--text-tertiary)",
  marginBottom: 3,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  background: "var(--bg-inset)",
  border: "1px solid var(--border-hairline)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontSize: 12,
  fontFamily: "var(--font-mono)",
  marginBottom: 4,
};

function primaryButtonStyle(disabled: boolean): React.CSSProperties {
  return {
    padding: "10px 14px",
    borderRadius: "var(--radius-md)",
    border: "none",
    background: disabled ? "var(--bg-panel-raised)" : "var(--grad-waterfall)",
    backgroundSize: "220% 100%",
    color: disabled ? "var(--text-tertiary)" : "#0a0d10",
    fontWeight: 700,
    fontSize: 13,
    cursor: disabled ? "default" : "pointer",
    fontFamily: "var(--font-display)",
    letterSpacing: "0.02em",
  };
}

const secondaryButtonStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-hairline-bright)",
  background: "var(--bg-panel-raised)",
  color: "var(--text-secondary)",
  fontSize: 12,
  cursor: "pointer",
  width: "100%",
};
