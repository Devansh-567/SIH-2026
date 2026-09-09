"""
Bitstream correlation / framing analysis -- PART 15 of the architecture
report. Runs on the post-FEC (or post-demod, if no FEC hypothesis is
confirmed) bit sequence to find sync words, periodic framing, and
candidate header/payload regions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Common real-world sync words / preambles, as (name, bit pattern) --
# extensible library, not exhaustive. Bit patterns given MSB-first.
KNOWN_PREAMBLES = {
    "hdlc_flag": [0, 1, 1, 1, 1, 1, 1, 0],                                  # 0x7E
    "ccsds_asm": [int(b) for b in format(0x1ACFFC1D, "032b")],              # CCSDS attached sync marker
    "ax25_flag": [0, 1, 1, 1, 1, 1, 1, 0],
    "barker_13": [1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1],
}


@dataclass
class EntropyProfile:
    window_size: int
    values: np.ndarray            # per-window Shannon entropy, 0-1
    positions: np.ndarray         # bit-index of each window start


@dataclass
class PreambleMatch:
    name: str
    bit_position: int
    hamming_distance: int
    pattern_length: int


@dataclass
class FramingHypothesis:
    frame_length_bits: int
    confidence: float
    method: str


@dataclass
class BitstreamAnalysis:
    length_bits: int
    entropy_profile: EntropyProfile
    preamble_matches: list[PreambleMatch] = field(default_factory=list)
    framing_hypotheses: list[FramingHypothesis] = field(default_factory=list)
    best_byte_alignment: int = 0
    byte_alignment_confidence: float = 0.0
    hex_preview: str = ""
    ascii_preview: str = ""


def compute_entropy_profile(bits: np.ndarray, window_size: int = 64, step: int | None = None) -> EntropyProfile:
    step = step or window_size // 2
    n = len(bits)
    values, positions = [], []
    for start in range(0, max(1, n - window_size + 1), step):
        window = bits[start:start + window_size]
        if len(window) < window_size:
            break
        p1 = np.mean(window)
        p0 = 1 - p1
        h = 0.0
        for p in (p0, p1):
            if p > 0:
                h -= p * np.log2(p)
        values.append(h)  # 0 = constant (all-0 or all-1, i.e. structured), 1 = balanced/random-looking
        positions.append(start)
    return EntropyProfile(window_size=window_size, values=np.array(values), positions=np.array(positions))


def find_preamble_matches(bits: np.ndarray, max_hamming_fraction: float = 0.1,
                           preambles: dict | None = None) -> list[PreambleMatch]:
    """Hamming-distance-tolerant correlation search for known sync words,
    conceptually the same operation as GNU Radio's correlate_access_code
    block (PART 3.4), reimplemented independently."""
    preambles = preambles or KNOWN_PREAMBLES
    matches = []
    for name, pattern in preambles.items():
        pat = np.array(pattern)
        plen = len(pat)
        max_dist = int(plen * max_hamming_fraction)
        for pos in range(len(bits) - plen + 1):
            window = bits[pos:pos + plen]
            dist = int(np.sum(window != pat))
            if dist <= max_dist:
                matches.append(PreambleMatch(name=name, bit_position=pos, hamming_distance=dist,
                                              pattern_length=plen))
    return matches


def estimate_frame_length(bits: np.ndarray, max_lag: int = 512) -> list[FramingHypothesis]:
    """Autocorrelation-based periodic-framing detection: a repeating header/
    sync-word every N bits shows up as an autocorrelation peak at lag N."""
    if len(bits) < 32:
        return []
    b = bits.astype(np.float64) * 2 - 1
    autocorr = np.correlate(b, b, mode="full")
    mid = len(autocorr) // 2
    max_lag = min(max_lag, mid - 1)
    sidelobes = np.abs(autocorr[mid + 1: mid + 1 + max_lag])
    if len(sidelobes) == 0:
        return []
    peak_val = float(np.max(autocorr[mid]))
    order = np.argsort(-sidelobes)[:5]
    hyps = []
    for lag_idx in order:
        lag = int(lag_idx) + 1
        strength = float(sidelobes[lag_idx] / (peak_val + 1e-12))
        if strength > 0.05:
            hyps.append(FramingHypothesis(frame_length_bits=lag, confidence=min(1.0, strength),
                                           method="bitstream_autocorrelation"))
    return hyps


def estimate_byte_alignment(bits: np.ndarray) -> tuple[int, float]:
    """Test all 8 bit-phase offsets; the correct byte alignment tends to
    show lower byte-level entropy variance / more repeated byte values
    when real structure (framing, padding, repeated headers) is present."""
    best_phase, best_score = 0, -1.0
    for phase in range(8):
        shifted = bits[phase:]
        n_bytes = len(shifted) // 8
        if n_bytes < 4:
            continue
        byte_vals = np.packbits(shifted[: n_bytes * 8].reshape(-1, 8), axis=1).flatten()
        _, counts = np.unique(byte_vals, return_counts=True)
        repetition_score = float(np.max(counts) / n_bytes)
        if repetition_score > best_score:
            best_score, best_phase = repetition_score, phase
    return best_phase, best_score


def bits_to_hex(bits: np.ndarray, max_bytes: int = 64) -> str:
    n_bytes = min(len(bits) // 8, max_bytes)
    if n_bytes == 0:
        return ""
    byte_vals = np.packbits(bits[: n_bytes * 8].reshape(-1, 8), axis=1).flatten()
    return byte_vals.tobytes().hex()


def bits_to_ascii(bits: np.ndarray, max_bytes: int = 64) -> str:
    n_bytes = min(len(bits) // 8, max_bytes)
    if n_bytes == 0:
        return ""
    byte_vals = np.packbits(bits[: n_bytes * 8].reshape(-1, 8), axis=1).flatten()
    return "".join(chr(b) if 32 <= b < 127 else "." for b in byte_vals)


def analyze_bitstream(bits: np.ndarray) -> BitstreamAnalysis:
    entropy = compute_entropy_profile(bits)
    preambles = find_preamble_matches(bits)
    framing = estimate_frame_length(bits)
    byte_phase, byte_conf = estimate_byte_alignment(bits)

    return BitstreamAnalysis(
        length_bits=len(bits),
        entropy_profile=entropy,
        preamble_matches=preambles,
        framing_hypotheses=framing,
        best_byte_alignment=byte_phase,
        byte_alignment_confidence=byte_conf,
        hex_preview=bits_to_hex(bits[byte_phase:]),
        ascii_preview=bits_to_ascii(bits[byte_phase:]),
    )
