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
