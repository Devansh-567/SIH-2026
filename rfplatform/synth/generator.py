"""
Synthetic signal generator -- PART 17 of the architecture report.

This is Phase-0 foundation infrastructure: it is simultaneously our
training-data source, our unit-test fixture generator (every DSP/FEC/
interleaving module is validated against known-answer synthetic signals),
and our demo material. Every generated signal carries full ground-truth
metadata for every injected parameter, because real-world labeled ground
truth for FEC/interleaving essentially does not exist outside vendor specs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from commpy.modulation import PSKModem, QAMModem

SUPPORTED_MODULATIONS = ["bpsk", "qpsk", "8psk", "16qam", "64qam", "2fsk", "4fsk"]


@dataclass
class SynthConfig:
    modulation: str = "bpsk"
    n_symbols: int = 4000
    sample_rate_hz: float = 200_000.0
    samples_per_symbol: int = 8
    snr_db: float = 15.0
    freq_offset_hz: float = 0.0
    phase_offset_rad: float = 0.0
    timing_offset_frac: float = 0.0     # fraction of a symbol period, 0-1
    fsk_deviation_hz: float = 5_000.0
    rrc_rolloff: Optional[float] = 0.35  # None = rectangular pulse shaping
    seed: Optional[int] = None


@dataclass
class SynthResult:
    iq: np.ndarray                # complex64 samples
    bits: np.ndarray              # ground-truth source bits (pre-modulation)
    config: SynthConfig
    ground_truth: dict = field(default_factory=dict)


def _rrc_filter(beta: float, span_symbols: int, sps: int) -> np.ndarray:
    n = span_symbols * sps
    t = (np.arange(-n, n + 1)) / sps
    h = np.zeros_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-8:
            h[i] = 1.0 - beta + 4 * beta / np.pi
        elif beta != 0 and abs(abs(4 * beta * ti) - 1.0) < 1e-8:
            h[i] = (beta / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta))
            )
        else:
            num = np.sin(np.pi * ti * (1 - beta)) + 4 * beta * ti * np.cos(np.pi * ti * (1 + beta))
            den = np.pi * ti * (1 - (4 * beta * ti) ** 2)
            h[i] = num / den
    return h / np.sqrt(np.sum(h ** 2))


def _bits_to_symbols(bits: np.ndarray, modulation: str) -> np.ndarray:
    if modulation == "bpsk":
        modem = PSKModem(2)
        return modem.modulate(bits)
    if modulation == "qpsk":
        modem = PSKModem(4)
        return modem.modulate(bits)
    if modulation == "8psk":
        modem = PSKModem(8)
        return modem.modulate(bits)
    if modulation == "16qam":
        modem = QAMModem(16)
        return modem.modulate(bits)
    if modulation == "64qam":
        modem = QAMModem(64)
        return modem.modulate(bits)
    raise ValueError(f"_bits_to_symbols does not handle {modulation} (FSK uses a separate path)")


def _generate_fsk(bits: np.ndarray, cfg: SynthConfig) -> np.ndarray:
    """Continuous-phase FSK: 2FSK uses 1 bit/symbol, 4FSK uses 2 bits/symbol."""
    bits_per_symbol = 1 if cfg.modulation == "2fsk" else 2
    n_sym = len(bits) // bits_per_symbol
    bits = bits[: n_sym * bits_per_symbol]
    symbols = bits.reshape(-1, bits_per_symbol)
    levels = {1: [-1, 1], 2: [-3, -1, 1, 3]}[bits_per_symbol]

    sym_values = []
    for row in symbols:
        idx = int("".join(str(b) for b in row), 2) if bits_per_symbol == 2 else row[0]
        sym_values.append(levels[idx])
    sym_values = np.array(sym_values, dtype=np.float64)

    sps = cfg.samples_per_symbol
    freq_per_sample = (sym_values[:, None] * cfg.fsk_deviation_hz / max(levels)) / cfg.sample_rate_hz
    freq_per_sample = np.repeat(freq_per_sample, sps, axis=1).reshape(-1)
    phase = 2 * np.pi * np.cumsum(freq_per_sample)
    iq = np.exp(1j * phase).astype(np.complex64)
    return iq


def generate(cfg: SynthConfig) -> SynthResult:
    if cfg.modulation not in SUPPORTED_MODULATIONS:
        raise ValueError(f"unsupported modulation: {cfg.modulation}")
    rng = np.random.default_rng(cfg.seed)

    bits_per_symbol_map = {"bpsk": 1, "qpsk": 2, "8psk": 3, "16qam": 4, "64qam": 6, "2fsk": 1, "4fsk": 2}
    bps = bits_per_symbol_map[cfg.modulation]
    n_bits = cfg.n_symbols * bps
    bits = rng.integers(0, 2, size=n_bits).astype(np.int64)

    if cfg.modulation in ("2fsk", "4fsk"):
        iq = _generate_fsk(bits, cfg)
    else:
        symbols = _bits_to_symbols(bits, cfg.modulation)
        sps = cfg.samples_per_symbol
        upsampled = np.zeros(len(symbols) * sps, dtype=np.complex64)
        upsampled[::sps] = symbols
        if cfg.rrc_rolloff is not None:
            taps = _rrc_filter(cfg.rrc_rolloff, span_symbols=8, sps=sps)
            iq = np.convolve(upsampled, taps, mode="same").astype(np.complex64)
        else:
            # rectangular pulse shaping: hold each symbol for `sps` samples
            iq = np.repeat(symbols, sps).astype(np.complex64)

    # timing offset: fractional-sample delay via simple interpolation
    if cfg.timing_offset_frac:
        shift = int(round(cfg.timing_offset_frac * cfg.samples_per_symbol))
        if shift > 0:
            iq = np.concatenate([np.zeros(shift, dtype=np.complex64), iq[:-shift]])

    # carrier frequency + phase offset
    n = len(iq)
    t = np.arange(n) / cfg.sample_rate_hz
    iq = iq * np.exp(1j * (2 * np.pi * cfg.freq_offset_hz * t + cfg.phase_offset_rad))

    # AWGN at the specified SNR (signal power measured empirically)
    sig_power = np.mean(np.abs(iq) ** 2)
    snr_linear = 10 ** (cfg.snr_db / 10)
    noise_power = sig_power / snr_linear
    noise = np.sqrt(noise_power / 2) * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    iq_noisy = (iq + noise).astype(np.complex64)

    ground_truth = {
        "modulation": cfg.modulation,
        "sample_rate_hz": cfg.sample_rate_hz,
        "samples_per_symbol": cfg.samples_per_symbol,
        "symbol_rate_hz": cfg.sample_rate_hz / cfg.samples_per_symbol,
        "snr_db_injected": cfg.snr_db,
        "freq_offset_hz": cfg.freq_offset_hz,
        "phase_offset_rad": cfg.phase_offset_rad,
        "timing_offset_frac": cfg.timing_offset_frac,
        "n_symbols": cfg.n_symbols,
        "pulse_shaping": "rrc" if cfg.rrc_rolloff is not None else "rectangular",
        "rrc_rolloff": cfg.rrc_rolloff,
    }

    return SynthResult(iq=iq_noisy, bits=bits, config=cfg, ground_truth=ground_truth)


def save_cf32(result: SynthResult, path: str) -> None:
    result.iq.astype(np.complex64).tofile(path)


def save_sigmf(result: SynthResult, data_path: str, center_freq_hz: float = 0.0) -> None:
    """Write a minimal valid SigMF pair (.sigmf-data + .sigmf-meta) with ground truth in a custom namespace."""
    import json
    from pathlib import Path

    data_path = Path(data_path)
    result.iq.astype(np.complex64).tofile(data_path)

    meta = {
        "global": {
            "core:datatype": "cf32_le",
            "core:sample_rate": result.config.sample_rate_hz,
            "core:version": "1.0.0",
            "rfplatform:synthetic": True,
            "rfplatform:ground_truth": result.ground_truth,
        },
        "captures": [{"core:sample_start": 0, "core:frequency": center_freq_hz}],
        "annotations": [],
    }
    meta_path = data_path.with_suffix(".sigmf-meta")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
