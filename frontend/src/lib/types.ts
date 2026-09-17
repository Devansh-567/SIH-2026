export type Status = "DETECTED" | "ESTIMATED" | "INFERRED" | "HYPOTHESIZED" | "UNKNOWN";

export interface Evidence {
  source: string;
  description: string;
  weight: number;
  value: unknown;
}

export interface Alternative {
  value: unknown;
  confidence: number;
}

export interface Parameter {
  name: string;
  value: unknown;
  status: Status;
  confidence: number;
  unit: string | null;
  alternatives: Alternative[];
  evidence: Evidence[];
}

export interface StageInfo {
  name: string;
  status: "ok" | "skipped" | "error";
  duration_s: number;
  detail: Record<string, unknown>;
}

export interface Manifest {
  analysis_id: string;
  created_at: number;
  input_file: string;
  input_file_hash: string;
  pipeline_version: string;
  stage_versions: Record<string, string>;
  parameters_used: Record<string, unknown>;
  warnings: string[];
}

export interface RecordingSummary {
  path: string;
  num_samples: number;
  sample_rate_hz: number | null;
  center_freq_hz: number | null;
  duration_s: number | null;
  source_format: string;
  metadata_status: string;
}

export interface DemodResultJSON {
  modulation: string;
  num_bits: number;
  evm_percent: number;
  lock_quality: number;
  samples_per_symbol_used: number;
  notes: string[];
  bits_preview: number[];
  constellation?: [number, number][];
  constellation_total_symbols?: number;
}

export interface PreambleMatch {
  name: string;
  position: number;
  hamming_distance: number;
}

export interface FramingHypothesis {
  frame_length_bits: number;
  confidence: number;
}

export interface BitstreamAnalysisJSON {
  length_bits: number;
  preamble_matches: PreambleMatch[];
  framing_hypotheses: FramingHypothesis[];
  best_byte_alignment: number;
  byte_alignment_confidence: number;
  hex_preview: string;
  ascii_preview: string;
}

export interface ConvFecHypothesis {
  preset: string;
  reencode_distance_fraction: number;
}

export interface BlockDeinterleaveHypothesis {
  rows: number;
  cols: number;
  structure_score: number;
}

export interface ReedSolomonHypothesis {
  preset: string;
  success: boolean;
  symbols_corrected: number;
  byte_alignment: number;
  parity_bytes: number;
}

export interface SignalResultJSON {
  region: [number, number];
  parameters: Parameter[];
  demod_result: DemodResultJSON | null;
  fec_hypotheses: {
    convolutional?: ConvFecHypothesis[];
    convolutional_error?: string;
    reed_solomon?: ReedSolomonHypothesis[];
    reed_solomon_error?: string;
  };
  deinterleave_hypotheses: {
    block?: BlockDeinterleaveHypothesis[];
    pseudo_random_note?: string;
  };
  bitstream_analysis: BitstreamAnalysisJSON | null;
  fingerprint: number[];
  stages: StageInfo[];
}

export interface AnalysisResultJSON {
  manifest: Manifest;
  recording_summary: RecordingSummary;
  detected_regions: [number, number][];
  parameters: Parameter[];
  demod_result: DemodResultJSON | null;
  fec_hypotheses: {
    convolutional?: ConvFecHypothesis[];
    convolutional_error?: string;
    reed_solomon?: ReedSolomonHypothesis[];
    reed_solomon_error?: string;
  };
  deinterleave_hypotheses: {
    block?: BlockDeinterleaveHypothesis[];
    pseudo_random_note?: string;
  };
  bitstream_analysis: BitstreamAnalysisJSON | null;
  stages: StageInfo[];
  signals: SignalResultJSON[];
}

export interface UploadEntry {
  file_id: string;
  recording_name: string;
  kind: "sigmf" | "standalone";
  sigmf_pair_complete: boolean | null;
  size_bytes?: number;
  data_size_bytes?: number;
  meta_size_bytes?: number;
}

export interface UploadResponse {
  uploads: UploadEntry[];
}

export interface SpectrogramJSON {
  freqs_hz: number[];
  times_s: number[];
  power_db: number[][];
  min_db: number;
  max_db: number;
  sample_rate_hz: number;
  center_freq_hz: number | null;
  is_absolute_frequency: boolean;
}

// --- History / batch / comparison / feedback / annotations / similarity ---

export interface HistoryEntry {
  id: string;
  created_at: number;
  input_file: string | null;
  source_format: string | null;
  sample_rate_hz: number | null;
  center_freq_hz: number | null;
  primary_modulation: string | null;
  primary_status: string | null;
  num_signals: number;
}

export interface HistoryListResponse {
  analyses: HistoryEntry[];
}

export interface ParameterDiff {
  name: string;
  status: "same" | "changed" | "only_in_a" | "only_in_b";
  value_a: unknown;
  value_b: unknown;
  status_a: string | null;
  status_b: string | null;
}

export interface CompareResult {
  analysis_id_a: string;
  analysis_id_b: string;
  recording: Record<string, { a: unknown; b: unknown; same: boolean }>;
  parameters: ParameterDiff[];
  num_parameters_compared: number;
  num_parameters_changed: number;
}

export interface BatchResultEntry {
  file_id: string;
  status: "ok" | "error";
  analysis_id?: string;
  modulation?: string | null;
  num_signals?: number;
  error?: string;
}

export interface BatchAnalyzeResponse {
  results: BatchResultEntry[];
  num_ok: number;
  num_failed: number;
}

export interface FeedbackEntry {
  id: number;
  analysis_id: string;
  parameter_name: string;
  original_value: unknown;
  original_status: string | null;
  corrected_value: unknown;
  note: string | null;
  created_at: number;
}

export interface AnnotationEntry {
  id: number;
  analysis_id: string;
  start_s: number;
  end_s: number | null;
  freq_hz: number | null;
  label: string | null;
  note: string | null;
  created_at: number;
}

export interface SimilarSignalEntry {
  signal_id: string;
  analysis_id: string;
  signal_index: number;
  region: [number | null, number | null];
  modulation: string | null;
  distance: number;
}

export interface SimilarSignalsResponse {
  query_analysis_id: string;
  query_signal_index: number;
  results: SimilarSignalEntry[];
}

// --- Demo sample catalog ---

export interface SampleSpec {
  id: string;
  title: string;
  description: string;
  highlights: string[];
  expected: Record<string, unknown>;
}

export interface SampleListResponse {
  samples: SampleSpec[];
}

export interface SampleLoadResponse {
  file_id: string;
  sample_id: string;
  title: string;
  expected: Record<string, unknown>;
  size_bytes: number;
}

export interface SignalViewJSON {
  sample_rate_hz: number | null;
  center_freq_hz: number | null;
  start_sample: number;
  num_samples_returned: number;
  total_samples: number;
  decimation: number;
  time_domain: { time_s: number[]; i: number[]; q: number[]; envelope: number[] };
  spectrum: {
    freqs_hz: number[];
    psd_db: number[];
    is_absolute_frequency: boolean;
    peak_freq_hz: number;
    peak_psd_db: number;
  };
}
