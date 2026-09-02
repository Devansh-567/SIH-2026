"""
Reed-Solomon block coding, wrapping `reedsolo` (MIT license).

RS is the most reliably *self-verifying* FEC family we support (per PART 14
of the architecture report): the decoder itself tells you how many symbol
errors it corrected, or that it failed outright. That success/failure and
error count is exactly the evidence the confidence-fusion engine needs, so
this wrapper surfaces it explicitly rather than just returning bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import reedsolo

# Standard real-world RS parameter families (n, k) in bytes -- bounded
# hypothesis set, not an unbounded search, per PART 14.
KNOWN_PRESETS = {
    "rs_255_223": {"n": 255, "k": 223},   # CCSDS / classic deep-space standard
    "rs_255_239": {"n": 255, "k": 239},
    "rs_31_15": {"n": 31, "k": 15},        # small-block variant, useful for short frames
}


@dataclass
class RSResult:
    preset_name: str
    success: bool
    symbols_corrected: int
    decoded_bytes: bytes | None
    byte_alignment: int = 0
    parity_bytes: int = 0


def _codec(preset_name: str) -> tuple[reedsolo.RSCodec, dict]:
    preset = KNOWN_PRESETS[preset_name]
    nsym = preset["n"] - preset["k"]
    return reedsolo.RSCodec(nsym), preset


def encode(payload: bytes, preset_name: str = "rs_255_223") -> bytes:
    codec, _ = _codec(preset_name)
    return bytes(codec.encode(payload))


def decode(block: bytes, preset_name: str = "rs_255_223") -> RSResult:
    codec, preset = _codec(preset_name)
    nsym = preset["n"] - preset["k"]
    try:
        decoded, decoded_full, errata_pos = codec.decode(block)
        return RSResult(
            preset_name=preset_name,
            success=True,
            symbols_corrected=len(errata_pos),
            decoded_bytes=bytes(decoded),
            parity_bytes=nsym,
        )
    except reedsolo.ReedSolomonError:
        return RSResult(preset_name=preset_name, success=False, symbols_corrected=-1, decoded_bytes=None,
                         parity_bytes=nsym)


def hypothesis_search(block: bytes, presets: list[str] | None = None) -> list[RSResult]:
    """
    Try each known RS preset; successful, low-correction decodes rank
    first. Tie-broken by parity byte count (descending): a decode that
    validates successfully against a code with MORE parity bytes is
    stronger evidence than one with fewer, because a smaller-nsym RS
    decoder's syndrome check is weaker and can validate (falsely) against
    data actually encoded with a different, larger-nsym code -- confirmed
    directly during testing: decoding an rs_255_223-encoded block with the
    rs_255_239 preset reported success (0 symbols corrected) but produced
    the WRONG payload. `success=True` alone is therefore necessary but not
    sufficient evidence; this tie-break is a partial mitigation, and the
    fusion/GUI layer still shows every hypothesis rather than silently
    trusting the first one.
    """
    presets = presets or list(KNOWN_PRESETS.keys())
    results = [decode(block, p) for p in presets]
    results.sort(key=lambda r: (not r.success, r.symbols_corrected if r.symbols_corrected >= 0 else 999,
                                 -r.parity_bytes))
    return results


def bits_to_bytes(bits: np.ndarray, bit_offset: int = 0) -> bytes:
    """Packs a 0/1 bit array (MSB-first per byte) into bytes, starting at
    the given bit offset -- shared by hypothesis_search_from_bits and by
    the pipeline/bitstream layer, which already computes byte-alignment
    candidates the same way (see pipeline/bitstream.py::estimate_byte_alignment)."""
    shifted = bits[bit_offset:]
    n_bytes = len(shifted) // 8
    if n_bytes == 0:
        return b""
    return np.packbits(shifted[: n_bytes * 8].reshape(-1, 8), axis=1).flatten().tobytes()


def hypothesis_search_from_bits(bits: np.ndarray, presets: list[str] | None = None,
                                 max_byte_offset: int = 8) -> list[RSResult]:
    """
    Blind RS hypothesis search directly from a demodulated bit array: since
    the correct byte alignment isn't known a priori for an arbitrary
    demodulated stream (RS operates on bytes, not bits), this tries every
    bit-phase offset (0-7) for every known preset and ranks all candidates
    together -- a *successful* decode at a given (preset, offset) pair is
    strong, self-verifying evidence for both the code and the alignment
    simultaneously (RS decode failure/success is close to binary: garbage
    alignment essentially never happens to produce a valid-looking
    codeword), which is exactly the kind of joint evidence PART 14 of the
    architecture report calls for.

    Note: `reedsolo.RSCodec` appends `n-k` parity bytes to whatever payload
    length it's given rather than enforcing a fixed total codeword length
    `n` -- so this decodes whatever block of bytes results from a given
    bit offset directly (matching how `decode()`/`hypothesis_search()`
    already work elsewhere in this module), rather than slicing to a fixed
    255-byte assumption, which was a real bug caught here during testing
    (RSCodec.encode(200-byte payload, nsym=32) produces a 232-byte
    codeword, not 255).
    """
    presets = presets or list(KNOWN_PRESETS.keys())
    results: list[RSResult] = []
    for offset in range(max_byte_offset):
        block = bits_to_bytes(bits, bit_offset=offset)
        for preset in presets:
            nsym = KNOWN_PRESETS[preset]["n"] - KNOWN_PRESETS[preset]["k"]
            if len(block) <= nsym:
                continue  # not enough bytes recovered to contain even the parity alone
            r = decode(block, preset)
            r.byte_alignment = offset
            results.append(r)
    results.sort(key=lambda r: (not r.success, r.symbols_corrected if r.symbols_corrected >= 0 else 999,
                                 -r.parity_bytes))
    return results
