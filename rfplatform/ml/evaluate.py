"""
Accuracy-vs-SNR evaluation -- PART 18 of the architecture report:
"the standard accuracy-vs-SNR curve... reproducing this is the standard
benchmark shape" from the RadioML/modulation-classification literature.
Run after training so the checkpoint's reported performance is honest
about where it works and where it doesn't, rather than a single aggregate
accuracy number that hides the SNR-dependence every real classifier has.
"""

from __future__ import annotations

import numpy as np
import torch

from rfplatform.ml.model import LABELS, ModulationCNN, iq_to_tensor
from rfplatform.synth.generator import SUPPORTED_MODULATIONS, SynthConfig, generate

SNR_BUCKETS_DB = [-5, 0, 5, 10, 15, 20, 25]


def accuracy_by_snr(model: ModulationCNN, temperature: float, n_per_bucket: int = 60,
                     seed: int = 12345) -> dict[float, float]:
    """
    For each SNR bucket, generates n_per_bucket examples uniformly across
    the 7 signal modulations (no 'unknown' examples here -- this
    specifically measures modulation-family/order accuracy as a function
    of SNR, matching the standard literature methodology, not reject-class
    behavior, which is evaluated separately).
    """
    rng = np.random.default_rng(seed)
    model.eval()
    results = {}
    for snr_db in SNR_BUCKETS_DB:
        correct = 0
        for _ in range(n_per_bucket):
            mod = rng.choice(SUPPORTED_MODULATIONS)
            sps = int(rng.choice([4, 8]))
            n_symbols = max(64, (512 + 64) // sps + 8)
            cfg = SynthConfig(modulation=str(mod), n_symbols=n_symbols, sample_rate_hz=200_000.0,
                               seed=int(rng.integers(0, 2**31 - 1)), snr_db=float(snr_db),
                               freq_offset_hz=float(rng.uniform(-2000, 2000)),
                               samples_per_symbol=sps, fsk_deviation_hz=float(rng.uniform(3000, 10000)))
            result = generate(cfg)
            x = iq_to_tensor(result.iq).unsqueeze(0)
            with torch.no_grad():
                logits = model(x) / temperature
                pred_idx = int(logits.argmax(dim=-1).item())
            if LABELS[pred_idx] == mod:
                correct += 1
        results[snr_db] = correct / n_per_bucket
    return results


def unknown_rejection_rate(model: ModulationCNN, temperature: float, n_samples: int = 200,
                            seed: int = 54321) -> float:
    """Fraction of pure-noise (no signal) inputs correctly classified as 'unknown'."""
    rng = np.random.default_rng(seed)
    model.eval()
    correct = 0
    for _ in range(n_samples):
        n = 576
        noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
        x = iq_to_tensor(noise).unsqueeze(0)
        with torch.no_grad():
            logits = model(x) / temperature
            pred_idx = int(logits.argmax(dim=-1).item())
        if LABELS[pred_idx] == "unknown":
            correct += 1
    return correct / n_samples


if __name__ == "__main__":
    from rfplatform.ml.inference import load_checkpoint

    model, temperature, meta = load_checkpoint()
    print("Accuracy vs SNR:")
    for snr, acc in accuracy_by_snr(model, temperature).items():
        print(f"  {snr:+3d} dB: {acc * 100:5.1f}%")
    print(f"Unknown/noise rejection rate: {unknown_rejection_rate(model, temperature) * 100:.1f}%")
