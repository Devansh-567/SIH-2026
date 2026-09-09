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

from rfplatform.dsp import chunked
from rfplatform.dsp import classifier as dsp_classifier
from rfplatform.dsp import demodulate as demod_module
from rfplatform.dsp import estimators as est
<<<<<<< HEAD
from rfplatform.dsp import fingerprint as fingerprint_module
=======
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
from rfplatform.fec import convolutional as convfec
from rfplatform.fec import reed_solomon as rsfec
from rfplatform.interleave import interleavers as il
from rfplatform.io.formats import MissingSigMFMetadataError, RecordingHandle, load_recording
from rfplatform.models.schema import AnalysisManifest, Evidence, Parameter, Status
from rfplatform.pipeline import bitstream as bitstream_module
from rfplatform.pipeline.fusion import fuse_modulation

PIPELINE_VERSION = "0.1.0-mvp"
FEC_HYPOTHESIS_MAX_BITS = 4000  # see rationale at the FEC stage below
NOISE_CHUNK_SIZE = 2_000_000    # per-chunk size for the full-file streaming scan (peak memory bound)
SOI_ANALYSIS_MAX_SAMPLES = 2_000_000  # deep per-sample analysis cap on the selected signal-of-interest region
<<<<<<< HEAD
MAX_SIGNALS_PER_FILE = 5        # cap on how many detected regions get full per-signal analysis (see run_pipeline)
=======
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2


@dataclass
class StageResult:
    name: str
    status: str  # "ok" | "skipped" | "error"
    duration_s: float
    detail: dict = field(default_factory=dict)


@dataclass
<<<<<<< HEAD
class SignalResult:
    """
    Everything Stages 7-16 produce for ONE detected signal region. A file
    with multiple simultaneous signals produces one of these per analyzed
    region (see MAX_SIGNALS_PER_FILE) -- this is the concrete unit that
    "automatic multi-signal segmentation" was missing: previously only the
    single largest region ever got a demod/FEC/bitstream pass at all.
    """
    region: tuple[int, int]
    parameters: list[Parameter]
    demod_result: dict | None
    fec_hypotheses: dict
    deinterleave_hypotheses: dict
    bitstream_analysis: dict | None
    fingerprint: list[float]
    stages: list["StageResult"] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "region": list(self.region),
            "parameters": [p.as_dict() for p in self.parameters],
            "demod_result": self.demod_result,
            "fec_hypotheses": self.fec_hypotheses,
            "deinterleave_hypotheses": self.deinterleave_hypotheses,
            "bitstream_analysis": self.bitstream_analysis,
            "fingerprint": self.fingerprint,
            "stages": [{"name": s.name, "status": s.status, "duration_s": round(s.duration_s, 4),
                        "detail": s.detail} for s in self.stages],
        }


@dataclass
=======
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
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
<<<<<<< HEAD
    signals: list[SignalResult] = field(default_factory=list)
=======
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2

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
<<<<<<< HEAD
            "signals": [s.as_dict() for s in self.signals],
=======
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
        }


def _run_ml_classifier(iq: np.ndarray, sample_rate_hz: float) -> Parameter | None:
    """
    Stage 9 (AI classification). Wired to the trained CNN classifier
    (rfplatform/ml/) -- returns None (graceful DSP-only fallback, exactly
    as before) if no checkpoint has been trained yet, so a fresh checkout
    without a checkpoint file still runs end-to-end.
    """
    from rfplatform.ml.inference import ModelUnavailableError, classify
    try:
        return classify(iq)
    except ModelUnavailableError:
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


def _provenance_parameter(name: str, value: float | None, unit: str, source: str | None,
                           unknown_description: str) -> Parameter:
    """
    Builds a Parameter for a value that either came from trusted metadata/
    an analyst override (Status.DETECTED, confidence 1.0) or is genuinely
    unavailable (Status.UNKNOWN, value None) -- used for sample_rate_hz and
    center_frequency_hz so their provenance is visible in the same
    Parameter/Evidence model as every other extracted value, rather than
    being a special case only shown in recording_summary.
    """
    if value is None or not value:
        return Parameter(name=name, value=None, status=Status.UNKNOWN, confidence=0.0, unit=unit,
                          evidence=[Evidence(source="ingestion", description=unknown_description)])
    source_label = source or "metadata"
    description = {
        "sigmf_metadata": "Read directly from the .sigmf-meta sidecar.",
        "wav_header": "Read directly from the WAV file's RIFF header.",
        "analyst_override": "Manually set by the analyst, overriding any detected value.",
    }.get(source_label, "Provided value.")
    return Parameter(name=name, value=value, status=Status.DETECTED, confidence=1.0, unit=unit,
                      evidence=[Evidence(source=source_label, description=description)])


def run_pipeline(file_path: str, fmt: str | None = None, sample_rate_hz: float | None = None,
                  center_freq_hz: float | None = None,
                  overrides: dict | None = None) -> AnalysisResult:
    """
    Run the full MVP pipeline on a single file. `overrides` supports the
    analyst-in-the-loop workflow (PART 8/16): pass e.g.
    {"sample_rate_hz": 250000, "modulation": "qpsk"} to force those values
    and skip the corresponding estimation/classification stages.

    Honesty contract (see rfplatform/io/formats.py module docstring): this
    function NEVER substitutes a placeholder sample rate (e.g. 1 Hz) when
    one cannot be resolved from metadata or an override. If sample rate is
    unknown, every frequency-dependent stage (noise floor via PSD,
    detection, spectral/symbol-rate estimation, demodulation, etc.) is
    explicitly skipped with a stated reason, and `sample_rate_hz` is
    reported as a Parameter with Status.UNKNOWN -- never a fabricated
    number silently feeding downstream Hz-scaled math.
    """
    overrides = overrides or {}
    stages: list[StageResult] = []
    manifest = AnalysisManifest(input_file=file_path, pipeline_version=PIPELINE_VERSION)

    t0 = time.time()
    manifest.input_file_hash = _file_hash(file_path)
    stages.append(StageResult("file_identification", "ok", time.time() - t0))

    # Stage 1-2: ingestion + normalization. MissingSigMFMetadataError is
    # allowed to propagate to the caller (API layer maps it to a clear
    # HTTP 400) rather than being caught here -- a .sigmf-data file whose
    # datatype can't be resolved isn't a "degraded analysis", it's bytes we
    # cannot honestly decode into IQ samples at all.
    t0 = time.time()
    handle = load_recording(file_path, fmt=fmt, sample_rate_hz=sample_rate_hz, center_freq_hz=center_freq_hz)

    sample_rate_source = "sigmf_metadata" if handle.metadata_status == "sidecar_sigmf" else (
        "wav_header" if handle.metadata_status == "trusted_metadata" else None)
    center_freq_source = "sigmf_metadata" if handle.center_freq_hz is not None and handle.sigmf_meta_path else None

    if "sample_rate_hz" in overrides:
        handle.sample_rate_hz = overrides["sample_rate_hz"]
        manifest.parameters_used["sample_rate_hz"] = overrides["sample_rate_hz"]
        sample_rate_source = "analyst_override"
    if "center_freq_hz" in overrides:
        handle.center_freq_hz = overrides["center_freq_hz"]
        manifest.parameters_used["center_freq_hz"] = overrides["center_freq_hz"]
        center_freq_source = "analyst_override"

    sample_rate_known = bool(handle.sample_rate_hz)
    if not sample_rate_known:
        manifest.warnings.append(
            "Sample rate could not be determined from file metadata, and no analyst override was "
            "provided. Every frequency-dependent stage below has been skipped rather than run "
            "against a fabricated sample rate -- supply core:sample_rate via a .sigmf-meta sidecar, "
            "or set sample_rate_hz as an analyst override, then re-run."
        )

    stages.append(StageResult("ingestion_normalization", "ok", time.time() - t0, {
        "source_format": handle.source_format, "metadata_status": handle.metadata_status,
        "num_samples": handle.num_samples, "sample_rate_known": sample_rate_known,
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

    parameters: list[Parameter] = [
        _provenance_parameter("sample_rate_hz", handle.sample_rate_hz, "Hz", sample_rate_source,
                               "No sample rate available from SigMF metadata, WAV header, or analyst override."),
        _provenance_parameter("center_frequency_hz", handle.center_freq_hz, "Hz", center_freq_source,
                               "No center frequency available from SigMF metadata or analyst override "
                               "(this file's frequency axis is baseband-relative only)."),
    ]

    if not sample_rate_known:
        # Every remaining stage is frequency-dependent (noise/PSD estimation,
        # detection, symbol-rate/modulation classification, demod, FEC,
        # bitstream framing all consume Hz-scale quantities derived from
        # sample_rate_hz) -- skip them all explicitly rather than run any of
        # them against a placeholder.
        skip_reason = {"reason": "sample_rate_hz is unknown; see manifest warnings"}
        for stage_name in ("noise_estimation", "signal_detection_segmentation", "parameter_extraction",
                           "ai_classification", "confidence_fusion", "demodulation_symbol_sync",
                           "de_interleaving", "fec_hypothesis_decoding", "bitstream_correlation_framing"):
            stages.append(StageResult(stage_name, "skipped", 0.0, skip_reason))
        manifest.stage_versions = {s.name: PIPELINE_VERSION for s in stages}
        return AnalysisResult(
            manifest=manifest, recording_summary=recording_summary, detected_regions=[],
            parameters=parameters, demod_result=None, fec_hypotheses={}, deinterleave_hypotheses={},
            bitstream_analysis=None, stages=stages,
        )

    # Stage 4: noise estimation -- scans the ENTIRE file, chunk by chunk
    # (peak memory bounded by one chunk), not just a fixed-size prefix.
    t0 = time.time()
    noise = chunked.estimate_noise_floor_chunked(handle, chunk_size=NOISE_CHUNK_SIZE)
    stages.append(StageResult("noise_estimation", "ok", time.time() - t0,
                               {"noise_floor_db": noise.noise_floor_db}))

    # Stage 5-6: detection + segmentation -- also a full-file streaming scan
    # (see rfplatform/dsp/chunked.py), so a signal located anywhere in a
    # large recording is found, not only one sitting in the first ~2M
    # samples of the file.
    t0 = time.time()
    detection = chunked.detect_signal_regions_chunked(handle, noise.noise_floor_db,
                                                        chunk_size=NOISE_CHUNK_SIZE)
    regions = detection.regions
    if not regions:
        regions = [(0, min(handle.num_samples, NOISE_CHUNK_SIZE))]  # fall back to a bounded window
        manifest.warnings.append("No signal region rose above the noise-floor threshold across the "
                                  "full recording; analyzing an initial window as a fallback.")
    stages.append(StageResult("signal_detection_segmentation", "ok", time.time() - t0,
                               {"num_regions": len(regions), "chunks_scanned": detection.chunks_scanned,
                                "total_samples_scanned": detection.total_samples_scanned}))

<<<<<<< HEAD
    # Stages 5-6 detected `regions`; analyze up to MAX_SIGNALS_PER_FILE of
    # them (largest first) as distinct signals -- this is the concrete
    # mechanism behind "automatic multi-signal segmentation": earlier
    # versions of this pipeline only ever ran stages 7-16 on the single
    # largest region, so a file with two simultaneous signals silently
    # analyzed only one of them. The primary (largest) region's results
    # are still mirrored onto the top-level `parameters`/`demod_result`/etc.
    # fields for backward compatibility with every existing consumer.
    ranked_regions = sorted(regions, key=lambda r: r[1] - r[0], reverse=True)[:MAX_SIGNALS_PER_FILE]
    if len(regions) > len(ranked_regions):
        manifest.warnings.append(
            f"{len(regions)} signal regions were detected; only the {len(ranked_regions)} largest "
            f"were fully analyzed (demodulation/FEC/bitstream) -- see MAX_SIGNALS_PER_FILE."
        )

    signals: list[SignalResult] = []
    top_demod_result: dict | None = None
    top_fec_hyps: dict = {}
    top_deinterleave_hyps: dict = {}
    top_bitstream_result: dict | None = None
    for i, region in enumerate(ranked_regions):
        sig_params, demod_result, fec_hyps, deinterleave_hyps, bitstream_result, sub_stages = _analyze_region(
            handle, region, overrides, manifest, center_freq_source,
        )
        fp = fingerprint_module.compute_fingerprint(sig_params)
        signals.append(SignalResult(
            region=region, parameters=sig_params, demod_result=demod_result, fec_hypotheses=fec_hyps,
            deinterleave_hypotheses=deinterleave_hyps, bitstream_analysis=bitstream_result,
            fingerprint=fp.vector, stages=sub_stages,
        ))
        if i == 0:
            # primary signal: mirror onto the flat top-level fields, and
            # merge its sub-stage timings into the main `stages` list --
            # this preserves the exact pre-multi-signal behavior/shape for
            # every existing caller (API, tests, GUI) that only knows about
            # a single signal per file.
            parameters += sig_params
            top_demod_result = demod_result
            top_fec_hyps = fec_hyps
            top_deinterleave_hyps = deinterleave_hyps
            top_bitstream_result = bitstream_result
            stages += sub_stages

    manifest.stage_versions = {s.name: PIPELINE_VERSION for s in stages}

    return AnalysisResult(
        manifest=manifest,
        recording_summary=recording_summary,
        detected_regions=regions,
        parameters=parameters,
        demod_result=top_demod_result,
        fec_hypotheses=top_fec_hyps,
        deinterleave_hypotheses=top_deinterleave_hyps,
        bitstream_analysis=top_bitstream_result,
        stages=stages,
        signals=signals,
    )


def _analyze_region(handle: RecordingHandle, region: tuple[int, int], overrides: dict,
                     manifest: AnalysisManifest, center_freq_source: str | None
                     ) -> tuple[list[Parameter], dict | None, dict, dict, dict | None, list[StageResult]]:
    """
    Runs Stages 7-16 (parameter extraction through bitstream correlation)
    on a single detected signal region. Extracted from run_pipeline so it
    can be called once per detected signal (see MAX_SIGNALS_PER_FILE)
    rather than only ever on the single largest region.
    """
    stages: list[StageResult] = []
    region_start, region_end = region
=======
    # MVP: analyze the single largest detected region (multi-signal handling
    # is a roadmap item). The region itself can legitimately span the whole
    # file for a continuous transmission, so the DEEP per-sample analysis
    # below (feature extraction, classification, demod) still bounds how
    # much of that region it processes -- this is a distinct, later cap
    # from the full-file scan above, and is a deliberate scoping choice
    # (a bounded sample of a long signal is enough for these estimates),
    # not a silent truncation of what gets *looked at*.
    largest = max(regions, key=lambda r: r[1] - r[0])
    region_start, region_end = largest
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
    region_len = min(region_end - region_start, SOI_ANALYSIS_MAX_SAMPLES)
    soi = np.asarray(handle.samples[region_start: region_start + region_len])

    # Stage 7-8: parameter extraction + DSP modulation hypothesis
    t0 = time.time()
<<<<<<< HEAD
    parameters = dsp_classifier.estimate_parameters(soi, handle.sample_rate_hz)
    dsp_mod_param = next(p for p in parameters if p.name == "modulation")

    if handle.center_freq_hz is not None:
        peak_param = next((p for p in parameters if p.name == "peak_frequency_hz"), None)
=======
    extracted = dsp_classifier.estimate_parameters(soi, handle.sample_rate_hz)
    dsp_mod_param = next(p for p in extracted if p.name == "modulation")
    parameters += extracted

    if handle.center_freq_hz is not None:
        peak_param = next((p for p in extracted if p.name == "peak_frequency_hz"), None)
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
        if peak_param is not None and peak_param.value is not None:
            absolute_hz = handle.center_freq_hz + peak_param.value
            parameters.append(Parameter(
                name="absolute_peak_frequency_hz", value=round(absolute_hz, 1), status=peak_param.status,
                confidence=peak_param.confidence, unit="Hz",
                evidence=[Evidence(
                    source="dsp:center_freq_plus_baseband_offset",
                    description=f"Center frequency ({handle.center_freq_hz:,.0f} Hz, from "
                                f"{center_freq_source or 'metadata'}) plus baseband peak offset "
                                f"({peak_param.value:,.1f} Hz).",
                )],
            ))
    stages.append(StageResult("parameter_extraction", "ok", time.time() - t0))

<<<<<<< HEAD
    # Stage 9: AI classification
=======
    # Stage 9: AI classification (stubbed in MVP)
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
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
<<<<<<< HEAD
        # Cap how much of the bitstream feeds hypothesis testing -- see
        # FEC_HYPOTHESIS_MAX_BITS's definition for the full rationale
        # (commpy's Viterbi decode is pure-Python and slow at scale; a
        # representative prefix is methodologically sufficient here).
=======
        # Cap how much of the bitstream feeds hypothesis testing. Two
        # independent reasons, not just speed: (1) commpy's Viterbi decode
        # is pure-Python with no vectorization -- measured ~1ms/bit per
        # preset, so decoding tens of thousands of bits x 3 presets turns a
        # single /analyze call into 10-20+ seconds, a real UX problem, not
        # just a slow test; (2) a representative prefix is *methodologically*
        # sufficient for hypothesis testing (which preset's re-encode most
        # closely matches, or which RS block validates) -- decoding the
        # entire recording's bitstream for a yes/no hypothesis check doesn't
        # add confidence proportional to its cost.
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
        fec_test_bits = demod_bits[:FEC_HYPOTHESIS_MAX_BITS]
        try:
            conv_results = convfec.hypothesis_search(fec_test_bits.astype(np.int64))
            fec_hyps["convolutional"] = [
                {"preset": r.preset_name, "reencode_distance_fraction": round(r.reencode_distance_fraction, 4)}
                for r in conv_results
            ]
        except Exception as e:
            fec_hyps["convolutional_error"] = str(e)
        try:
            rs_results = rsfec.hypothesis_search_from_bits(fec_test_bits.astype(np.uint8))
            fec_hyps["reed_solomon"] = [
                {"preset": r.preset_name, "success": r.success, "symbols_corrected": r.symbols_corrected,
                 "byte_alignment": r.byte_alignment, "parity_bytes": r.parity_bytes}
                for r in rs_results[:8]  # cap payload size; full ranking already computed
            ]
        except Exception as e:
            fec_hyps["reed_solomon_error"] = str(e)
        stages.append(StageResult("fec_hypothesis_decoding", "ok", time.time() - t0, {
            "convolutional_candidates": len(fec_hyps.get("convolutional", [])),
            "reed_solomon_candidates": len(fec_hyps.get("reed_solomon", [])),
            "bits_tested": len(fec_test_bits),
        }))
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

<<<<<<< HEAD
    return parameters, demod_result, fec_hyps, deinterleave_hyps, bitstream_result, stages
=======
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
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
