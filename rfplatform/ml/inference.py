"""
Inference -- loads the trained checkpoint once and classifies IQ windows,
producing output in the same Parameter/Evidence/Status shape every other
part of the pipeline uses (see rfplatform/models/schema.py), so the
fusion engine (rfplatform/pipeline/fusion.py) can combine it with the DSP
classifier's output without any special-casing.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

from rfplatform.ml.model import LABELS, ModulationCNN, iq_to_tensor
from rfplatform.models.schema import Evidence, Parameter, Status

CHECKPOINT_PATH = Path(__file__).parent / "checkpoints" / "modulation_classifier.pt"

# Below this calibrated confidence, report UNKNOWN rather than a guess --
# distinct from (and in addition to) the model's own learned 'unknown'
# class, this is a second, independent safety net (PART 11: "confidence
# scores... unknown/reject class" are both required, not either/or).
CONFIDENCE_FLOOR = 0.3


class ModelUnavailableError(Exception):
    """Raised when no trained checkpoint exists -- callers (the pipeline)
    must handle this gracefully by falling back to DSP-only classification,
    not crash the analysis."""


@lru_cache(maxsize=1)
def load_checkpoint(path: Path | None = None) -> tuple[ModulationCNN, float, dict]:
    """Loads the model once per process (cached) -- checkpoint loading and
    weight deserialization are not free, and this function may be called
    once per analysis."""
    checkpoint_path = path or CHECKPOINT_PATH
    if not checkpoint_path.exists():
        raise ModelUnavailableError(
            f"No trained model checkpoint at {checkpoint_path}. Run "
            f"`python -m rfplatform.ml.train` to train one."
        )
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    model = ModulationCNN()
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    metadata = checkpoint["metadata"]
    return model, metadata["temperature"], metadata


def classify(iq: np.ndarray) -> Parameter:
    """
    Classifies a window of IQ samples. Always returns a Parameter with
    top-k alternatives and calibrated confidence -- never a bare label.
    Raises ModelUnavailableError if no checkpoint exists (caller decides
    the fallback behavior; see pipeline/stages.py::_run_ml_classifier).
    """
    model, temperature, metadata = load_checkpoint()

    x = iq_to_tensor(iq).unsqueeze(0)
    with torch.no_grad():
        logits = model(x)
        probs = torch.softmax(logits / temperature, dim=-1).squeeze(0)

    order = torch.argsort(probs, descending=True)
    top_label = LABELS[int(order[0])]
    top_conf = float(probs[order[0]])
    alternatives = [(LABELS[int(i)], float(probs[i])) for i in order[1:4]]

    evidence = [Evidence(
        source="ml:cnn_classifier_v1",
        description=f"CNN classifier (temperature-calibrated, val_acc={metadata.get('final_val_acc', 0):.2f} "
                    f"at training time) -- top prediction '{top_label}' at {top_conf:.2f} confidence.",
        value=top_conf,
    )]

    if top_label == "unknown" or top_conf < CONFIDENCE_FLOOR:
        return Parameter(
            name="modulation", value=None, status=Status.UNKNOWN, confidence=top_conf,
            alternatives=alternatives, evidence=evidence,
        )

    return Parameter(
        name="modulation", value=top_label, status=Status.INFERRED, confidence=top_conf,
        alternatives=alternatives, evidence=evidence,
    )
