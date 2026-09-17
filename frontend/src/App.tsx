import { Fragment, useCallback, useEffect, useState } from "react";
import { analyzeFile, deleteUpload, fetchSignalView, fetchSpectrogram, getHistoryEntry, loadSample, uploadFiles } from "./lib/api";
import type { AnalysisResultJSON, SignalViewJSON, SpectrogramJSON, UploadEntry } from "./lib/types";
import { FileDropzone } from "./components/FileDropzone";
import { RecordingSummary } from "./components/RecordingSummary";
import { StageProgress } from "./components/StageProgress";
import { ReportExportPanel } from "./components/ReportExportPanel";
import { Waterfall } from "./components/Waterfall";
import { AutomaticAnalysisPanel } from "./components/AutomaticAnalysisPanel";
import { DemodPanel } from "./components/DemodPanel";
import { FecInterleavePanel } from "./components/FecInterleavePanel";
import { BitstreamPanel } from "./components/BitstreamPanel";
import { SimilarSignalsPanel } from "./components/SimilarSignalsPanel";
import { HistoryView } from "./components/HistoryView";
import { BatchView } from "./components/BatchView";
import { CompareView } from "./components/CompareView";
import { SampleGallery } from "./components/SampleGallery";
import { ConstellationPlot } from "./components/ConstellationPlot";
import { TimeDomainPlot, SpectrumPlot } from "./components/SignalPlots";

type Phase = "idle" | "uploading" | "ready" | "analyzing" | "done" | "error";
type Tab = "analyze" | "history" | "batch" | "compare";

export default function App() {
  const [tab, setTab] = useState<Tab>("analyze");
  const [files, setFiles] = useState<File[]>([]);
  const [upload, setUpload] = useState<UploadEntry | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResultJSON | null>(null);
  const [historicalMode, setHistoricalMode] = useState(false);
  const [spectrogram, setSpectrogram] = useState<SpectrogramJSON | null>(null);
  const [spectrogramError, setSpectrogramError] = useState<string | null>(null);
  const [sampleRateOverride, setSampleRateOverride] = useState<string>("");
  const [centerFreqOverride, setCenterFreqOverride] = useState<string>("");
  const [modulationOverride, setModulationOverride] = useState<string>("");
  const [compareSelection, setCompareSelection] = useState<string[]>([]);
  const [sampleExpected, setSampleExpected] = useState<Record<string, unknown> | null>(null);
  const [sampleTitle, setSampleTitle] = useState<string | null>(null);
  const [signalView, setSignalView] = useState<SignalViewJSON | null>(null);

  const fileId = upload?.file_id ?? null;
  const analysisId = result?.manifest.analysis_id;

  const handleFilesSelected = useCallback(async (selected: File[]) => {
    setFiles(selected);
    setResult(null);
    setSampleExpected(null);
    setSampleTitle(null);
    setSignalView(null);
    setHistoricalMode(false);
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
      setHistoricalMode(false);
      try {
        const specRes = await fetchSpectrogram(fileId, { sampleRateHz: sr });
        setSpectrogram(specRes);
        try { setSignalView(await fetchSignalView(fileId, { sampleRateHz: sr })); } catch { setSignalView(null); }
      } catch (specErr) {
        setSpectrogram(null);
        setSpectrogramError(specErr instanceof Error ? specErr.message : String(specErr));
      }
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, [fileId, modulationOverride, sampleRateOverride, centerFreqOverride]);

  const runSample = useCallback(async (sampleId: string) => {
    setError(null);
    setResult(null);
    setHistoricalMode(false);
    setSpectrogram(null);
    setSpectrogramError(null);
    setSignalView(null);
    setFiles([]);
    setPhase("uploading");
    try {
      const loaded = await loadSample(sampleId);
      setUpload({ file_id: loaded.file_id, recording_name: loaded.sample_id, kind: "sigmf", sigmf_pair_complete: true });
      setSampleExpected(loaded.expected);
      setSampleTitle(loaded.title);
      setPhase("analyzing");
      const analysisRes = await analyzeFile(loaded.file_id, {});
      setResult(analysisRes);
      try {
        setSpectrogram(await fetchSpectrogram(loaded.file_id, {}));
        try { setSignalView(await fetchSignalView(loaded.file_id, {})); } catch { setSignalView(null); }
      } catch (specErr) {
        setSpectrogram(null);
        setSpectrogramError(specErr instanceof Error ? specErr.message : String(specErr));
      }
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, []);

  const openHistoricalAnalysis = useCallback(async (id: string) => {
    setError(null);
    setSpectrogram(null);
    try {
      const historical = await getHistoryEntry(id);
      setSpectrogramError(null);
      setSignalView(null);
      setResult(historical);
      setUpload(null);
      setFiles([]);
      setHistoricalMode(true);
      setPhase("done");
      setTab("analyze");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const reset = useCallback(async () => {
    if (fileId) await deleteUpload(fileId).catch(() => {});
    setFiles([]);
    setUpload(null);
    setResult(null);
    setSampleExpected(null);
    setSampleTitle(null);
    setSignalView(null);
    setHistoricalMode(false);
    setSpectrogram(null);
    setSpectrogramError(null);
    setError(null);
    setPhase("idle");
    setSampleRateOverride("");
    setCenterFreqOverride("");
    setModulationOverride("");
  }, [fileId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return;
      const map: Record<string, Tab> = { "1": "analyze", "2": "history", "3": "batch", "4": "compare" };
      if (map[e.key]) setTab(map[e.key]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const busy = phase === "uploading" || phase === "analyzing";

  return (
    <div style={{ minHeight: "100%", display: "flex", flexDirection: "column" }}>
      <Header tab={tab} setTab={setTab} result={result} phase={phase} />

      <div style={{ flex: 1, maxWidth: 1440, margin: "0 auto", width: "100%", padding: "20px 24px" }}>
        {tab === "history" && (
          <HistoryView onOpen={openHistoricalAnalysis} onCompareSelectionChange={setCompareSelection} />
        )}
        {tab === "batch" && <BatchView onOpenAnalysis={openHistoricalAnalysis} />}
        {tab === "compare" && <CompareView initialSelection={compareSelection} />}

        {tab === "analyze" && (
          <div style={{ display: "flex", gap: 20 }}>
            <div style={{ width: 300, flexShrink: 0, display: "flex", flexDirection: "column", gap: 14 }}>
              {historicalMode && result && (
                <div className="panel" style={{ padding: "10px 12px", borderColor: "var(--status-estimated)55" }}>
                  <div style={{ fontSize: 12, color: "var(--status-estimated)", fontWeight: 500, marginBottom: 2 }}>
                    Viewing a saved analysis
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                    {new Date(result.manifest.created_at * 1000).toLocaleString()}
                  </div>
                </div>
              )}

              {!historicalMode && (
                <FileDropzone onFilesSelected={handleFilesSelected} selectedNames={files.map((f) => f.name)} disabled={busy} />
              )}

              {!historicalMode && upload && upload.kind === "sigmf" && (
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

              {!historicalMode && phase !== "idle" && phase !== "error" && result === null && (
                <button onClick={runAnalysis} disabled={busy || !fileId} style={primaryButtonStyle(busy)}>
                  {phase === "uploading" ? "Uploading\u2026" : phase === "analyzing" ? "Analyzing\u2026" : "\u25B6 Analyze Signal"}
                </button>
              )}

              {error && (
                <div style={{ padding: 12, borderRadius: "var(--radius-md)", background: "rgba(255, 77, 94, 0.1)", border: "1px solid rgba(255, 77, 94, 0.3)", color: "var(--semantic-error)", fontSize: 12, lineHeight: 1.5 }}>
                  {error}
                </div>
              )}

              {result && <RecordingSummary summary={result.recording_summary} />}

              {!historicalMode && (phase === "ready" || phase === "error") && !result && (
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
                  {!historicalMode && <AnalystOverrideResult result={result} onRerun={runAnalysis} />}
                  {sampleExpected && <GroundTruthPanel expected={sampleExpected} title={sampleTitle} result={result} />}
                  <StageProgress stages={result.stages} />
                  {result.manifest.warnings.length > 0 && <WarningsPanel warnings={result.manifest.warnings} />}
                  {analysisId && <SimilarSignalsPanel analysisId={analysisId} onOpen={openHistoricalAnalysis} />}
                  {analysisId && (
                    <ReportExportPanel
                      result={result}
                      filenameHint={files[0]?.name.replace(/\.[^.]+$/, "") || "rf_analysis_report"}
                    />
                  )}
                  <button onClick={reset} style={secondaryButtonStyle}>
                    New Analysis
                  </button>
                </>
              )}
            </div>

            <div style={{ flex: 1, minWidth: 0 }}>
              <Waterfall
                data={spectrogram}
                errorMessage={historicalMode ? "Waterfall isn't available for a historical analysis reopened from the archive -- the original upload is no longer held on the server." : spectrogramError}
              />

              {result ? (
                <>
                  {signalView && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 14 }}>
                      <TimeDomainPlot view={signalView} />
                      <SpectrumPlot view={signalView} />
                    </div>
                  )}
                  {result.demod_result?.constellation && result.demod_result.constellation.length > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <ConstellationPlot demod={result.demod_result} />
                    </div>
                  )}
                  <AutomaticAnalysisPanel parameters={result.parameters} analysisId={analysisId} />
                  <DemodPanel demod={result.demod_result} />
                  <FecInterleavePanel result={result} />
                  <BitstreamPanel bitstream={result.bitstream_analysis} />
                </>
              ) : (
                <>
                  <div className="panel" style={{ marginTop: 22, padding: 28, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13, borderStyle: "dashed" }}>
                    Load a recording and click Analyze Signal to run the full detection, classification,
                    demodulation, de-interleaving, FEC, and bitstream-correlation pipeline.
                  </div>
                  <SampleGallery onRunSample={runSample} disabled={busy} />
                </>
              )}
            </div>
          </div>
        )}
      </div>
      <StatusStrip phase={phase} result={result} error={error} />
    </div>
  );
}

function StatusStrip({ phase, result, error }: { phase: Phase; result: AnalysisResultJSON | null; error: string | null }) {
  const warnings = result?.manifest.warnings.length ?? 0;
  const stages = result?.stages ?? [];
  const ok = stages.filter((s) => s.status === "ok").length;
  const skipped = stages.filter((s) => s.status === "skipped").length;
  const dot = (c: string) => ({ width: 6, height: 6, borderRadius: "50%", background: c, display: "inline-block" });
  return (
    <div style={{ borderTop: "1px solid var(--border-hairline)", background: "var(--bg-panel)",
                  padding: "0 18px", height: 28, display: "flex", alignItems: "center", gap: 18,
                  fontSize: 11.5, color: "var(--text-tertiary)" }}>
      <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={dot(error ? "var(--semantic-error)" : phase === "done" ? "var(--status-detected)"
                : phase === "analyzing" || phase === "uploading" ? "var(--status-inferred)" : "var(--text-tertiary)")} />
        {error ? "Analysis failed" : phase === "done" ? "Analysis complete"
          : phase === "analyzing" ? "Analyzing" : phase === "uploading" ? "Loading" : "Idle"}
      </span>
      {stages.length > 0 && (
        <span className="num">{ok} stages run{skipped > 0 ? `, ${skipped} skipped` : ""}</span>
      )}
      {warnings > 0 && (
        <span style={{ color: "var(--status-inferred)" }}>
          {warnings} warning{warnings === 1 ? "" : "s"}
        </span>
      )}
      <span style={{ marginLeft: "auto", color: "var(--text-tertiary)" }}>
        Press 1–4 to switch views
      </span>
    </div>
  );
}

function Header({ tab, setTab, result, phase }: {
  tab: Tab; setTab: (t: Tab) => void; result: AnalysisResultJSON | null; phase: Phase;
}) {
  const tabs: { key: Tab; label: string; hint: string }[] = [
    { key: "analyze", label: "Analyze", hint: "1" },
    { key: "history", label: "History", hint: "2" },
    { key: "batch", label: "Batch", hint: "3" },
    { key: "compare", label: "Compare", hint: "4" },
  ];
  const s0 = result?.recording_summary;
  return (
    <header style={{ borderBottom: "1px solid var(--border-hairline)", background: "var(--bg-panel)" }}>
      <div style={{ display: "flex", alignItems: "stretch", height: 52 }}>
        {/* wordmark: the tick marks read as a frequency scale, which is
            what this instrument actually measures */}
        <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "0 18px", borderRight: "1px solid var(--border-hairline)", minWidth: 210 }}>
          <svg width="18" height="20" viewBox="0 0 18 20" aria-hidden="true">
            {[0, 1, 2, 3, 4].map((i) => (
              <rect key={i} x={i * 4} y={10 - [4, 8, 10, 7, 3][i]} width="2"
                    height={[8, 16, 20, 14, 6][i]} fill="var(--status-estimated)"
                    opacity={[0.35, 0.6, 1, 0.6, 0.35][i]} />
            ))}
          </svg>
          <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--text-primary)" }}>
            Nyquist
          </span>
        </div>

        {/* live readout strip — an instrument always shows its current
            operating conditions, not marketing copy */}
        <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 0, overflow: "hidden" }}>
          {s0 ? (
            <>
              <Readout label="Sample rate" value={s0.sample_rate_hz ? fmtHz(s0.sample_rate_hz) : "not set"} known={!!s0.sample_rate_hz} />
              <Readout label="Center" value={s0.center_freq_hz ? fmtHz(s0.center_freq_hz) : "not set"} known={!!s0.center_freq_hz} />
              <Readout label="Duration" value={s0.duration_s ? `${s0.duration_s.toFixed(3)} s` : "not set"} known={!!s0.duration_s} />
              <Readout label="Format" value={s0.source_format ?? "unknown"} known={!!s0.source_format} />
              <Readout label="Signals" value={String(result?.signals.length ?? 0)} known />
            </>
          ) : (
            <span style={{ paddingLeft: 18, fontSize: 12.5, color: "var(--text-tertiary)" }}>
              {phase === "analyzing" ? "Running analysis…" : phase === "uploading" ? "Loading recording…" : "No recording loaded"}
            </span>
          )}
        </div>

        <nav style={{ display: "flex", alignItems: "stretch", borderLeft: "1px solid var(--border-hairline)" }}>
          {tabs.map((t) => {
            const active = tab === t.key;
            return (
              <button key={t.key} onClick={() => setTab(t.key)} title={`Shortcut: ${t.hint}`}
                style={{
                  padding: "0 17px", border: "none", background: active ? "var(--bg-panel-raised)" : "transparent",
                  color: active ? "var(--text-primary)" : "var(--text-secondary)",
                  fontSize: 13, fontWeight: active ? 500 : 400, cursor: "pointer",
                  borderBottom: active ? "2px solid var(--status-estimated)" : "2px solid transparent",
                  borderLeft: "1px solid var(--border-hairline)",
                }}>
                {t.label}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

function Readout({ label, value, known }: { label: string; value: string; known: boolean }) {
  return (
    <div style={{ padding: "0 16px", borderRight: "1px solid var(--border-hairline)", height: "100%",
                  display: "flex", flexDirection: "column", justifyContent: "center", minWidth: 108 }}>
      <span style={{ fontSize: 10.5, color: "var(--text-tertiary)", lineHeight: 1.3 }}>{label}</span>
      <span className="num" style={{ fontSize: 13, lineHeight: 1.35,
        color: known ? "var(--text-primary)" : "var(--text-tertiary)",
        fontWeight: known ? 500 : 300, fontStyle: known ? "normal" : "italic" }}>{value}</span>
    </div>
  );
}

export function fmtHz(hz: number): string {
  if (Math.abs(hz) >= 1e9) return `${(hz / 1e9).toFixed(3)} GHz`;
  if (Math.abs(hz) >= 1e6) return `${(hz / 1e6).toFixed(3)} MHz`;
  if (Math.abs(hz) >= 1e3) return `${(hz / 1e3).toFixed(1)} kHz`;
  return `${hz.toFixed(0)} Hz`;
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
      <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 9, fontWeight: 500 }}>
        Override detected values
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
      <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 9, fontWeight: 500 }}>
        Your corrections
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
        Warnings
      </div>
      {warnings.map((w, i) => (
        <div key={i} style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5, marginBottom: 4 }}>
          {w}
        </div>
      ))}
    </div>
  );
}


function GroundTruthPanel({
  expected, title, result,
}: {
  expected: Record<string, unknown>;
  title: string | null;
  result: AnalysisResultJSON;
}) {
  const found = (name: string): string => {
    const p = result.parameters.find((x) => x.name === name);
    if (!p || p.value === null || p.value === undefined) return "\u2014";
    return typeof p.value === "number" ? (Number.isInteger(p.value) ? String(p.value) : p.value.toFixed(1)) : String(p.value);
  };
  const rows: [string, string, string][] = [
    ["modulation", String(expected.modulation ?? "\u2014"), found("modulation")],
    ["sample_rate_hz", String(expected.sample_rate_hz ?? "\u2014"), found("sample_rate_hz")],
    ["center_freq_hz", String(expected.center_freq_hz ?? "\u2014"), found("center_frequency_hz")],
    ["symbol_rate_hz", String(expected.symbol_rate_hz ?? "\u2014"), found("symbol_rate_hz")],
  ];
  return (
    <div className="panel" style={{ padding: "14px 16px", borderColor: "var(--status-detected)44" }}>
      <div style={{ fontSize: 12, color: "var(--status-detected)", marginBottom: 3, fontWeight: 500 }}>
        Known ground truth
      </div>
      {title && <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginBottom: 8 }}>{title}</div>}
      <div className="mono" style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: "3px 10px", fontSize: 10.5 }}>
        <span style={{ color: "var(--text-tertiary)" }} />
        <span style={{ color: "var(--text-tertiary)", textAlign: "right" }}>expected</span>
        <span style={{ color: "var(--text-tertiary)", textAlign: "right" }}>found</span>
        {rows.map(([k, exp, act]) => (
          <Fragment key={k}>
            <span style={{ color: "var(--text-tertiary)" }}>{k.replace(/_hz$/, "")}</span>
            <span style={{ color: "var(--text-secondary)", textAlign: "right" }}>{exp}</span>
            <span style={{ color: act === "\u2014" ? "var(--text-tertiary)" : "var(--status-detected)", textAlign: "right" }}>{act}</span>
          </Fragment>
        ))}
      </div>
      <div style={{ fontSize: 9.5, color: "var(--text-tertiary)", marginTop: 8, lineHeight: 1.45 }}>
        Values are compared as reported. A mismatch on a deliberately hard sample (e.g. the low-SNR case)
        is the honest, expected outcome &mdash; not a failure to hide.
      </div>
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
    background: disabled ? "var(--bg-panel-raised)" : "var(--status-estimated)",
    color: disabled ? "var(--text-tertiary)" : "#0b1620",
    fontWeight: 500,
    fontSize: 13,
    cursor: disabled ? "default" : "pointer",
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
