import pytest

from rfplatform.dsp.fingerprint import compute_fingerprint, fingerprint_distance, most_similar
from rfplatform.dsp.classifier import estimate_parameters
from rfplatform.synth.generator import SynthConfig, generate


def _fingerprint_for(modulation: str, snr_db: float, seed: int, sample_rate_hz: float = 200_000.0):
    cfg = SynthConfig(modulation=modulation, n_symbols=3000, snr_db=snr_db, seed=seed,
                       sample_rate_hz=sample_rate_hz, samples_per_symbol=8)
    result = generate(cfg)
    params = estimate_parameters(result.iq, cfg.sample_rate_hz)
    return compute_fingerprint(params)


def test_fingerprint_is_fixed_length_and_deterministic():
    fp1 = _fingerprint_for("qpsk", 20, seed=1)
    fp2 = _fingerprint_for("qpsk", 20, seed=1)
    assert len(fp1.vector) == len(fp2.vector)
    assert len(fp1.vector) == len(fp1.feature_names)
    assert fp1.vector == fp2.vector


def test_fingerprint_same_modulation_closer_than_different_modulation():
    fp_qpsk_a = _fingerprint_for("qpsk", 20, seed=1)
    fp_qpsk_b = _fingerprint_for("qpsk", 22, seed=2)
    fp_64qam = _fingerprint_for("64qam", 20, seed=3)

    d_same = fingerprint_distance(fp_qpsk_a.vector, fp_qpsk_b.vector)
    d_diff = fingerprint_distance(fp_qpsk_a.vector, fp_64qam.vector)
    assert d_same < d_diff


def test_fingerprint_mismatched_length_raises():
    with pytest.raises(ValueError):
        fingerprint_distance([1.0, 2.0], [1.0, 2.0, 3.0])


def test_most_similar_ranks_correctly():
    query = _fingerprint_for("bpsk", 20, seed=10)
    same = _fingerprint_for("bpsk", 18, seed=11)
    other = _fingerprint_for("4fsk", 20, seed=12)

    ranked = most_similar(query.vector, [("other", other.vector), ("same", same.vector)], top_k=2)
    assert ranked[0][0] == "same"
    assert ranked[0][1] < ranked[1][1]


def test_fingerprint_handles_unknown_modulation_gracefully():
    fp = _fingerprint_for("64qam", -8, seed=99)  # very low SNR, likely UNKNOWN
    assert len(fp.vector) > 0
    assert all(isinstance(v, float) for v in fp.vector)
