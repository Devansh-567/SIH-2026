"""
Demo sample catalog -- powers the GUI's "No files? Try one of these"
panel, which exists so a judge/evaluator with no .iq file of their own can
click one button and see the full pipeline run end to end.

Samples are GENERATED on demand from rfplatform.synth.generator (cached on
disk after first build), not shipped as binary blobs in the repo. Three
reasons that matters:
  1. The repo stays small and text-only.
  2. Every sample's ground truth is known exactly, because we made it --
     so the UI can show "expected vs. what the pipeline found" honestly.
  3. They exercise the SAME generator the test suite validates against,
     so a demo sample can't silently diverge from tested behavior.

Honesty note carried into the UI: these are SYNTHETIC signals, clearly
labelled as such. They are not off-air captures, and the UI says so --
a judge should not be left thinking these are real intercepts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from rfplatform.synth.generator import SynthConfig, generate, generate_from_bits, save_sigmf

SAMPLE_DIR = Path("/tmp/rfplatform_samples")


@dataclass
class SampleSpec:
    id: str
    title: str
    description: str          # what an analyst/judge should expect to see
    highlights: list[str]     # short bullets: which platform features this one shows off
    expected: dict            # ground truth, shown in the UI next to what the pipeline found
    builder: str              # which build function to use
    params: dict = field(default_factory=dict)


CATALOG: list[SampleSpec] = [
    SampleSpec(
        id="qpsk_clean",
        title="QPSK @ 20 dB SNR",
        description="A clean, textbook QPSK signal with SigMF metadata. The fastest way to see the "
                    "whole pipeline succeed: detection, classification, demodulation and bitstream analysis.",
        highlights=["SigMF metadata is read, not guessed", "DSP + AI classifiers agree \u2192 high confidence",
                    "Clean demodulation, low EVM"],
        expected={"modulation": "qpsk", "sample_rate_hz": 1_000_000.0, "center_freq_hz": 100_000_000.0,
                  "snr_db": 20.0, "symbol_rate_hz": 125_000.0},
        builder="simple",
        params={"modulation": "qpsk", "snr_db": 20.0, "n_symbols": 8000, "samples_per_symbol": 8,
                "sample_rate_hz": 1_000_000.0, "center_freq_hz": 100_000_000.0, "seed": 101},
    ),
    SampleSpec(
        id="fsk_lowsnr",
        title="2-FSK @ 3 dB SNR (hard case)",
        description="A noisy 2-FSK burst near the edge of usability. Deliberately included to show the "
                    "platform degrading honestly -- expect lower confidence, and possibly an UNKNOWN or "
                    "HYPOTHESIZED verdict rather than a confident wrong answer.",
        highlights=["Confidence drops as SNR drops", "Honest UNKNOWN/HYPOTHESIZED reporting",
                    "No fabricated certainty"],
        expected={"modulation": "2fsk", "sample_rate_hz": 1_000_000.0, "center_freq_hz": 433_000_000.0,
                  "snr_db": 3.0, "symbol_rate_hz": 125_000.0},
        builder="simple",
        params={"modulation": "2fsk", "snr_db": 3.0, "n_symbols": 8000, "samples_per_symbol": 8,
                "sample_rate_hz": 1_000_000.0, "center_freq_hz": 433_000_000.0, "seed": 202,
                "fsk_deviation_hz": 60_000.0},
    ),
    SampleSpec(
        id="multi_signal",
        title="Two signals in one recording",
        description="A BPSK burst and a 16-QAM burst separated in time, with noise between them. Shows "
                    "automatic multi-signal segmentation: the pipeline finds and analyzes BOTH "
                    "independently instead of only the strongest.",
        highlights=["Automatic multi-signal segmentation", "Per-signal parameters and fingerprints",
                    "Each signal classified separately"],
        expected={"modulation": "bpsk + 16qam (2 signals)", "sample_rate_hz": 1_000_000.0,
                  "center_freq_hz": 2_400_000_000.0, "snr_db": 20.0},
        builder="multi",
        params={"sample_rate_hz": 1_000_000.0, "center_freq_hz": 2_400_000_000.0, "seed": 303},
    ),
    SampleSpec(
        id="fec_coded",
        title="BPSK with convolutional FEC (K=7, rate 1/2)",
        description="A BPSK signal whose payload was encoded with the standard CCSDS K=7 rate-1/2 "
                    "convolutional code before transmission. Shows the FEC hypothesis search actually "
                    "identifying the right code from the demodulated bits.",
        highlights=["FEC hypothesis search over real coded data", "Viterbi decoding with self-verification",
                    "Reed-Solomon candidates ranked alongside"],
        expected={"modulation": "bpsk", "sample_rate_hz": 1_000_000.0, "center_freq_hz": 137_000_000.0,
                  "snr_db": 22.0, "fec": "convolutional K=7 rate 1/2 (CCSDS)"},
        builder="fec",
        params={"sample_rate_hz": 1_000_000.0, "center_freq_hz": 137_000_000.0, "seed": 404,
                "snr_db": 22.0, "samples_per_symbol": 8},
    ),
]

CATALOG_BY_ID = {s.id: s for s in CATALOG}


def _build_simple(spec: SampleSpec, out_path: Path) -> None:
    p = spec.params
    cfg = SynthConfig(
        modulation=p["modulation"], n_symbols=p["n_symbols"], sample_rate_hz=p["sample_rate_hz"],
        samples_per_symbol=p["samples_per_symbol"], snr_db=p["snr_db"], seed=p["seed"],
        fsk_deviation_hz=p.get("fsk_deviation_hz", 5000.0),
    )
    result = generate(cfg)
    save_sigmf(result, str(out_path), center_freq_hz=p["center_freq_hz"])


def _build_multi(spec: SampleSpec, out_path: Path) -> None:
    p = spec.params
    rng = np.random.default_rng(p["seed"])
    sr = p["sample_rate_hz"]

    bpsk = generate(SynthConfig(modulation="bpsk", n_symbols=6000, sample_rate_hz=sr,
                                 samples_per_symbol=8, snr_db=20.0, seed=p["seed"]))
    qam = generate(SynthConfig(modulation="16qam", n_symbols=6000, sample_rate_hz=sr,
                                samples_per_symbol=8, snr_db=20.0, seed=p["seed"] + 1))
    gap = ((rng.standard_normal(120_000) + 1j * rng.standard_normal(120_000)) * 0.02).astype(np.complex64)

    combined = np.concatenate([gap, bpsk.iq, gap, qam.iq, gap]).astype(np.complex64)

    # reuse the BPSK result object as a carrier for the combined IQ so we can
    # go through the same SigMF writer every other sample uses
    bpsk.iq = combined
    save_sigmf(bpsk, str(out_path), center_freq_hz=p["center_freq_hz"])


def _build_fec(spec: SampleSpec, out_path: Path) -> None:
    from rfplatform.fec import convolutional as convfec

    p = spec.params
    rng = np.random.default_rng(p["seed"])
    payload_bits = rng.integers(0, 2, size=3000).astype(np.int64)
    coded_bits = convfec.encode(payload_bits, "k7_r1/2_ccsds").astype(np.int64)

    cfg = SynthConfig(
        modulation="bpsk", n_symbols=len(coded_bits), sample_rate_hz=p["sample_rate_hz"],
        samples_per_symbol=p["samples_per_symbol"], snr_db=p["snr_db"], seed=p["seed"],
    )
    result = generate_from_bits(coded_bits, cfg)
    result.ground_truth["fec"] = "convolutional k7_r1/2_ccsds"
    save_sigmf(result, str(out_path), center_freq_hz=p["center_freq_hz"])


_BUILDERS = {"simple": _build_simple, "multi": _build_multi, "fec": _build_fec}


def ensure_sample(sample_id: str) -> Path:
    """
    Returns the path to the sample's .sigmf-data file, generating it (and
    its .sigmf-meta sidecar) on first request. Cached on disk thereafter
    so repeated demo clicks are instant.
    """
    spec = CATALOG_BY_ID.get(sample_id)
    if spec is None:
        raise KeyError(f"Unknown sample id '{sample_id}'. Available: {sorted(CATALOG_BY_ID)}")

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    data_path = SAMPLE_DIR / f"{sample_id}.sigmf-data"
    meta_path = SAMPLE_DIR / f"{sample_id}.sigmf-meta"
    if data_path.exists() and meta_path.exists():
        return data_path

    _BUILDERS[spec.builder](spec, data_path)
    return data_path


def catalog_as_dicts() -> list[dict]:
    return [
        {"id": s.id, "title": s.title, "description": s.description,
         "highlights": s.highlights, "expected": s.expected}
        for s in CATALOG
    ]
