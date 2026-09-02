"""
Modulation classifier model -- PART 11 of the architecture report.

Architecture: a small 1D CNN over raw IQ samples (2 channels: I and Q),
following the RadioML/CLDNN literature pattern (PART 3.7 of the
architecture report: "CNN feature extractors over IQ directly... work
reasonably well"), kept intentionally small (three conv blocks + global
average pooling) so it trains in a few minutes on CPU in this environment
-- this is a real, working classifier sized for this project's constraints,
not a research-scale model.

Critically, this is NOT the whole story: PART 11 explicitly requires a
calibration step and a genuine reject/unknown class, both implemented in
calibration.py and dataset.py respectively, not just this raw network.
"""

from __future__ import annotations

import torch
import torch.nn as nn

# Keep in sync with dataset.py::LABELS -- the class index <-> modulation
# name mapping used throughout training, calibration, and inference.
LABELS = ["bpsk", "qpsk", "8psk", "16qam", "64qam", "2fsk", "4fsk", "unknown"]
NUM_CLASSES = len(LABELS)
INPUT_LENGTH = 512  # fixed-length IQ window the model consumes, in samples


class ModulationCNN(nn.Module):
    def __init__(self, num_classes: int = NUM_CLASSES, input_length: int = INPUT_LENGTH):
        super().__init__()
        self.input_length = input_length

        def conv_block(in_ch: int, out_ch: int, kernel: int = 7, stride: int = 2) -> nn.Sequential:
            return nn.Sequential(
                nn.Conv1d(in_ch, out_ch, kernel_size=kernel, stride=stride, padding=kernel // 2),
                nn.BatchNorm1d(out_ch),
                nn.ReLU(inplace=True),
            )

        self.features = nn.Sequential(
            conv_block(2, 16),    # 512 -> 256
            conv_block(16, 32),   # 256 -> 128
            conv_block(32, 64),   # 128 -> 64
            conv_block(64, 64),   # 64 -> 32
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.classifier = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(32, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (batch, 2, input_length) real-valued tensor -> (batch, num_classes) logits."""
        features = self.features(x)
        pooled = self.pool(features).squeeze(-1)
        return self.classifier(pooled)


def iq_to_tensor(iq_complex: "torch.Tensor | object", length: int = INPUT_LENGTH) -> torch.Tensor:
    """
    Converts a complex64 numpy array (or anything array-like) into the
    model's expected (2, length) real tensor: channel 0 = I, channel 1 = Q,
    normalized to unit average power (so the model sees consistent scale
    regardless of the recording's absolute amplitude) and center-cropped
    or zero-padded to a fixed length.
    """
    import numpy as np

    iq = np.asarray(iq_complex)
    power = np.mean(np.abs(iq) ** 2) + 1e-12
    iq = iq / np.sqrt(power)

    if len(iq) >= length:
        start = (len(iq) - length) // 2
        iq = iq[start: start + length]
    else:
        pad = length - len(iq)
        iq = np.concatenate([iq, np.zeros(pad, dtype=iq.dtype)])

    arr = np.stack([iq.real, iq.imag], axis=0).astype(np.float32)
    return torch.from_numpy(arr)
