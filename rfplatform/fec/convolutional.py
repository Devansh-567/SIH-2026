"""
Convolutional coding + Viterbi decoding.

We deliberately do NOT hand-roll a trellis/Viterbi implementation -- that's
exactly the kind of validated, mature DSP primitive the architecture report
(PART 5/9) says to source from a permissively-licensed library rather than
reimplement. scikit-commpy (BSD-3) provides a correct, tested Trellis +
viterbi_decode; this module wraps it with the specific short-constraint-length
code presets actually used in the field, per PART 14 of the architecture
report, plus a hypothesis-search helper for blind FEC identification.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from commpy.channelcoding import Trellis, conv_encode, viterbi_decode

# Common real-world short-constraint-length convolutional code presets.
# (constraint_length, rate_k/n, generator polynomials in octal)
# These are the standard presets referenced across satellite/telemetry/
# digital-radio literature -- NOT an unbounded search space, per PART 14.
#
# NOTE: scikit-commpy's Trellis builder uses an int8 internal state-index
# array (commpy/channelcoding/convcode.py), which overflows for constraint
# lengths >= 8 (256 states) under current NumPy's strict integer-overflow
# checking -- confirmed empirically, not a bug in our code. We therefore
# restrict presets to constraint_length <= 7, which is also literally what
# the PS asks for ("short-constrained convolutional codes") and covers the
# single most common real-world code (K=7, rate 1/2, the CCSDS/NASA
# standard). A K=9 preset can be reinstated if/when upstream commpy fixes
# this, or if we swap in a different Viterbi implementation.
KNOWN_PRESETS = {
    "k7_r1/2_ccsds": {  # the classic CCSDS/NASA standard code, extremely common
        "constraint_length": 7,
        "rate": (1, 2),
        "generators_octal": [0o171, 0o133],
    },
    "k5_r1/2": {
        "constraint_length": 5,
        "rate": (1, 2),
        "generators_octal": [0o23, 0o35],
    },
    "k7_r1/3": {
        "constraint_length": 7,
        "rate": (1, 3),
        "generators_octal": [0o171, 0o133, 0o165],
    },
}


def _build_trellis(preset: dict) -> Trellis:
    k = preset["constraint_length"]
    n = preset["rate"][1]
    memory = np.array([k - 1])
    g_matrix = np.array([preset["generators_octal"]], dtype=int)  # shape (1, n)
    return Trellis(memory, g_matrix)


@dataclass
class ConvCodeResult:
    preset_name: str
    decoded_bits: np.ndarray
    reencode_hamming_distance: int  # self-check score: re-encode decoded bits, compare to input
    reencode_distance_fraction: float
    code_rate: tuple


def encode(bits: np.ndarray, preset_name: str = "k7_r1/2_ccsds") -> np.ndarray:
    preset = KNOWN_PRESETS[preset_name]
    trellis = _build_trellis(preset)
    return conv_encode(bits.astype(np.int64), trellis)


def decode(coded_bits: np.ndarray, preset_name: str = "k7_r1/2_ccsds", tb_depth: int = 15) -> ConvCodeResult:
    """
    Hard-decision Viterbi decode using the named preset, plus a self-check:
    re-encode the decoded bits and measure Hamming distance back to the
    input -- low distance is strong positive evidence this preset is the
    correct hypothesis (see architecture report PART 14 scoring approach).
    """
    preset = KNOWN_PRESETS[preset_name]
    trellis = _build_trellis(preset)
    decoded = viterbi_decode(coded_bits.astype(np.int64).astype(float), trellis, tb_depth=tb_depth, decoding_type="hard")

    # commpy pads the decode; trim to the expected message length for a rate-1/n code
    n = preset["rate"][1]
    expected_len = len(coded_bits) // n
    decoded = decoded[:expected_len]

    re_encoded = conv_encode(decoded, trellis)
    compare_len = min(len(re_encoded), len(coded_bits))
    distance = int(np.sum(re_encoded[:compare_len] != coded_bits[:compare_len]))
    fraction = distance / compare_len if compare_len else 1.0

    return ConvCodeResult(
        preset_name=preset_name,
        decoded_bits=decoded,
        reencode_hamming_distance=distance,
        reencode_distance_fraction=fraction,
        code_rate=preset["rate"],
    )


def hypothesis_search(coded_bits: np.ndarray, presets: list[str] | None = None) -> list[ConvCodeResult]:
    """
    Try every known preset, return results ranked by re-encode agreement
    (ascending distance fraction = better hypothesis). This is the FEC
    hypothesis-generation mechanism described in PART 14.
    """
    presets = presets or list(KNOWN_PRESETS.keys())
    results = []
    for name in presets:
        try:
            results.append(decode(coded_bits, preset_name=name))
        except Exception:
            continue
    results.sort(key=lambda r: r.reencode_distance_fraction)
    return results
