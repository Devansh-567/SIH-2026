"""
End-to-end pipeline orchestration -- implements Stages 1-17 of the
architecture report (PART "MULTI-STAGE ANALYSIS PIPELINE") in their MVP
form. This is what the FastAPI `/analyze` endpoint and any future GUI
"[ANALYZE SIGNAL]" button call.

MVP scope notes (consistent with the architecture report's PART 24):
  - single dominant signal region per file for FEC/de-interleave/bitstream
    stages (multi-signal separation is a documented roadmap item)
  - ML classification stage is stubbed (returns None) since no trained
    model is wired in yet -- the fusion engine already handles this
    gracefully (falls back to DSP-only) so wiring in a real model later
    is a one-line change in `_run_ml_classifier`, not a pipeline rewrite
  - FEC/interleaving stages run as best-effort hypothesis attempts on the
    demodulated bitstream; they do not assume ground truth is known
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

import numpy as np

from rfplatform.dsp import classifier as dsp_classifier
from rfplatform.dsp import demodulate as demod_module
from rfplatform.dsp import estimators as est
from rfplatform.fec import convolutional as convfec
from rfplatform.fec import reed_solomon as rsfec
from rfplatform.interleave import interleavers as il
from rfplatform.io.formats import RecordingHandle, load_recording
from rfplatform.models.schema import AnalysisManifest, Evidence, Parameter, Status
from rfplatform.pipeline import bitstream as bitstream_module
from rfplatform.pipeline.fusion import fuse_modulation

PIPELINE_VERSION = "0.1.0-mvp"


@dataclass
class StageResult:
    name: str
    status: str  # "ok" | "skipped" | "error"
    duration_s: float
    detail: dict = field(default_factory=dict)


@dataclass
class AnalysisResult:
    manifest: AnalysisManifest
    recording_summary: dict
    detected_regions: list[tuple[int, int]]
    parameters: list[Parameter]
    demod_result: dict | None
    fec_hypotheses: dict
    deinterleave_hypotheses: dict
    bitstream_analysis: dict | None
    stages: list[StageResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "manifest": self.manifest.as_dict(),
            "recording_summary": self.recording_summary,
            "detected_regions": self.detected_regions,
            "parameters": [p.as_dict() for p in self.parameters],
            "demod_result": self.demod_result,
            "fec_hypotheses": self.fec_hypotheses,
            "deinterleave_hypotheses": self.deinterleave_hypotheses,
            "bitstream_analysis": self.bitstream_analysis,
            "stages": [{"name": s.name, "status": s.status, "duration_s": round(s.duration_s, 4),
                        "detail": s.detail} for s in self.stages],
        }


def _run_ml_classifier(iq: np.ndarray, sample_rate_hz: float) -> Parameter | None:
    """
    Stage 9 (AI classification) -- STUB. No trained PyTorch model is wired
    in this MVP build (see architecture report PART 24/26: ML classifier
    training is a separate, later phase requiring a GPU-appropriate
    environment and the full synthetic training corpus). The fusion engine
    (PART 11) is already written to accept `None` here and fall back
    gracefully to DSP-only results with an explicit note in the evidence
    trail -- wiring in a real model later means replacing this function's
    body, nothing else in the pipeline changes.
    """
    return None


def _file_hash(path: str, max_bytes: int = 8 * 1024 * 1024) -> str:
    """Hash only a bounded prefix for large files -- full-file hashing of a
    100GB recording would itself violate the no-full-load rule; a prefix
    hash is sufficient for the reproducibility manifest's practical purpose
    (detecting 'did the input file change'), not cryptographic identity."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(max_bytes))
    return h.hexdigest()


def run_pipeline(file_path: str, fmt: str | None = None, sample_rate_hz: float | None = None,
                  center_freq_hz: float | None = None,
                  overrides: dict | None = None) -> AnalysisResult:
    """
    Run the full MVP pipeline on a single file. `overrides` supports the
    analyst-in-the-loop workflow (PART 8/16): pass e.g.
    {"sample_rate_hz": 250000, "modulation": "qpsk"} to force those values
    and skip the corresponding estimation/classification stages.
    """
    overrides = overrides or {}
    stages: list[StageResult] = []
    manifest = AnalysisManifest(input_file=file_path, pipeline_version=PIPELINE_VERSION)

    t0 = time.time()
    manifest.input_file_hash = _file_hash(file_path)
    stages.append(StageResult("file_identification", "ok", time.time() - t0))

    # Stage 1-2: ingestion + normalization
    t0 = time.time()
    handle = load_recording(file_path, fmt=fmt, sample_rate_hz=sample_rate_hz, center_freq_hz=center_freq_hz)
    if "sample_rate_hz" in overrides:
        handle.sample_rate_hz = overrides["sample_rate_hz"]
        manifest.parameters_used["sample_rate_hz"] = overrides["sample_rate_hz"]
    if not handle.sample_rate_hz:
        manifest.warnings.append("No sample rate available from metadata or override; "
                                  "downstream frequency-domain results are unreliable.")
        handle.sample_rate_hz = 1.0  # placeholder to avoid division-by-zero; flagged via warning above
    stages.append(StageResult("ingestion_normalization", "ok", time.time() - t0, {
        "source_format": handle.source_format, "metadata_status": handle.metadata_status,
        "num_samples": handle.num_samples,
    }))

    recording_summary = {
        "path": str(handle.path),
        "num_samples": handle.num_samples,
        "sample_rate_hz": handle.sample_rate_hz,
        "center_freq_hz": handle.center_freq_hz,
        "duration_s": handle.duration_s(),
        "source_format": handle.source_format,
        "metadata_status": handle.metadata_status,
    }

    # For MVP: analyze at most this many samples directly (chunked scan for
    # noise/detection across the whole file is a documented roadmap item;
    # this cap keeps the MVP responsive on large files without violating
    # correctness for the demo-scale files it's validated against).
    analysis_window = np.asarray(handle.samples[: min(handle.num_samples, 2_000_000)])

    # Stage 4: noise estimation
    t0 = time.time()
    noise = est.estimate_noise_floor(analysis_window, handle.sample_rate_hz)
    stages.append(StageResult("noise_estimation", "ok", time.time() - t0,
                               {"noise_floor_db": noise.noise_floor_db}))

    # Stage 5-6: detection + segmentation
    t0 = time.time()
    regions = est.detect_signal_regions(analysis_window, handle.sample_rate_hz, noise.noise_floor_db)
    if not regions:
        regions = [(0, len(analysis_window))]  # fall back to whole-window analysis
        manifest.warnings.append("No signal region rose above the noise-floor threshold; "
                                  "analyzing the full window as a fallback.")
    stages.append(StageResult("signal_detection_segmentation", "ok", time.time() - t0,
                               {"num_regions": len(regions)}))

    # MVP: analyze the single largest detected region (multi-signal handling is a roadmap item)
    largest = max(regions, key=lambda r: r[1] - r[0])
    soi = analysis_window[largest[0]: largest[1]]

    # Stage 7-8: parameter extraction + DSP modulation hypothesis
    t0 = time.time()
    parameters = dsp_classifier.estimate_parameters(soi, handle.sample_rate_hz)
    dsp_mod_param = next(p for p in parameters if p.name == "modulation")
    stages.append(StageResult("parameter_extraction", "ok", time.time() - t0))

    # Stage 9: AI classification (stubbed in MVP)
    t0 = time.time()
    ml_param = _run_ml_classifier(soi, handle.sample_rate_hz)
    stages.append(StageResult("ai_classification", "skipped" if ml_param is None else "ok", time.time() - t0,
                               {"reason": "no trained model wired in this MVP build"} if ml_param is None else {}))

    # Stage 10: confidence fusion
    t0 = time.time()
    if "modulation" in overrides:
        fused_mod = Parameter(name="modulation", value=overrides["modulation"], status=Status.DETECTED,
                               confidence=1.0,
                               evidence=[Evidence(source="analyst_override",
                                                   description="Analyst manually set this value.")])
        manifest.parameters_used["modulation"] = overrides["modulation"]
    else:
        fused_mod = fuse_modulation(dsp_mod_param, ml_param)
    parameters = [p for p in parameters if p.name != "modulation"] + [fused_mod]
    stages.append(StageResult("confidence_fusion", "ok", time.time() - t0))

    # Stage 11-12: demodulation + symbol sync
    demod_result = None
    t0 = time.time()
    symbol_rate_param = next((p for p in parameters if p.name == "symbol_rate_hz"), None)
    if fused_mod.status != Status.UNKNOWN and symbol_rate_param and symbol_rate_param.value:
        try:
            sps = max(2, int(round(handle.sample_rate_hz / symbol_rate_param.value)))
            extra = {}
            if fused_mod.value in ("2fsk", "4fsk"):
                extra = {"deviation_hz": symbol_rate_param.value * 1.5, "sample_rate_hz": handle.sample_rate_hz}
            demod = demod_module.demodulate(fused_mod.value, soi, samples_per_symbol=sps, **extra)
            demod_result = {
                "modulation": demod.modulation, "num_bits": len(demod.bits),
                "evm_percent": round(demod.evm_percent, 2), "lock_quality": round(demod.lock_quality, 3),
                "samples_per_symbol_used": demod.samples_per_symbol_used, "notes": demod.notes,
                "bits_preview": demod.bits[:64].tolist(),
            }
            demod_bits = demod.bits
            stages.append(StageResult("demodulation_symbol_sync", "ok", time.time() - t0,
                                       {"evm_percent": demod_result["evm_percent"]}))
        except Exception as e:
            demod_bits = None
            stages.append(StageResult("demodulation_symbol_sync", "error", time.time() - t0, {"error": str(e)}))
    else:
        demod_bits = None
        stages.append(StageResult("demodulation_symbol_sync", "skipped", time.time() - t0,
                                   {"reason": "modulation confidence below usable threshold or no symbol-rate estimate"}))

    # Stage 13: de-interleaving hypothesis search
    t0 = time.time()
    deinterleave_hyps: dict = {}
    if demod_bits is not None and len(demod_bits) >= 64:
        block_results = il.block_hypothesis_search(demod_bits, max_dim=16)
        deinterleave_hyps["block"] = [
            {"rows": r.params["rows"], "cols": r.params["cols"], "structure_score": round(r.score, 4)}
            for r in block_results
        ]
        deinterleave_hyps["pseudo_random_note"] = il.pseudorandom_deinterleave_hypothesis(demod_bits).note
        stages.append(StageResult("de_interleaving", "ok", time.time() - t0,
                                   {"block_candidates": len(block_results)}))
    else:
        stages.append(StageResult("de_interleaving", "skipped", time.time() - t0,
                                   {"reason": "insufficient demodulated bits"}))

    # Stage 14: FEC hypothesis + decoding
    t0 = time.time()
    fec_hyps: dict = {}
    if demod_bits is not None and len(demod_bits) >= 200:
        try:
            conv_results = convfec.hypothesis_search(demod_bits.astype(np.int64))
            fec_hyps["convolutional"] = [
                {"preset": r.preset_name, "reencode_distance_fraction": round(r.reencode_distance_fraction, 4)}
                for r in conv_results
            ]
        except Exception as e:
            fec_hyps["convolutional_error"] = str(e)
        stages.append(StageResult("fec_hypothesis_decoding", "ok", time.time() - t0))
    else:
        stages.append(StageResult("fec_hypothesis_decoding", "skipped", time.time() - t0,
                                   {"reason": "insufficient demodulated bits"}))

    # Stage 15-16: bitstream correlation + framing
    t0 = time.time()
    bitstream_result = None
    if demod_bits is not None and len(demod_bits) >= 32:
        analysis = bitstream_module.analyze_bitstream(demod_bits)
        bitstream_result = {
            "length_bits": analysis.length_bits,
            "preamble_matches": [
                {"name": m.name, "position": m.bit_position, "hamming_distance": m.hamming_distance}
                for m in analysis.preamble_matches[:10]
            ],
            "framing_hypotheses": [
                {"frame_length_bits": h.frame_length_bits, "confidence": round(h.confidence, 3)}
                for h in analysis.framing_hypotheses
            ],
            "best_byte_alignment": analysis.best_byte_alignment,
            "byte_alignment_confidence": round(analysis.byte_alignment_confidence, 3),
            "hex_preview": analysis.hex_preview,
            "ascii_preview": analysis.ascii_preview,
        }
        stages.append(StageResult("bitstream_correlation_framing", "ok", time.time() - t0,
                                   {"num_preamble_matches": len(analysis.preamble_matches)}))
    else:
        stages.append(StageResult("bitstream_correlation_framing", "skipped", time.time() - t0,
                                   {"reason": "insufficient demodulated bits"}))

    manifest.stage_versions = {s.name: PIPELINE_VERSION for s in stages}

    return AnalysisResult(
        manifest=manifest,
        recording_summary=recording_summary,
        detected_regions=regions,
        parameters=parameters,
        demod_result=demod_result,
        fec_hypotheses=fec_hyps,
        deinterleave_hypotheses=deinterleave_hyps,
        bitstream_analysis=bitstream_result,
        stages=stages,
    )
