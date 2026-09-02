import numpy as np

from rfplatform.pipeline.bitstream import (
    KNOWN_PREAMBLES, analyze_bitstream, estimate_byte_alignment,
    estimate_frame_length, find_preamble_matches,
)


def test_preamble_detection_exact_match():
    rng = np.random.default_rng(1)
    payload = rng.integers(0, 2, size=200)
    preamble = np.array(KNOWN_PREAMBLES["hdlc_flag"])
    stream = np.concatenate([rng.integers(0, 2, size=20), preamble, payload])
    matches = find_preamble_matches(stream)
    positions = [m.bit_position for m in matches if m.name == "hdlc_flag"]
    assert 20 in positions


def test_preamble_detection_tolerates_bit_errors():
    rng = np.random.default_rng(2)
    preamble = np.array(KNOWN_PREAMBLES["ccsds_asm"])
    corrupted = preamble.copy()
    corrupted[3] ^= 1  # one bit error out of 32
    stream = np.concatenate([rng.integers(0, 2, size=10), corrupted, rng.integers(0, 2, size=100)])
    matches = find_preamble_matches(stream)
    positions = [m.bit_position for m in matches if m.name == "ccsds_asm"]
    assert 10 in positions


def test_frame_length_detection_on_periodic_header():
    """Inject a repeating 8-bit header every 40 bits and confirm the
    autocorrelation-based estimator recovers a frame-length hypothesis
    near 40."""
    rng = np.random.default_rng(3)
    header = np.array([1, 0, 1, 0, 1, 1, 0, 0])
    frames = []
    for _ in range(30):
        frames.append(header)
        frames.append(rng.integers(0, 2, size=32))
    stream = np.concatenate(frames)
    hyps = estimate_frame_length(stream, max_lag=100)
    lengths = [h.frame_length_bits for h in hyps]
    assert any(abs(l - 40) <= 1 for l in lengths), f"expected ~40-bit frame hypothesis, got {lengths}"


def test_byte_alignment_detection():
    """A stream built from repeated identical bytes should have its true
    byte alignment recovered."""
    rng = np.random.default_rng(4)
    byte_pattern = np.array([1, 0, 1, 0, 1, 0, 1, 0])
    stream_bytes = np.tile(byte_pattern, 40)
    phase_shift = 3
    padding = rng.integers(0, 2, size=phase_shift)
    shifted_stream = np.concatenate([padding, stream_bytes])
    phase, score = estimate_byte_alignment(shifted_stream)
    assert phase == phase_shift
    assert score > 0.5


def test_analyze_bitstream_end_to_end_runs_without_error():
    rng = np.random.default_rng(5)
    bits = rng.integers(0, 2, size=1000)
    result = analyze_bitstream(bits)
    assert result.length_bits == 1000
    assert len(result.hex_preview) > 0
    assert isinstance(result.entropy_profile.values, np.ndarray)


def test_entropy_low_for_constant_bits_high_for_random():
    from rfplatform.pipeline.bitstream import compute_entropy_profile

    constant = np.zeros(256, dtype=int)
    rng = np.random.default_rng(6)
    random_bits = rng.integers(0, 2, size=256)

    e_const = compute_entropy_profile(constant, window_size=64)
    e_rand = compute_entropy_profile(random_bits, window_size=64)

    assert np.mean(e_const.values) < 0.1
    assert np.mean(e_rand.values) > 0.5
