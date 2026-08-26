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

export interface AnalysisResultJSON {
  manifest: Manifest;
  recording_summary: RecordingSummary;
  detected_regions: [number, number][];
  parameters: Parameter[];
  demod_result: DemodResultJSON | null;
  fec_hypotheses: {
    convolutional?: ConvFecHypothesis[];
    convolutional_error?: string;
  };
  deinterleave_hypotheses: {
    block?: BlockDeinterleaveHypothesis[];
    pseudo_random_note?: string;
  };
  bitstream_analysis: BitstreamAnalysisJSON | null;
  stages: StageInfo[];
}

export interface SpectrogramJSON {
  freqs_hz: number[];
  times_s: number[];
  power_db: number[][];
  min_db: number;
  max_db: number;
  sample_rate_hz: number;
}
