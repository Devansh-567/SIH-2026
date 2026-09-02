"""
Temperature scaling calibration -- PART 11 of the architecture report:
"an explicit temperature-scaling calibration step... so softmax outputs
are trustworthy probabilities, not just relative rankings."

Raw softmax outputs from a trained classifier are well-known to be
overconfident (Guo et al., 2017, "On Calibration of Modern Neural
Networks") -- a network can assign 99% confidence to a wrong answer just
as readily as a right one. Temperature scaling divides the logits by a
single learned scalar T > 1 before the softmax, which does not change the
model's predicted class (argmax is unaffected) but spreads out the
probability distribution so the reported confidence is closer to the
actual empirical accuracy at that confidence level.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F


def fit_temperature(logits: torch.Tensor, labels: torch.Tensor,
                     search_range: tuple[float, float] = (0.3, 6.0), steps: int = 60) -> float:
    """
    Finds the temperature T minimizing negative log-likelihood of
    softmax(logits / T) against the true labels, via a simple 1D grid
    search. A grid search is used instead of the more common LBFGS
    approach specifically because it can't fail to converge or diverge --
    for a single scalar parameter over a bounded, sensible range, the
    robustness is worth more than LBFGS's slightly faster convergence.
    """
    best_t, best_nll = 1.0, float("inf")
    lo, hi = search_range
    for i in range(steps):
        t = lo + (hi - lo) * i / (steps - 1)
        scaled = logits / t
        nll = F.cross_entropy(scaled, labels).item()
        if nll < best_nll:
            best_nll, best_t = nll, t
    return best_t


def calibrated_probs(logits: torch.Tensor, temperature: float) -> torch.Tensor:
    return F.softmax(logits / temperature, dim=-1)


def expected_calibration_error(probs: torch.Tensor, labels: torch.Tensor, n_bins: int = 10) -> float:
    """
    ECE: bins predictions by their top confidence, and for each bin
    measures |average confidence - actual accuracy|, weighted by bin
    population. Lower is better-calibrated. Used in tests/training reports
    to confirm calibration actually helped, not just asserted to.
    """
    confidences, predictions = probs.max(dim=-1)
    accuracies = predictions.eq(labels).float()

    bin_boundaries = torch.linspace(0, 1, n_bins + 1)
    ece = torch.zeros(1)
    for i in range(n_bins):
        lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
        in_bin = (confidences > lo) & (confidences <= hi)
        prop_in_bin = in_bin.float().mean()
        if prop_in_bin.item() > 0:
            acc_in_bin = accuracies[in_bin].mean()
            conf_in_bin = confidences[in_bin].mean()
            ece += torch.abs(conf_in_bin - acc_in_bin) * prop_in_bin
    return float(ece.item())
