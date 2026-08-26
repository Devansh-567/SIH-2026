"""
Deterministic DSP feature extraction -- PART 10 of the architecture report.

Every function here is a well-defined, citable algorithm (Welch PSD,
percentile/MAD noise floor, instantaneous-amplitude/phase/frequency via the
IQ signal's own analytic-signal structure, cyclostationary symbol-rate
estimation). This module produces the *evidence* that both the rule-based
classifier and the ML classifier's fusion step consume -- see PART 11.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import welch


@dataclass
class NoiseEstimate:
    noise_floor_db: float
    method_agreement_db: float  # abs difference between percentile and MAD estimators; large = warn


@dataclass
class SpectralFeatures:
    freqs_hz: np.ndarray
    psd_db: np.ndarray
    peak_freq_hz: float
    occupied_bandwidth_hz: float
    spectral_entropy: float
    spectral_flatness: float


@dataclass
class IQFeatures:
    mean_amplitude: float
    amplitude_std: float
    amplitude_variance_normalized: float  # key constant-envelope discriminator (FSK/PSK vs QAM/ASK)
    phase_std: float
    inst_freq_std_hz: float
    kurtosis_amplitude: float
    kurtosis_phase: float
    papr_db: float  # peak-to-average power ratio


def estimate_noise_floor(iq: np.ndarray, sample_rate_hz: float, nperseg: int = 1024) -> NoiseEstimate:
    freqs, psd = welch(iq, fs=sample_rate_hz, nperseg=min(nperseg, len(iq)), return_onesided=False)
    psd_db = 10 * np.log10(psd + 1e-20)

    # Method 1: low-percentile bin power (robust to a narrowband signal sitting in the noise)
    percentile_floor = float(np.percentile(psd_db, 10))

    # Method 2: median + MAD-based robust estimate
    median = np.median(psd_db)
    mad = np.median(np.abs(psd_db - median))
    mad_floor = float(median - 0.5 * mad)

    agreement = abs(percentile_floor - mad_floor)
    combined = (percentile_floor + mad_floor) / 2.0
    return NoiseEstimate(noise_floor_db=combined, method_agreement_db=agreement)


def extract_spectral_features(iq: np.ndarray, sample_rate_hz: float, nperseg: int = 1024) -> SpectralFeatures:
    freqs, psd = welch(iq, fs=sample_rate_hz, nperseg=min(nperseg, len(iq)), return_onesided=False)
    order = np.argsort(freqs)
    freqs, psd = freqs[order], psd[order]
    psd_db = 10 * np.log10(psd + 1e-20)

    peak_idx = int(np.argmax(psd))
    peak_freq = float(freqs[peak_idx])

    # occupied bandwidth: smallest band containing 99% of spectral energy
    total_energy = np.sum(psd)
    cumulative = np.cumsum(psd[np.argsort(-psd)])
    sorted_freqs = freqs[np.argsort(-psd)]
    keep = cumulative <= 0.99 * total_energy
    if np.any(keep):
        occ_freqs = sorted_freqs[: np.sum(keep) + 1]
        occupied_bw = float(np.max(occ_freqs) - np.min(occ_freqs))
    else:
        occupied_bw = float(freqs[-1] - freqs[0])

    p_norm = psd / (np.sum(psd) + 1e-20)
    spectral_entropy = float(-np.sum(p_norm * np.log2(p_norm + 1e-20)) / np.log2(len(p_norm)))
    spectral_flatness = float(
        np.exp(np.mean(np.log(psd + 1e-20))) / (np.mean(psd) + 1e-20)
    )

    return SpectralFeatures(
        freqs_hz=freqs,
        psd_db=psd_db,
        peak_freq_hz=peak_freq,
        occupied_bandwidth_hz=occupied_bw,
        spectral_entropy=spectral_entropy,
        spectral_flatness=spectral_flatness,
    )


def extract_iq_features(iq: np.ndarray, sample_rate_hz: float) -> IQFeatures:
    amplitude = np.abs(iq)
    phase = np.unwrap(np.angle(iq))
    inst_freq = np.diff(phase) / (2 * np.pi) * sample_rate_hz

    mean_amp = float(np.mean(amplitude))
    std_amp = float(np.std(amplitude))
    amp_var_norm = float(np.var(amplitude) / (mean_amp ** 2 + 1e-20))  # ~0 for constant-envelope signals

    def kurtosis(x):
        x = x - np.mean(x)
        s = np.std(x) + 1e-20
        return float(np.mean((x / s) ** 4) - 3.0)

    peak_power = float(np.max(amplitude) ** 2)
    avg_power = float(np.mean(amplitude ** 2)) + 1e-20
    papr_db = 10 * np.log10(peak_power / avg_power)

    return IQFeatures(
        mean_amplitude=mean_amp,
        amplitude_std=std_amp,
        amplitude_variance_normalized=amp_var_norm,
        phase_std=float(np.std(np.diff(phase))),
        inst_freq_std_hz=float(np.std(inst_freq)),
        kurtosis_amplitude=kurtosis(amplitude),
        kurtosis_phase=kurtosis(np.diff(phase)),
        papr_db=papr_db,
    )


def estimate_symbol_rate(iq: np.ndarray, sample_rate_hz: float, psk_like: bool = True) -> tuple[float, float]:
    """
    Cyclostationary symbol-rate estimate. For PSK/QAM-family signals, raising
    to the 4th (or 2nd) power collapses the modulation and leaves a spectral
    line at the symbol rate; for FSK/ASK-family, the squared-magnitude
    spectrum shows the same line. Returns (symbol_rate_hz, confidence 0-1).
    """
    if psk_like:
        nonlinear = iq ** 4
    else:
        nonlinear = np.abs(iq) ** 2 - np.mean(np.abs(iq) ** 2)

    n = len(nonlinear)
    spectrum = np.abs(np.fft.fft(nonlinear))
    freqs = np.fft.fftfreq(n, d=1.0 / sample_rate_hz)

    # ignore DC region
    dc_guard = max(1, n // 200)
    spectrum[:dc_guard] = 0
    spectrum[-dc_guard:] = 0

    half = n // 2
    peak_idx = int(np.argmax(spectrum[:half]))
    candidate_rate = abs(freqs[peak_idx])

    # Confidence: peak-to-median ratio of the candidate spectral line vs. the
    # rest of the spectrum. (An earlier version used peak/total-energy, which
    # is diluted across thousands of bins and under-reported confidence even
    # for a textbook-clean symbol-rate line -- found via testing against a
    # known-good synthetic signal where peak/total gave 0.07 confidence for a
    # spectral line that a peak/median comparison correctly shows is ~100x
    # the surrounding noise floor.) Scaling saturates smoothly toward 1.0.
    median_level = np.median(spectrum[:half]) + 1e-20
    peak_to_median = spectrum[peak_idx] / median_level
    confidence = float(np.clip(np.log10(peak_to_median + 1) / 2.5, 0.0, 1.0))

    return float(candidate_rate), confidence


def detect_signal_regions(iq: np.ndarray, sample_rate_hz: float, noise_floor_db: float,
                           threshold_db: float = 6.0, window: int = 256) -> list[tuple[int, int]]:
    """
    Simple wideband energy detector: sliding-window power vs. noise-floor
    threshold, merged into contiguous regions. This is Stage 5/6 (detection
    + segmentation) in its minimal viable form -- single-channel time-domain
    energy detection, not yet full time-frequency clustering (see roadmap).
    """
    power = np.abs(iq) ** 2
    n = len(power)
    n_windows = n // window
    if n_windows == 0:
        return []
    windowed = power[: n_windows * window].reshape(n_windows, window).mean(axis=1)
    windowed_db = 10 * np.log10(windowed + 1e-20)

    active = windowed_db > (noise_floor_db + threshold_db)
    regions = []
    start = None
    for i, is_active in enumerate(active):
        if is_active and start is None:
            start = i
        elif not is_active and start is not None:
            regions.append((start * window, i * window))
            start = None
    if start is not None:
        regions.append((start * window, n_windows * window))
    return regions
