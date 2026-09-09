"""
Signal fingerprinting -- PART 22 differentiator from the architecture
report ("Create a feature fingerprint for each detected signal so similar
signals can be found across recordings").

Design: the fingerprint is built entirely from Parameters this pipeline
already computes (see dsp/classifier.py::estimate_parameters) -- it is not
a separate, redundant feature-extraction pass over raw IQ. This keeps the
fingerprint's provenance traceable (every dimension maps to a named,
already-evidenced Parameter) and means computing one is nearly free once
a signal has been analyzed.

Distance is plain Euclidean over a normalized vector -- deliberately not a
learned embedding. At the scale this project operates at (an analyst's
local recording history, not a million-signal corpus), a transparent,
debuggable distance metric is more valuable than a marginally-better
learned one, and it costs nothing to compute or explain.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rfplatform.models.schema import Parameter
from rfplatform.synth.generator import SUPPORTED_MODULATIONS

FINGERPRINT_VERSION = "1.0"

_NUMERIC_FEATURES = [
    ("occupied_bandwidth_hz", "log10", 7.0),
    ("snr_db", "linear", 40.0),
    ("spectral_entropy", "linear", 1.0),
    ("symbol_rate_hz", "log10", 7.0),
    ("noise_floor_db", "linear", 100.0),
]


def _transform(value: float, kind: str) -> float:
    if kind == "log10":
        return float(np.log10(max(value, 1e-6)))
    return float(value)


@dataclass
class Fingerprint:
    vector: list[float]
    feature_names: list[str]
    version: str = FINGERPRINT_VERSION


def compute_fingerprint(parameters: list[Parameter]) -> Fingerprint:
    """
    Builds a fixed-length vector from a signal's Parameter list:
    - 5 numeric features (bandwidth, SNR, spectral entropy, symbol rate,
      noise floor), each with a trailing "is this value actually known"
      presence bit (an UNKNOWN parameter contributes 0.0, not a fabricated
      number, and the presence bit lets similarity search distinguish
      "genuinely near-zero" from "not measured")
    - a one-hot modulation encoding over the 7 supported modulations, plus
      an 8th "unknown/unclassified" slot
    """
    by_name = {p.name: p for p in parameters}
    values: list[float] = []
    presence: list[float] = []

    for name, kind, scale in _NUMERIC_FEATURES:
        param = by_name.get(name)
        known = param is not None and param.value is not None
        raw = _transform(float(param.value), kind) / scale if known else 0.0
        values.append(float(np.clip(raw, -3.0, 3.0)))
        presence.append(1.0 if known else 0.0)

    mod_param = by_name.get("modulation")
    mod_value = mod_param.value if mod_param else None
    mod_one_hot = [1.0 if mod_value == m else 0.0 for m in SUPPORTED_MODULATIONS]
    mod_one_hot.append(1.0 if mod_value is None else 0.0)  # unknown slot

    vector = values + presence + mod_one_hot
    feature_names = (
        [n for n, _, _ in _NUMERIC_FEATURES]
        + [f"{n}:known" for n, _, _ in _NUMERIC_FEATURES]
        + [f"mod:{m}" for m in SUPPORTED_MODULATIONS] + ["mod:unknown"]
    )

    return Fingerprint(vector=[round(v, 5) for v in vector], feature_names=feature_names)


def fingerprint_distance(a: list[float], b: list[float]) -> float:
    """Plain Euclidean distance. Lower = more similar. Vectors must be the
    same length (i.e. produced by the same FINGERPRINT_VERSION)."""
    if len(a) != len(b):
        raise ValueError(f"fingerprint length mismatch: {len(a)} vs {len(b)} -- "
                          f"likely comparing fingerprints from different FINGERPRINT_VERSIONs")
    va, vb = np.asarray(a), np.asarray(b)
    return float(np.linalg.norm(va - vb))


def most_similar(query: list[float], candidates: list[tuple[str, list[float]]], top_k: int = 5) -> list[tuple[str, float]]:
    """candidates: list of (id, vector). Returns [(id, distance), ...] sorted ascending by distance."""
    scored = [(cid, fingerprint_distance(query, vec)) for cid, vec in candidates]
    scored.sort(key=lambda t: t[1])
    return scored[:top_k]
