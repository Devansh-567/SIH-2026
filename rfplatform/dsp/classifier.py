"""
Deterministic, explainable modulation classification -- PART 10/11 of the
architecture report ("use deterministic DSP wherever it is more reliable").

This is intentionally NOT a machine-learning model. It is a small decision
procedure over well-understood discriminating features, and every decision
carries the measured feature value as its evidence. Thresholds below were
empirically calibrated against the synthetic generator (see
tests/test_classifier_calibration.py) rather than guessed.

This module's output is one input to the confidence-fusion engine
(rfplatform/pipeline/fusion.py); it is deliberately independent of the ML
classifier so the two can be compared/fused rather than one just deferring
to the other.
"""

from __future__ import annotations

import numpy as np

from rfplatform.dsp import estimators as est
from rfplatform.models.schema import Evidence, Parameter, Status

# Empirically calibrated thresholds (see calibration test). These are
# intentionally conservative -- the classifier should say UNKNOWN/low
# confidence rather than force a guess near a decision boundary.
FSK_AMP_VAR_NORM_MAX = 0.02      # below this: constant-envelope (FSK family)
PSK_PAPR_DB_MAX = 5.5            # below this (and not FSK): PSK family
# above PSK_PAPR_DB_MAX (and not FSK): QAM family


def _mth_power_peakiness(iq: np.ndarray, m: int) -> float:
    x = iq.astype(np.complex128) ** m
    spec = np.abs(np.fft.fft(x))
    n = len(spec)
    guard = max(1, n // 200)
    spec[:guard] = 0
    spec[-guard:] = 0
    total = np.sum(spec) + 1e-12
    return float(np.max(spec) / total)


def _estimate_psk_order(iq: np.ndarray) -> tuple[int, float, dict]:
    scores = {m: _mth_power_peakiness(iq, m) for m in (2, 4, 8)}
    order_map = {2: 2, 4: 4, 8: 8}
    best_m = max(scores, key=scores.get)
    total = sum(scores.values()) + 1e-12
    margin_confidence = float(scores[best_m] / total)  # how dominant the winner is vs the field
    return order_map[best_m], margin_confidence, scores


def _estimate_qam_order(iq_features: est.IQFeatures) -> tuple[int, float]:
    """
    Coarse QAM-order hint from PAPR alone (higher-order QAM -> higher PAPR).
    This is intentionally a low-confidence heuristic -- accurate QAM order
    estimation really wants carrier/timing recovery + constellation
    clustering, which lives in the demod stage, not here. We say so via a
    low confidence score rather than pretending this is reliable.
    """
    if iq_features.papr_db < 7.0:
        return 16, 0.4
    return 64, 0.35


def classify_modulation(iq: np.ndarray, sample_rate_hz: float) -> tuple[Parameter, dict]:
    """
    Returns (Parameter for 'modulation', dict of raw features) -- the raw
    features dict is passed on to the fusion engine so it can be compared
    against the ML classifier's own feature basis.
    """
    iqf = est.extract_iq_features(iq, sample_rate_hz)
    evidence: list[Evidence] = []

    evidence.append(Evidence(
        source="dsp:amplitude_variance",
        description=f"Normalized amplitude variance = {iqf.amplitude_variance_normalized:.4f} "
                    f"({'near-zero -> constant envelope' if iqf.amplitude_variance_normalized < FSK_AMP_VAR_NORM_MAX else 'non-zero -> varying envelope'})",
        value=iqf.amplitude_variance_normalized,
    ))

    if iqf.amplitude_variance_normalized < FSK_AMP_VAR_NORM_MAX:
        # Constant-envelope family -> FSK (CPM). Distinguish 2FSK vs 4FSK is a
        # secondary, lower-confidence call based on the discrete-tone count;
        # for MVP we report the family confidently and 2FSK as the modal
        # top hypothesis with 4FSK as an explicit alternative.
        confidence = float(min(0.95, 0.6 + (FSK_AMP_VAR_NORM_MAX - iqf.amplitude_variance_normalized) * 10))
        param = Parameter(
            name="modulation",
            value="2fsk",
            status=Status.INFERRED,
            confidence=confidence,
            alternatives=[("4fsk", round(confidence * 0.5, 3)), ("gfsk", round(confidence * 0.2, 3))],
            evidence=evidence,
        )
        return param, {"family": "fsk", "iq_features": iqf}

    evidence.append(Evidence(
        source="dsp:papr",
        description=f"Peak-to-average power ratio = {iqf.papr_db:.2f} dB "
                    f"({'consistent with constant-modulus PSK' if iqf.papr_db < PSK_PAPR_DB_MAX else 'consistent with multi-amplitude QAM'})",
        value=iqf.papr_db,
    ))

    if iqf.papr_db < PSK_PAPR_DB_MAX:
        order, margin_conf, scores = _estimate_psk_order(iq)
        evidence.append(Evidence(
            source="dsp:mth_power_method",
            description=f"M-th power spectral peakiness scores {scores} -> order-{order} PSK dominant",
            value=scores,
        ))
        confidence = float(min(0.92, 0.5 + margin_conf * 3))
        label = {2: "bpsk", 4: "qpsk", 8: "8psk"}[order]
        alt_orders = [o for o in (2, 4, 8) if o != order]
        alternatives = [
            ({2: "bpsk", 4: "qpsk", 8: "8psk"}[o], round(confidence * (scores[o] / sum(scores.values())) * 2, 3))
            for o in alt_orders
        ]
        param = Parameter(
            name="modulation", value=label, status=Status.INFERRED,
            confidence=confidence, alternatives=alternatives, evidence=evidence,
        )
        return param, {"family": "psk", "order": order, "iq_features": iqf}

    order, order_conf = _estimate_qam_order(iqf)
    evidence.append(Evidence(
        source="dsp:papr_qam_order_hint",
        description=f"PAPR-based QAM order hint: {order}-QAM (low-confidence heuristic; "
                    f"confirm via constellation after demodulation)",
        value=order,
    ))
    label = {16: "16qam", 64: "64qam"}[order]
    other = "64qam" if label == "16qam" else "16qam"
    param = Parameter(
        name="modulation", value=label, status=Status.INFERRED,
        confidence=order_conf, alternatives=[(other, round(order_conf * 0.6, 3))],
        evidence=evidence,
    )
    return param, {"family": "qam", "order": order, "iq_features": iqf}


def estimate_parameters(iq: np.ndarray, sample_rate_hz: float, family_hint: str | None = None) -> list[Parameter]:
    """
    Runs the full deterministic-DSP parameter extraction (PART 10 + the
    'PARAMETERS WE WANT TO EXTRACT' list) and returns them as Parameter
    objects ready for fusion / GUI display / report export.
    """
    params: list[Parameter] = []

    noise = est.estimate_noise_floor(iq, sample_rate_hz)
    params.append(Parameter(
        name="noise_floor_db", value=round(noise.noise_floor_db, 2), status=Status.ESTIMATED,
        confidence=1.0 if noise.method_agreement_db < 2.0 else 0.6, unit="dB",
        evidence=[Evidence("dsp:welch_psd_percentile_and_mad",
                            f"Percentile and MAD noise-floor estimators agree within {noise.method_agreement_db:.2f} dB",
                            value=noise.method_agreement_db)],
    ))

    spec = est.extract_spectral_features(iq, sample_rate_hz)

    # SNR estimate: noise_floor_db is a *power-spectral-density* level
    # (power per Hz), while raw time-domain power is total power across the
    # whole sampled bandwidth -- these must be converted to the same units
    # before subtracting. Integrate the noise PSD over the sampled
    # bandwidth to get total noise power, then back it out of total
    # received power to get an estimated signal-only power.
    total_power_linear = float(np.mean(np.abs(iq) ** 2))
    noise_floor_linear = 10 ** (noise.noise_floor_db / 10)
    noise_power_linear = max(noise_floor_linear * sample_rate_hz, 1e-30)
    signal_power_linear = max(total_power_linear - noise_power_linear, total_power_linear * 1e-6)
    snr_est = 10 * np.log10(signal_power_linear / noise_power_linear)

    params.append(Parameter(
        name="occupied_bandwidth_hz", value=round(spec.occupied_bandwidth_hz, 1), status=Status.ESTIMATED,
        confidence=0.85, unit="Hz",
        evidence=[Evidence("dsp:welch_psd_99pct_energy", "99% spectral-energy containment bandwidth",
                            value=spec.occupied_bandwidth_hz)],
    ))
    params.append(Parameter(
        name="peak_frequency_hz", value=round(spec.peak_freq_hz, 1), status=Status.ESTIMATED,
        confidence=0.9, unit="Hz",
        evidence=[Evidence("dsp:welch_psd_argmax", "Frequency bin of maximum PSD", value=spec.peak_freq_hz)],
    ))
    params.append(Parameter(
        name="snr_db", value=round(float(snr_est), 2), status=Status.ESTIMATED, confidence=0.75, unit="dB",
        evidence=[Evidence("dsp:power_minus_noise_floor",
                            "Total signal power minus estimated noise floor", value=snr_est)],
    ))
    params.append(Parameter(
        name="spectral_entropy", value=round(spec.spectral_entropy, 4), status=Status.ESTIMATED, confidence=0.9,
        evidence=[Evidence("dsp:normalized_shannon_entropy_of_psd", "0=single tone, 1=flat/noise-like",
                            value=spec.spectral_entropy)],
    ))

    mod_param, feature_ctx = classify_modulation(iq, sample_rate_hz)
    params.append(mod_param)

    psk_like = feature_ctx.get("family") in ("psk", "qam")
    sym_rate, sym_conf = est.estimate_symbol_rate(iq, sample_rate_hz, psk_like=psk_like)
    status = Status.ESTIMATED if sym_conf > 0.3 else Status.UNKNOWN
    params.append(Parameter(
        name="symbol_rate_hz",
        value=round(sym_rate, 1) if status != Status.UNKNOWN else None,
        status=status, confidence=sym_conf, unit="Hz",
        evidence=[Evidence("dsp:cyclostationary_mth_power_spectral_line",
                            f"Spectral-line strength ratio = {sym_conf:.3f} "
                            f"({'above' if sym_conf > 0.3 else 'below'} usable threshold)",
                            value=sym_conf)],
    ))

    return params
