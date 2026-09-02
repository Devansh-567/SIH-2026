"""
Training dataset for the modulation classifier -- generated on the fly
from rfplatform.synth.generator, not a static file. This is the same
"synthetic data as ground-truth infrastructure" principle from PART 17 of
the architecture report, applied to ML training specifically: real-world
labeled data for "is this signal FSK or QPSK" is available in places
(RadioML), but we already decided (README) to train primarily on our own
generator rather than depend on DeepSig's CC BY-NC-SA-licensed dataset.

The 'unknown' class is trained on genuinely out-of-distribution examples
(pure noise, no signal) -- PART 11's explicit requirement that the reject
class be learned, not just a post-hoc confidence threshold. A model that
has never seen "no signal" during training has no real basis for
recognizing it at inference time.
"""

from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import Dataset

from rfplatform.ml.model import INPUT_LENGTH, LABELS
from rfplatform.synth.generator import SUPPORTED_MODULATIONS, SynthConfig, generate

assert LABELS[:-1] == SUPPORTED_MODULATIONS, "ml/model.py LABELS must match synth generator modulations + 'unknown'"

SIGNAL_LABELS = SUPPORTED_MODULATIONS  # bpsk, qpsk, 8psk, 16qam, 64qam, 2fsk, 4fsk
UNKNOWN_LABEL_IDX = LABELS.index("unknown")

# Training-time impairment ranges -- deliberately wide so the classifier
# doesn't overfit to one clean operating point (architecture report PART
# 17: "aggressive impairment augmentation... in the generator").
SNR_DB_RANGE = (-2.0, 25.0)
FREQ_OFFSET_HZ_RANGE = (-3000.0, 3000.0)
PHASE_OFFSET_RANGE = (0.0, 2 * np.pi)
SPS_CHOICES = (4, 8)


class ModulationDataset(Dataset):
    """
    Infinite-style on-the-fly dataset: __len__ reports a nominal epoch size,
    __getitem__ generates a fresh random example each call rather than
    indexing a fixed pre-generated array. This trades a small amount of
    per-batch generation cost for effectively unlimited training variety
    with zero disk footprint -- appropriate here since signal generation
    is cheap (a few hundred microseconds) relative to a training step.
    """

    def __init__(self, epoch_size: int = 4000, seed: int | None = None,
                 unknown_fraction: float = 1.0 / len(LABELS)):
        self.epoch_size = epoch_size
        self.unknown_fraction = unknown_fraction
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return self.epoch_size

    def _random_params(self) -> dict:
        return {
            "snr_db": float(self.rng.uniform(*SNR_DB_RANGE)),
            "freq_offset_hz": float(self.rng.uniform(*FREQ_OFFSET_HZ_RANGE)),
            "phase_offset_rad": float(self.rng.uniform(*PHASE_OFFSET_RANGE)),
            "samples_per_symbol": int(self.rng.choice(SPS_CHOICES)),
        }

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        if self.rng.random() < self.unknown_fraction:
            # genuine out-of-distribution example: pure AWGN, no signal at all
            n = INPUT_LENGTH + 64
            noise = (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n)).astype(np.complex64)
            return self._to_tensor(noise), UNKNOWN_LABEL_IDX

        label_name = self.rng.choice(SIGNAL_LABELS)
        label_idx = LABELS.index(label_name)
        params = self._random_params()
        n_symbols = max(64, (INPUT_LENGTH + 64) // params["samples_per_symbol"] + 8)
        cfg = SynthConfig(
            modulation=label_name, n_symbols=n_symbols, sample_rate_hz=200_000.0,
            seed=int(self.rng.integers(0, 2**31 - 1)),
            snr_db=params["snr_db"], freq_offset_hz=params["freq_offset_hz"],
            phase_offset_rad=params["phase_offset_rad"], samples_per_symbol=params["samples_per_symbol"],
            fsk_deviation_hz=self.rng.uniform(3000, 10000),
        )
        result = generate(cfg)
        return self._to_tensor(result.iq), label_idx

    @staticmethod
    def _to_tensor(iq: np.ndarray) -> torch.Tensor:
        from rfplatform.ml.model import iq_to_tensor
        return iq_to_tensor(iq)
