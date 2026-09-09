"""
Chunked/streaming analysis across an entire recording -- PART 19 of the
architecture report ("NEVER load a 100GB recording entirely into RAM").

This module is what makes that a real guarantee rather than an aspiration:
`rfplatform.io.formats.RecordingHandle.chunks()` already exists to hand out
bounded windows of a memmap-backed array, but until this module, nothing in
the pipeline actually called it -- noise estimation and signal detection
were capped to the first 2,000,000 samples of any file, meaning a signal
located later in a large recording was silently invisible to the pipeline,
not merely slower to reach. The functions here scan the *whole* file,
chunk by chunk, with peak memory bounded by one chunk (plus a small
overlap buffer), regardless of total file size.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import welch

from rfplatform.dsp.estimators import NoiseEstimate, noise_floor_from_psd
from rfplatform.io.formats import RecordingHandle

DEFAULT_CHUNK_SIZE = 2_000_000
DEFAULT_OVERLAP = 8192  # large enough to catch a detection window straddling a chunk boundary


def estimate_noise_floor_chunked(handle: RecordingHandle, chunk_size: int = DEFAULT_CHUNK_SIZE,
                                  nperseg: int = 1024, max_chunks: int | None = None) -> NoiseEstimate:
    """
    Streaming noise-floor estimate across the entire file: computes a Welch
    PSD per chunk and accumulates a running average, then applies the
    exact same percentile/MAD math the single-window estimator uses (via
    `noise_floor_from_psd`) to the averaged PSD. Peak memory is one chunk,
    not the whole file, regardless of how many chunks there are.
    """
    fs = handle.sample_rate_hz
    psd_sum: np.ndarray | None = None
    n_chunks = 0

    for i, (_, chunk) in enumerate(handle.chunks(chunk_size)):
        if max_chunks is not None and i >= max_chunks:
            break
        if len(chunk) < 32:
            continue
        _, psd = welch(chunk, fs=fs, nperseg=min(nperseg, len(chunk)), return_onesided=False)
        psd_sum = psd if psd_sum is None else psd_sum + psd
        n_chunks += 1

    if psd_sum is None or n_chunks == 0:
        # degenerate case: recording shorter than one usable chunk -- fall
        # back to a single-shot estimate over whatever samples exist
        _, psd = welch(np.asarray(handle.samples[:]), fs=fs, nperseg=min(nperseg, handle.num_samples),
                        return_onesided=False)
        return noise_floor_from_psd(psd)

    return noise_floor_from_psd(psd_sum / n_chunks)


@dataclass
class ChunkedDetectionResult:
    regions: list[tuple[int, int]]
    chunks_scanned: int
    total_samples_scanned: int


def detect_signal_regions_chunked(handle: RecordingHandle, noise_floor_db: float,
                                   chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP,
                                   threshold_db: float = 6.0, window: int = 256,
                                   max_chunks: int | None = None) -> ChunkedDetectionResult:
    """
    Streaming energy-detection scan across the entire file. Each chunk is
    scanned independently (peak memory: one chunk), with global sample
    indices, then adjacent/overlapping regions -- including a detection
    that straddles a chunk boundary, caught by the overlap margin -- are
    merged into the final region list.
    """
    from rfplatform.dsp.estimators import detect_signal_regions

    fs = handle.sample_rate_hz
    all_regions: list[tuple[int, int]] = []
    n_chunks = 0
    total_scanned = 0

    for i, (start_idx, chunk) in enumerate(handle.chunks(chunk_size, overlap=overlap)):
        if max_chunks is not None and i >= max_chunks:
            break
        if len(chunk) < window:
            continue
        local_regions = detect_signal_regions(chunk, fs, noise_floor_db, threshold_db=threshold_db, window=window)
        for s, e in local_regions:
            all_regions.append((start_idx + s, start_idx + e))
        n_chunks += 1
        total_scanned += len(chunk)

    merged = _merge_regions(all_regions)
    return ChunkedDetectionResult(regions=merged, chunks_scanned=n_chunks, total_samples_scanned=total_scanned)


def _merge_regions(regions: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merges overlapping/adjacent (start, end) index ranges -- needed
    because the overlap margin between chunks means the same physical
    signal can produce two separate detections (one per chunk) that need
    to be reunited into one region."""
    if not regions:
        return []
    ordered = sorted(regions)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged
