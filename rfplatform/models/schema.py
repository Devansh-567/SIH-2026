"""
Core data model for the RF analysis platform.

The central design rule of this project: no numeric result is ever presented
without a Status (how sure are we, and *why*) and an evidence trail. This
module is the literal enforcement point for that rule -- every pipeline stage
returns Parameter objects, not bare floats/strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import time
import uuid


class Status(str, Enum):
    """
    The five-state honesty vocabulary. Every extracted/inferred quantity in
    the system must be tagged with exactly one of these -- see PART 16 / 21
    of the architecture report. Do not add a bare "CONFIRMED" or similar;
    the whole point is that these five states map to five genuinely
    different epistemic situations.
    """

    DETECTED = "DETECTED"        # read directly from trusted metadata (e.g. SigMF sample_rate)
    ESTIMATED = "ESTIMATED"      # computed via a well-defined DSP algorithm (e.g. Welch PSD bandwidth)
    INFERRED = "INFERRED"        # produced by classification / pattern matching with a confidence score
    HYPOTHESIZED = "HYPOTHESIZED"  # one candidate among several plausible explanations, unconfirmed
    UNKNOWN = "UNKNOWN"          # confidence below usable threshold, or algorithm not applicable


@dataclass
class Evidence:
    """A single piece of evidence supporting (or contradicting) a Parameter."""

    source: str          # e.g. "dsp:spectral_flatness", "ml:cnn_classifier_v0", "fec:rs_syndrome"
    description: str      # human-readable explanation, shown in the GUI evidence panel
    weight: float = 1.0   # relative contribution to the final confidence (for fusion transparency)
    value: Optional[Any] = None  # raw supporting value if useful (e.g. the measured kurtosis)


@dataclass
class Parameter:
    """
    One extracted/inferred signal parameter, always carrying its status,
    confidence, and evidence trail together. This is the atomic unit that
    flows from DSP/ML modules into the fusion engine and out to the GUI
    and report exporter.
    """

    name: str                     # e.g. "modulation", "sample_rate_hz", "symbol_rate_hz"
    value: Any                    # the best-estimate value (may be None if UNKNOWN)
    status: Status
    confidence: float = 0.0       # 0.0-1.0, meaningless/ignored when status == UNKNOWN
    unit: Optional[str] = None
    alternatives: list[tuple[Any, float]] = field(default_factory=list)  # top-k (value, confidence)
    evidence: list[Evidence] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status.value,
            "confidence": round(self.confidence, 4),
            "unit": self.unit,
            "alternatives": [
                {"value": v, "confidence": round(c, 4)} for v, c in self.alternatives
            ],
            "evidence": [
                {"source": e.source, "description": e.description, "weight": e.weight, "value": e.value}
                for e in self.evidence
            ],
        }


@dataclass
class AnalysisManifest:
    """
    Reproducibility record for one analysis run -- PART 21/26 differentiator.
    Saved alongside every analysis result so another analyst (or the same
    one, later) can see exactly what produced a given conclusion.
    """

    analysis_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    input_file: str = ""
    input_file_hash: str = ""
    pipeline_version: str = "0.1.0-mvp"
    stage_versions: dict = field(default_factory=dict)
    parameters_used: dict = field(default_factory=dict)  # any analyst overrides applied
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "analysis_id": self.analysis_id,
            "created_at": self.created_at,
            "input_file": self.input_file,
            "input_file_hash": self.input_file_hash,
            "pipeline_version": self.pipeline_version,
            "stage_versions": self.stage_versions,
            "parameters_used": self.parameters_used,
            "warnings": self.warnings,
        }
