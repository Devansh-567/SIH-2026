import numpy as np
import pytest

from rfplatform.synth.generator import SUPPORTED_MODULATIONS, SynthConfig, generate


@pytest.mark.parametrize("modulation", SUPPORTED_MODULATIONS)
def test_generate_all_modulations(modulation):
    cfg = SynthConfig(modulation=modulation, n_symbols=500, snr_db=15, seed=42)
    result = generate(cfg)
    assert result.iq.dtype == np.complex64
    assert len(result.iq) > 0
    assert not np.any(np.isnan(result.iq))
    assert not np.any(np.isinf(result.iq))
    assert result.ground_truth["modulation"] == modulation


def test_snr_affects_measured_power():
    cfg_clean = SynthConfig(modulation="qpsk", n_symbols=1000, snr_db=30, seed=1)
    cfg_noisy = SynthConfig(modulation="qpsk", n_symbols=1000, snr_db=0, seed=1)
    clean = generate(cfg_clean)
    noisy = generate(cfg_noisy)
    # at 0dB SNR the noise roughly doubles total measured power vs. signal-only baseline
    assert np.var(noisy.iq) > np.var(clean.iq) * 1.3


def test_seed_reproducibility():
    cfg = SynthConfig(modulation="bpsk", n_symbols=200, seed=7)
    r1 = generate(cfg)
    r2 = generate(cfg)
    np.testing.assert_array_equal(r1.bits, r2.bits)
    np.testing.assert_allclose(r1.iq, r2.iq)


def test_freq_offset_shifts_spectrum_peak():
    from scipy.signal import welch

    cfg = SynthConfig(modulation="bpsk", n_symbols=2000, snr_db=25, seed=3,
                       sample_rate_hz=200_000, freq_offset_hz=40_000)
    result = generate(cfg)
    freqs, psd = welch(result.iq, fs=cfg.sample_rate_hz, nperseg=1024, return_onesided=False)
    peak_freq = freqs[np.argmax(psd)]
    assert abs(peak_freq - 40_000) < 5_000  # peak should land near the injected offset
