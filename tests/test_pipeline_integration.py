import numpy as np
import pytest

from rfplatform.models.schema import Status
from rfplatform.pipeline.stages import run_pipeline
from rfplatform.synth.generator import SynthConfig, generate, save_sigmf


@pytest.fixture
def synthetic_qpsk_file(tmp_path):
    cfg = SynthConfig(modulation="qpsk", n_symbols=5000, snr_db=20, seed=42,
                       sample_rate_hz=200_000, samples_per_symbol=8, freq_offset_hz=0.0)
    result = generate(cfg)
    data_path = tmp_path / "test_signal.sigmf-data"
    save_sigmf(result, str(data_path))
    return str(data_path), result


def test_pipeline_runs_end_to_end_on_real_file(synthetic_qpsk_file):
    path, ground_truth = synthetic_qpsk_file
    result = run_pipeline(path)

    assert result.recording_summary["sample_rate_hz"] == ground_truth.config.sample_rate_hz
    assert result.recording_summary["metadata_status"] == "sidecar_sigmf"

    mod_param = next(p for p in result.parameters if p.name == "modulation")
    assert mod_param.value == "qpsk"
    assert mod_param.status in (Status.INFERRED, Status.HYPOTHESIZED)

    assert result.demod_result is not None
    assert result.demod_result["evm_percent"] < 40

    assert result.bitstream_analysis is not None
    assert len(result.bitstream_analysis["hex_preview"]) > 0

    # every stage should have actually run (none crashed silently)
    stage_statuses = {s.name: s.status for s in result.stages}
    assert stage_statuses["ingestion_normalization"] == "ok"
    assert "error" not in stage_statuses.values()


def test_pipeline_manifest_is_reproducible(synthetic_qpsk_file):
    path, _ = synthetic_qpsk_file
    r1 = run_pipeline(path)
    r2 = run_pipeline(path)
    assert r1.manifest.input_file_hash == r2.manifest.input_file_hash
    assert r1.manifest.pipeline_version == r2.manifest.pipeline_version


def test_pipeline_analyst_override_forces_modulation_and_skips_classification(synthetic_qpsk_file):
    path, _ = synthetic_qpsk_file
    result = run_pipeline(path, overrides={"modulation": "8psk"})
    mod_param = next(p for p in result.parameters if p.name == "modulation")
    assert mod_param.value == "8psk"
    assert mod_param.status == Status.DETECTED  # analyst-provided values are DETECTED, not inferred
    assert result.manifest.parameters_used["modulation"] == "8psk"


def test_pipeline_handles_missing_sample_rate_gracefully(tmp_path):
    """A raw .cf32 file with no SigMF sidecar and no explicit sample rate --
    the pipeline must not crash, and must honestly warn rather than silently
    guessing a sample rate."""
    cfg = SynthConfig(modulation="bpsk", n_symbols=1000, seed=1, sample_rate_hz=200_000)
    result = generate(cfg)
    raw_path = tmp_path / "unknown.cf32"
    result.iq.astype(np.complex64).tofile(raw_path)

    analysis = run_pipeline(str(raw_path))
    assert any("sample rate" in w.lower() for w in analysis.manifest.warnings)


def test_pipeline_finds_signal_beyond_old_fixed_window_cap(tmp_path):
    """
    Regression test for the fixed-window bug this module used to have: an
    earlier version capped noise/detection analysis to the first 2,000,000
    samples of any file, so a signal located later would be silently
    invisible -- not merely slower to reach, genuinely never looked at.
    This builds a file with a real BPSK signal starting well past that old
    cutoff and confirms the pipeline (via chunked full-file scanning, see
    rfplatform/dsp/chunked.py) actually finds and correctly classifies it.
    """
    sample_rate_hz = 200_000.0
    rng = np.random.default_rng(7)
    n_noise_only = 3_000_000  # already exceeds the old 2,000,000-sample cap by itself
    noise_prefix = ((rng.standard_normal(n_noise_only) + 1j * rng.standard_normal(n_noise_only))
                     * 0.02).astype(np.complex64)

    cfg = SynthConfig(modulation="bpsk", n_symbols=6000, snr_db=20, seed=7,
                       sample_rate_hz=sample_rate_hz, samples_per_symbol=8)
    signal_result = generate(cfg)

    noise_suffix = ((rng.standard_normal(500_000) + 1j * rng.standard_normal(500_000))
                     * 0.02).astype(np.complex64)

    full = np.concatenate([noise_prefix, signal_result.iq, noise_suffix])
    path = tmp_path / "large_with_late_signal.cf32"
    full.astype(np.complex64).tofile(path)

    result = run_pipeline(str(path), sample_rate_hz=sample_rate_hz)

    # the detected region must actually reach into where the signal lives
    # (starting at sample 3,000,000) -- not be confined to the old capped window
    assert any(end > n_noise_only for _, end in result.detected_regions)

    mod_param = next(p for p in result.parameters if p.name == "modulation")
    assert mod_param.value == "bpsk"

    detection_stage = next(s for s in result.stages if s.name == "signal_detection_segmentation")
    assert detection_stage.detail["total_samples_scanned"] >= len(full) * 0.9  # scanned essentially the whole file


def test_pipeline_bitstream_analysis_present_when_demod_succeeds(synthetic_qpsk_file):
    path, _ = synthetic_qpsk_file
    result = run_pipeline(path)
    assert result.bitstream_analysis["length_bits"] > 0
    assert "best_byte_alignment" in result.bitstream_analysis
