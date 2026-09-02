import numpy as np
import pytest

from rfplatform.dsp.chunked import (
    detect_signal_regions_chunked, estimate_noise_floor_chunked, _merge_regions,
)
from rfplatform.io.formats import load_recording


@pytest.fixture
def noisy_file_with_late_burst(tmp_path):
    """5,000,000-sample file, mostly low-level noise, with a strong tone
    burst at samples [3,500,000 : 3,600,000] -- far past the old fixed
    2,000,000-sample analysis window."""
    sample_rate = 200_000
    rng = np.random.default_rng(1)
    n_total = 5_000_000
    noise = ((rng.standard_normal(n_total) + 1j * rng.standard_normal(n_total)) * 0.05).astype(np.complex64)

    burst_start, burst_len = 3_500_000, 100_000
    t = np.arange(burst_len) / sample_rate
    burst = (np.exp(1j * 2 * np.pi * 20_000 * t) * 2.0).astype(np.complex64)
    noise[burst_start: burst_start + burst_len] += burst

    path = tmp_path / "late_burst.cf32"
    noise.tofile(path)
    handle = load_recording(str(path), sample_rate_hz=float(sample_rate))
    return handle, burst_start, burst_start + burst_len


def test_merge_regions_combines_overlapping():
    assert _merge_regions([(0, 100), (90, 200), (300, 400)]) == [(0, 200), (300, 400)]


def test_merge_regions_leaves_disjoint_alone():
    assert _merge_regions([(0, 10), (20, 30)]) == [(0, 10), (20, 30)]


def test_merge_regions_empty():
    assert _merge_regions([]) == []


def test_chunked_noise_floor_scans_multiple_chunks(noisy_file_with_late_burst):
    handle, _, _ = noisy_file_with_late_burst
    noise_est = estimate_noise_floor_chunked(handle, chunk_size=1_000_000)
    # sanity: noise floor should be a plausible dB value, not NaN/inf/wildly off
    assert -150 < noise_est.noise_floor_db < 0


def test_chunked_noise_floor_matches_single_window_estimate_on_small_file(tmp_path):
    """For a file smaller than one chunk, the chunked estimator should
    closely agree with the plain single-window estimator (same underlying
    math, see estimators.py::noise_floor_from_psd)."""
    from rfplatform.dsp.estimators import estimate_noise_floor

    rng = np.random.default_rng(2)
    iq = (rng.standard_normal(50_000) + 1j * rng.standard_normal(50_000)).astype(np.complex64)
    path = tmp_path / "small.cf32"
    iq.tofile(path)
    handle = load_recording(str(path), sample_rate_hz=200_000.0)

    chunked_est = estimate_noise_floor_chunked(handle, chunk_size=1_000_000)
    single_est = estimate_noise_floor(iq, 200_000.0)
    assert abs(chunked_est.noise_floor_db - single_est.noise_floor_db) < 1.0


def test_chunked_detection_finds_burst_beyond_old_fixed_cap(noisy_file_with_late_burst):
    handle, expected_start, expected_end = noisy_file_with_late_burst
    noise_est = estimate_noise_floor_chunked(handle, chunk_size=1_000_000)
    result = detect_signal_regions_chunked(handle, noise_est.noise_floor_db, chunk_size=1_000_000)

    assert result.chunks_scanned >= 5
    assert result.total_samples_scanned >= handle.num_samples * 0.9

    assert len(result.regions) >= 1
    best = max(result.regions, key=lambda r: r[1] - r[0])
    # allow a small tolerance for the detector's window granularity
    assert abs(best[0] - expected_start) < 512
    assert abs(best[1] - expected_end) < 512


def test_chunked_detection_bounds_memory_per_chunk(noisy_file_with_late_burst):
    """Not a true RSS measurement (too environment-dependent to assert on
    reliably), but confirms the scan actually proceeds chunk-by-chunk --
    chunks_scanned should be roughly num_samples / chunk_size, not 1."""
    handle, _, _ = noisy_file_with_late_burst
    result = detect_signal_regions_chunked(handle, -80.0, chunk_size=1_000_000)
    expected_min_chunks = handle.num_samples // 1_000_000
    assert result.chunks_scanned >= expected_min_chunks
