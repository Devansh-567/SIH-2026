import numpy as np
import pytest

from rfplatform.dsp.demodulate import demodulate
from rfplatform.synth.generator import SynthConfig, generate


def _ber(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 1.0
    return float(np.mean(a[:n] != b[:n]))


@pytest.mark.parametrize("modulation,order_bits", [
    ("bpsk", 1), ("qpsk", 2), ("8psk", 3), ("16qam", 4), ("64qam", 6),
])
def test_psk_qam_demod_low_ber_at_high_snr(modulation, order_bits):
    cfg = SynthConfig(modulation=modulation, n_symbols=3000, snr_db=25, seed=42,
                       sample_rate_hz=200_000, samples_per_symbol=8, freq_offset_hz=0.0)
    result = generate(cfg)
    demod = demodulate(modulation, result.iq, samples_per_symbol=cfg.samples_per_symbol)
    ber = _ber(demod.bits, result.bits)
    assert ber < 0.05, f"{modulation}: BER={ber:.4f} too high at 25dB SNR"
    assert demod.evm_percent < 30


@pytest.mark.parametrize("modulation", ["2fsk", "4fsk"])
def test_fsk_demod_low_ber_at_high_snr(modulation):
    cfg = SynthConfig(modulation=modulation, n_symbols=3000, snr_db=20, seed=42,
                       sample_rate_hz=200_000, samples_per_symbol=8, fsk_deviation_hz=8_000)
    result = generate(cfg)
    demod = demodulate(modulation, result.iq, samples_per_symbol=cfg.samples_per_symbol,
                        deviation_hz=cfg.fsk_deviation_hz, sample_rate_hz=cfg.sample_rate_hz)
    ber = _ber(demod.bits, result.bits)
    assert ber < 0.08, f"{modulation}: BER={ber:.4f} too high at 20dB SNR"


def test_psk_demod_tolerates_small_carrier_offset():
    """Carrier-offset correction should recover a clean demod even with a
    real (non-zero) frequency offset injected -- not just the zero-offset case."""
    cfg = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=25, seed=7,
                       sample_rate_hz=200_000, samples_per_symbol=8, freq_offset_hz=1500.0)
    result = generate(cfg)
    demod = demodulate("qpsk", result.iq, samples_per_symbol=cfg.samples_per_symbol)
    ber = _ber(demod.bits, result.bits)
    assert ber < 0.1, f"BER={ber:.4f} with carrier offset -- correction may not be working"


def test_ber_degrades_at_low_snr():
    """Sanity check on the honesty contract: demod quality should visibly
    degrade at low SNR, not stay artificially perfect (which would indicate
    a test/measurement bug rather than real demodulation)."""
    cfg_hi = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=1, sample_rate_hz=200_000)
    cfg_lo = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=0, seed=1, sample_rate_hz=200_000)
    hi = generate(cfg_hi)
    lo = generate(cfg_lo)
    demod_hi = demodulate("qpsk", hi.iq, samples_per_symbol=cfg_hi.samples_per_symbol)
    demod_lo = demodulate("qpsk", lo.iq, samples_per_symbol=cfg_lo.samples_per_symbol)
    ber_hi = _ber(demod_hi.bits, hi.bits)
    ber_lo = _ber(demod_lo.bits, lo.bits)
    assert ber_lo > ber_hi
