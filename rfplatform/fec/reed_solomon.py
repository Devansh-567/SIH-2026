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


def _codec(preset_name: str) -> tuple[reedsolo.RSCodec, dict]:
    preset = KNOWN_PRESETS[preset_name]
    nsym = preset["n"] - preset["k"]
    return reedsolo.RSCodec(nsym), preset


def encode(payload: bytes, preset_name: str = "rs_255_223") -> bytes:
    codec, _ = _codec(preset_name)
    return bytes(codec.encode(payload))


def decode(block: bytes, preset_name: str = "rs_255_223") -> RSResult:
    codec, preset = _codec(preset_name)
    try:
        decoded, decoded_full, errata_pos = codec.decode(block)
        return RSResult(
            preset_name=preset_name,
            success=True,
            symbols_corrected=len(errata_pos),
            decoded_bytes=bytes(decoded),
        )
    except reedsolo.ReedSolomonError:
        return RSResult(preset_name=preset_name, success=False, symbols_corrected=-1, decoded_bytes=None)


def hypothesis_search(block: bytes, presets: list[str] | None = None) -> list[RSResult]:
    """Try each known RS preset; successful, low-correction decodes rank first."""
    presets = presets or list(KNOWN_PRESETS.keys())
    results = [decode(block, p) for p in presets]
    results.sort(key=lambda r: (not r.success, r.symbols_corrected if r.symbols_corrected >= 0 else 999))
    return results
