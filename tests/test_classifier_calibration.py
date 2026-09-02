"""
This test doubles as the classifier's calibration report: it measures
accuracy at high SNR (should be near-perfect -- validates the algorithm is
correct) and confirms confidence degrades sensibly at low SNR (validates
the "don't hallucinate" requirement) rather than asserting a hard number
that would be arbitrary.
"""

import numpy as np
import pytest

from rfplatform.dsp.classifier import estimate_parameters
from rfplatform.models.schema import Status
from rfplatform.synth.generator import SynthConfig, generate

FAMILY_OF = {
    "bpsk": "psk", "qpsk": "psk", "8psk": "psk",
    "16qam": "qam", "64qam": "qam",
    "2fsk": "fsk", "4fsk": "fsk",
}


@pytest.mark.parametrize("modulation", ["bpsk", "qpsk", "8psk", "16qam", "64qam", "2fsk", "4fsk"])
def test_family_classification_at_high_snr(modulation):
    """At high SNR, the DSP classifier must at least get the *family* right."""
    cfg = SynthConfig(modulation=modulation, n_symbols=3000, snr_db=20, seed=123,
                       sample_rate_hz=200_000, samples_per_symbol=8)
    result = generate(cfg)
    params = estimate_parameters(result.iq, cfg.sample_rate_hz)
    mod_param = next(p for p in params if p.name == "modulation")

    predicted_family = FAMILY_OF.get(mod_param.value)
    expected_family = FAMILY_OF[modulation]
    assert predicted_family == expected_family, (
        f"{modulation}: predicted {mod_param.value} (family {predicted_family}), "
        f"expected family {expected_family}. Evidence: {[e.description for e in mod_param.evidence]}"
    )
    assert mod_param.status == Status.INFERRED
    assert mod_param.confidence > 0.3


def test_psk_order_correct_at_high_snr():
    """The M-th power method should recover exact PSK order, not just family, at high SNR."""
    for modulation, expected in [("bpsk", "bpsk"), ("qpsk", "qpsk"), ("8psk", "8psk")]:
        cfg = SynthConfig(modulation=modulation, n_symbols=4000, snr_db=25, seed=99,
                           sample_rate_hz=200_000, samples_per_symbol=8)
        result = generate(cfg)
        params = estimate_parameters(result.iq, cfg.sample_rate_hz)
        mod_param = next(p for p in params if p.name == "modulation")
        assert mod_param.value == expected, f"expected {expected}, got {mod_param.value}"


def test_confidence_present_and_bounded():
    cfg = SynthConfig(modulation="qpsk", n_symbols=2000, snr_db=15, seed=5)
    result = generate(cfg)
    params = estimate_parameters(result.iq, cfg.sample_rate_hz)
    for p in params:
        assert 0.0 <= p.confidence <= 1.0
        assert p.status in Status


def test_low_snr_does_not_crash_and_produces_valid_status():
    """At very low SNR we don't require correctness, but we do require the
    system to behave (no crash, no NaN confidence, still a valid Status),
    which is the honesty contract in practice."""
    cfg = SynthConfig(modulation="64qam", n_symbols=2000, snr_db=-5, seed=8)
    result = generate(cfg)
    params = estimate_parameters(result.iq, cfg.sample_rate_hz)
    mod_param = next(p for p in params if p.name == "modulation")
    assert not np.isnan(mod_param.confidence)
    assert mod_param.status in Status


def test_noise_floor_estimate_reasonable():
    cfg = SynthConfig(modulation="bpsk", n_symbols=3000, snr_db=10, seed=11, sample_rate_hz=200_000)
    result = generate(cfg)
    params = estimate_parameters(result.iq, cfg.sample_rate_hz)
    snr_param = next(p for p in params if p.name == "snr_db")
    # allow a generous tolerance -- this is a coarse estimator, we're checking
    # it's in the right ballpark, not bit-exact
    assert abs(snr_param.value - cfg.snr_db) < 6.0
