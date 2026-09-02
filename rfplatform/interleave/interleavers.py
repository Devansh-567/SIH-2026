"""
Interleaving / de-interleaving -- the four families required by the PS.

Design note (architecture report PART 13): block, convolutional, and
diagonal interleavers have a small, bounded parameter space and are
blind-searchable. Pseudo-random interleaving is architecturally different:
without the seed/sequence it is NOT generally recoverable, and this module
says so explicitly rather than pretending otherwise -- see
`pseudorandom_deinterleave_hypothesis`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------- block ----

def block_interleave(bits: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """Write bits row-wise into a (rows x cols) matrix, read out column-wise."""
    n = rows * cols
    padded = np.zeros(n, dtype=bits.dtype)
    padded[: min(len(bits), n)] = bits[:n]
    matrix = padded.reshape(rows, cols)
    return matrix.T.reshape(-1)


def block_deinterleave(bits: np.ndarray, rows: int, cols: int) -> np.ndarray:
    n = rows * cols
    padded = np.zeros(n, dtype=bits.dtype)
    padded[: min(len(bits), n)] = bits[:n]
    matrix = padded.reshape(cols, rows).T
    return matrix.reshape(-1)


# --------------------------------------------------------- convolutional ---

def _commutator_pass(bits: np.ndarray, depth: int, delays: list[int]) -> np.ndarray:
    """
    Fixed-length shift-register commutator, one input <-> one output per
    cycle. Each branch's FIFO is pre-filled with `delay` zeros so a pop
    always follows a push -- this keeps every branch's queue at a constant
    length throughout (not just in "steady state"), which is what makes the
    interleave/deinterleave pair exactly invertible, including the fill and
    drain transients at the start/end of the stream (not just the middle).
    """
    delay_lines = [[0] * d for d in delays]
    out = np.empty_like(bits)
    for idx, b in enumerate(bits):
        branch = idx % depth
        delay_lines[branch].append(b)
        out[idx] = delay_lines[branch].pop(0)
    return out


def convolutional_interleave(bits: np.ndarray, depth: int, span: int) -> np.ndarray:
    """
    Classic Ramsey/Forney-style convolutional interleaver: branch i delays
    its symbols by i * span positions, using `depth` branches cyclically.
    """
    delays = [b * span for b in range(depth)]
    return _commutator_pass(bits, depth, delays)


def convolutional_deinterleave(bits: np.ndarray, depth: int, span: int) -> np.ndarray:
    """
    Inverse of convolutional_interleave: branch i delays by (depth-1-i)*span.

    Note on system delay: because the commutator revisits each branch once
    every `depth` samples, and the deinterleaver's branch assignment (by
    position in the *interleaved* stream) doesn't line up with the
    interleaver's branch assignment (by position in the *original* stream)
    until the whole depth x delay structure has cycled through, the total
    e2e system delay before interleave+deinterleave reproduces the original
    sequence is depth * (depth - 1) * span samples -- confirmed empirically
    in tests/test_interleave.py, not just the naive (depth-1)*span. This
    value is exposed via `convolutional_system_delay()` for callers (e.g.
    the GUI, which needs it to align/trim recovered streams correctly).
    """
    delays = [(depth - 1 - b) * span for b in range(depth)]
    return _commutator_pass(bits, depth, delays)


def convolutional_system_delay(depth: int, span: int) -> int:
    """Total sample delay before a convolutional interleave+deinterleave pass realigns with the input."""
    return depth * (depth - 1) * span


# -------------------------------------------------------------- diagonal ---

def diagonal_interleave(bits: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """Write row-wise, read along diagonals (wrapping)."""
    n = rows * cols
    padded = np.zeros(n, dtype=bits.dtype)
    padded[: min(len(bits), n)] = bits[:n]
    matrix = padded.reshape(rows, cols)
    out = np.zeros(n, dtype=bits.dtype)
    idx = 0
    for d in range(cols):
        for r in range(rows):
            c = (d + r) % cols
            out[idx] = matrix[r, c]
            idx += 1
    return out


def diagonal_deinterleave(bits: np.ndarray, rows: int, cols: int) -> np.ndarray:
    n = rows * cols
    padded = np.zeros(n, dtype=bits.dtype)
    padded[: min(len(bits), n)] = bits[:n]
    matrix = np.zeros((rows, cols), dtype=bits.dtype)
    idx = 0
    for d in range(cols):
        for r in range(rows):
            c = (d + r) % cols
            matrix[r, c] = padded[idx]
            idx += 1
    return matrix.reshape(-1)


# --------------------------------------------------------- pseudo-random ---

def pseudorandom_interleave(bits: np.ndarray, seed: int) -> np.ndarray:
    """Used only by the synthetic generator (we control the seed there)."""
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(bits))
    out = np.empty_like(bits)
    out[perm] = bits
    return out


def pseudorandom_deinterleave_known_seed(bits: np.ndarray, seed: int) -> np.ndarray:
    """Only possible when the seed/sequence is actually known (e.g. matches a published standard)."""
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(bits))
    return bits[perm]


@dataclass
class DeinterleaveHypothesis:
    family: str
    params: dict
    score: float          # HIGHER is better (structure-detection strength); see _structure_score
    recoverable: bool = True
    note: str = ""


def pseudorandom_deinterleave_hypothesis(bits: np.ndarray) -> DeinterleaveHypothesis:
    """
    Honest handling of the unrecoverable case (PART 13/29). We do not
    fabricate a recovered mapping. If block/convolutional/diagonal search
    all fail to reduce a structure-detection cost, this is the fallback
    conclusion the pipeline should report.
    """
    return DeinterleaveHypothesis(
        family="pseudo_random",
        params={},
        score=0.0,
        recoverable=False,
        note="Pseudo-random interleaving detected/suspected; parameters are not recoverable "
             "without a reference seed or a match against a known published standard sequence.",
    )


# --------------------------------------------------------------- search ----

def _structure_score(bits: np.ndarray) -> float:
    """
    Cheap proxy for 'does this bit sequence look structured (post-deinterleave,
    e.g. periodic framing/preambles) rather than scrambled/pseudo-random'.

    Important direction note (found via testing, not obvious a priori):
    STRUCTURED / PERIODIC data has HIGH autocorrelation sidelobes (that is
    what periodicity means) -- e.g. a repeating frame preamble reappearing
    every N bits shows up as a strong peak at lag N. SCRAMBLED/interleaved
    data looks closer to white noise, with LOW sidelobes everywhere. So a
    *higher* max-sidelobe-to-zero-lag ratio is evidence FOR a hypothesis
    (more likely correct/structured), not against it -- callers should sort
    descending. This is a heuristic, not a proof; FEC-decode success (when
    an FEC hypothesis is available) is a much stronger downstream
    confirmation and should be preferred when available (PART 13). It also
    only helps when the underlying data actually contains periodic
    structure (sync words, repeating headers) -- pure random payload gives
    no signal either way, which is an honest limitation, not a bug.
    """
    if len(bits) < 16:
        return 0.0
    b = bits.astype(np.float64) * 2 - 1  # map {0,1} -> {-1,1}
    autocorr = np.correlate(b, b, mode="full")
    mid = len(autocorr) // 2
    max_lag = min(64, mid)
    sidelobes = np.abs(autocorr[mid + 1: mid + 1 + max_lag])
    peak = abs(autocorr[mid]) + 1e-9
    return float(np.max(sidelobes) / peak) if len(sidelobes) else 0.0


def block_hypothesis_search(bits: np.ndarray, max_dim: int = 16) -> list[DeinterleaveHypothesis]:
    """Blind search over (rows, cols); ranked descending by structure score (higher = better)."""
    results = []
    for rows in range(2, max_dim + 1):
        for cols in range(2, max_dim + 1):
            if rows * cols > len(bits) or rows * cols < len(bits) // 4:
                continue
            try:
                candidate = block_deinterleave(bits, rows, cols)
                score = _structure_score(candidate)
                results.append(DeinterleaveHypothesis("block", {"rows": rows, "cols": cols}, score))
            except Exception:
                continue
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:5]
