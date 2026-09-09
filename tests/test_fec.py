import numpy as np

from rfplatform.fec import convolutional as convfec
from rfplatform.fec import reed_solomon as rsfec


def test_convolutional_round_trip_clean():
    rng = np.random.default_rng(1)
    bits = rng.integers(0, 2, size=200)
    coded = convfec.encode(bits, "k7_r1/2_ccsds")
    result = convfec.decode(coded, "k7_r1/2_ccsds")
    # commpy's conv_encode appends trellis-termination tail bits, so the
    # decoded sequence is slightly longer than the message; compare only
    # the message-length prefix.
    np.testing.assert_array_equal(result.decoded_bits[: len(bits)], bits)
    assert result.reencode_hamming_distance == 0


def test_convolutional_hypothesis_search_picks_correct_preset():
    rng = np.random.default_rng(2)
    bits = rng.integers(0, 2, size=200)
    coded = convfec.encode(bits, "k5_r1/2")
    results = convfec.hypothesis_search(coded, presets=["k7_r1/2_ccsds", "k5_r1/2"])
    assert results[0].preset_name == "k5_r1/2"
    assert results[0].reencode_distance_fraction < results[1].reencode_distance_fraction


def test_convolutional_survives_bit_errors():
    """Viterbi should correct a modest number of channel bit errors."""
    rng = np.random.default_rng(3)
    bits = rng.integers(0, 2, size=400)
    coded = convfec.encode(bits, "k7_r1/2_ccsds")
    corrupted = coded.copy()
    error_positions = rng.choice(len(corrupted), size=int(0.02 * len(corrupted)), replace=False)
    corrupted[error_positions] ^= 1
    result = convfec.decode(corrupted, "k7_r1/2_ccsds")
    bit_errors = np.sum(result.decoded_bits[: len(bits)] != bits)
    # 2% raw channel BER should be substantially cleaned up by a rate-1/2 K=7 code
    assert bit_errors < len(bits) * 0.02


def test_reed_solomon_round_trip_clean():
    payload = bytes(range(200))  # 200 bytes < k=223 for rs_255_223
    encoded = rsfec.encode(payload, "rs_255_223")
    result = rsfec.decode(encoded, "rs_255_223")
    assert result.success
    assert result.symbols_corrected == 0
    assert result.decoded_bytes == payload


def test_reed_solomon_corrects_symbol_errors():
    payload = bytes(range(200))
    encoded = bytearray(rsfec.encode(payload, "rs_255_223"))
    # corrupt a handful of symbols -- rs_255_223 can correct up to (255-223)/2 = 16 symbol errors
    for pos in (5, 40, 100, 150, 200):
        encoded[pos] ^= 0xFF
    result = rsfec.decode(bytes(encoded), "rs_255_223")
    assert result.success
    assert result.symbols_corrected == 5
    assert result.decoded_bytes == payload


def test_reed_solomon_hypothesis_search_ranks_successful_first():
    payload = bytes(range(200))
    encoded = rsfec.encode(payload, "rs_255_223")
    results = rsfec.hypothesis_search(encoded, presets=["rs_255_223", "rs_255_239"])
    assert results[0].preset_name == "rs_255_223"
    assert results[0].success


def test_reed_solomon_hypothesis_search_prefers_more_parity_on_tie():
    """When two presets both report success (one is a false positive with
    weaker error detection -- see docstring in reed_solomon.py), the
    preset with more parity bytes should rank first."""
    payload = bytes(range(200))
    encoded = rsfec.encode(payload, "rs_255_223")  # 32 parity bytes
    results = rsfec.hypothesis_search(encoded, presets=["rs_255_223", "rs_255_239"])
    top = results[0]
    assert top.preset_name == "rs_255_223"
    assert top.decoded_bytes == payload  # the correct preset also decodes to the correct content


def test_reed_solomon_bit_search_finds_correct_byte_alignment():
    """RS operates on bytes; a demodulated bitstream's byte alignment is
    unknown a priori. hypothesis_search_from_bits must recover both the
    correct preset AND the correct bit-phase offset blindly."""
    payload = bytes(range(200))
    encoded = rsfec.encode(payload, "rs_255_223")
    bits = np.unpackbits(np.frombuffer(encoded, dtype=np.uint8))
    misalignment = np.array([1, 0, 1, 1, 0], dtype=np.uint8)  # simulate 5 unknown leading bits
    shifted = np.concatenate([misalignment, bits])

    results = rsfec.hypothesis_search_from_bits(shifted, presets=["rs_255_223", "rs_255_239"])
    best = results[0]
    assert best.success
    assert best.preset_name == "rs_255_223"
    assert best.decoded_bytes == payload
    assert best.byte_alignment == 5


def test_reed_solomon_bit_search_with_no_valid_alignment_reports_failure():
    rng = np.random.default_rng(1)
    random_bits = rng.integers(0, 2, size=2000).astype(np.uint8)
    results = rsfec.hypothesis_search_from_bits(random_bits, presets=["rs_255_223"])
    # every candidate should honestly fail -- no fabricated success on pure noise
    assert all(not r.success for r in results)
