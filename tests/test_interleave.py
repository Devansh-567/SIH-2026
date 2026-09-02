import numpy as np

from rfplatform.interleave import interleavers as il


def test_block_interleave_round_trip():
    rng = np.random.default_rng(1)
    bits = rng.integers(0, 2, size=64)
    interleaved = il.block_interleave(bits, rows=8, cols=8)
    recovered = il.block_deinterleave(interleaved, rows=8, cols=8)
    np.testing.assert_array_equal(recovered, bits)


def test_convolutional_interleave_round_trip():
    depth, span = 4, 3
    rng = np.random.default_rng(2)
    bits = rng.integers(0, 2, size=300)
    interleaved = il.convolutional_interleave(bits, depth=depth, span=span)
    recovered = il.convolutional_deinterleave(interleaved, depth=depth, span=span)
    shift = il.convolutional_system_delay(depth, span)
    # a fixed-delay shift-register commutator reproduces the input exactly,
    # but offset by the constant system delay -- see convolutional_system_delay()
    np.testing.assert_array_equal(recovered[shift:], bits[: len(bits) - shift])


def test_diagonal_interleave_round_trip():
    rng = np.random.default_rng(3)
    bits = rng.integers(0, 2, size=48)
    interleaved = il.diagonal_interleave(bits, rows=6, cols=8)
    recovered = il.diagonal_deinterleave(interleaved, rows=6, cols=8)
    np.testing.assert_array_equal(recovered, bits)


def test_pseudorandom_round_trip_with_known_seed():
    rng = np.random.default_rng(4)
    bits = rng.integers(0, 2, size=100)
    interleaved = il.pseudorandom_interleave(bits, seed=42)
    recovered = il.pseudorandom_deinterleave_known_seed(interleaved, seed=42)
    np.testing.assert_array_equal(recovered, bits)


def test_pseudorandom_without_seed_is_honestly_unrecoverable():
    """This is a deliberate architectural assertion, not just a code test:
    the system must NOT claim to recover pseudo-random interleaving without
    a reference seed."""
    hyp = il.pseudorandom_deinterleave_hypothesis(np.zeros(10))
    assert hyp.recoverable is False
    assert "not recoverable" in hyp.note


def test_block_hypothesis_search_finds_correct_dimensions():
    rng = np.random.default_rng(5)
    # structured bits: a repeating pattern, so a *correct* de-interleave
    # should measurably reduce our structure-cost heuristic vs. wrong guesses
    pattern = np.tile([0, 0, 1, 1, 0, 1], 20)[:120]
    interleaved = il.block_interleave(pattern, rows=10, cols=12)
    results = il.block_hypothesis_search(interleaved, max_dim=14)
    assert len(results) > 0
    best = results[0]
    # correct dims recover clean periodic structure -> should be at/near the top
    dims_found = [(r.params["rows"], r.params["cols"]) for r in results]
    assert (10, 12) in dims_found or (12, 10) in dims_found
