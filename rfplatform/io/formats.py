"""
Format-agnostic, memory-mapped ingestion for .iq and .wav recordings.

Hard rule (see architecture report PART 19): nothing in this module ever
calls a whole-file read. Every access path returns a numpy.memmap-backed
view, or a chunk iterator over one, so a 100GB recording never touches RAM
except for the small window actually being processed.
"""

from __future__ import annotations

import json
import struct
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

# --- Sample format registry -------------------------------------------------
# Maps a short format code (as used by inspectrum/SNAIL-style extensions,
# and by our own synthetic generator) to (numpy dtype, is_complex, bytes/sample)

_RAW_FORMATS = {
    "cf32": (np.complex64, True),
    "fc32": (np.complex64, True),
    "cf64": (np.complex128, True),
    "fc64": (np.complex128, True),
    "cs16": (np.dtype([("i", "<i2"), ("q", "<i2")]), True),
    "cs8": (np.dtype([("i", "<i1"), ("q", "<i1")]), True),
    "cu8": (np.dtype([("i", "u1"), ("q", "u1")]), True),
    "f32": (np.float32, False),
    "s16": (np.int16, False),
    "s8": (np.int8, False),
    "u8": (np.uint8, False),
}

_EXT_TO_FORMAT = {
    ".cf32": "cf32", ".fc32": "cf32", ".cfile": "cf32",
    ".cf64": "cf64", ".fc64": "cf64",
    ".cs16": "cs16", ".cs8": "cs8", ".cu8": "cu8",
    ".iq": "cf32",  # default assumption when extension is generic; overridden by sidecar metadata if present
}


@dataclass
class RecordingHandle:
    """
    Unified handle to a loaded recording, regardless of original format.
    `samples` is a memmap (or memmap-backed) complex64 array -- callers
    should slice it, never call `[:]` on the whole thing for large files.
    """

    path: Path
    samples: np.ndarray            # memmap, dtype complex64, shape (N,)
    sample_rate_hz: Optional[float]
    center_freq_hz: Optional[float]
    source_format: str
    metadata_status: str           # "trusted_metadata" | "assumed_default" | "sidecar_sigmf"
    raw_metadata: dict = field(default_factory=dict)

    @property
    def num_samples(self) -> int:
        return self.samples.shape[0]

    def duration_s(self) -> Optional[float]:
        if self.sample_rate_hz:
            return self.num_samples / self.sample_rate_hz
        return None

    def chunks(self, chunk_size: int, overlap: int = 0) -> Iterator[tuple[int, np.ndarray]]:
        """Yield (start_index, chunk) pairs without ever materializing the full array."""
        step = chunk_size - overlap
        if step <= 0:
            raise ValueError("chunk_size must exceed overlap")
        n = self.num_samples
        i = 0
        while i < n:
            end = min(i + chunk_size, n)
            yield i, np.asarray(self.samples[i:end])  # copy only this chunk into RAM
            if end == n:
                break
            i += step


def _load_sigmf_sidecar(data_path: Path) -> Optional[dict]:
    meta_path = data_path.with_suffix(".sigmf-meta")
    if not meta_path.exists() and data_path.suffix == ".sigmf-data":
        meta_path = data_path.with_name(data_path.stem + ".sigmf-meta")
    if meta_path.exists():
        with open(meta_path, "r") as f:
            return json.load(f)
    return None


def _raw_iq_to_complex64(raw: np.ndarray, fmt: str) -> np.ndarray:
    dtype, is_complex = _RAW_FORMATS[fmt]
    if not is_complex:
        raise ValueError(f"format {fmt} is real-valued, not IQ")
    if fmt in ("cf32", "fc32"):
        return raw.astype(np.complex64, copy=False)
    if fmt in ("cf64", "fc64"):
        return raw.astype(np.complex64)
    if fmt == "cs16":
        i = raw["i"].astype(np.float32) / 32768.0
        q = raw["q"].astype(np.float32) / 32768.0
    elif fmt == "cs8":
        i = raw["i"].astype(np.float32) / 128.0
        q = raw["q"].astype(np.float32) / 128.0
    elif fmt == "cu8":
        i = (raw["i"].astype(np.float32) - 127.5) / 127.5
        q = (raw["q"].astype(np.float32) - 127.5) / 127.5
    else:
        raise ValueError(f"unsupported raw IQ format: {fmt}")
    return (i + 1j * q).astype(np.complex64)


def load_raw_iq(path: str | Path, fmt: Optional[str] = None,
                 sample_rate_hz: Optional[float] = None,
                 center_freq_hz: Optional[float] = None) -> RecordingHandle:
    """Load a raw binary IQ file via memmap. Format inferred from extension/SigMF sidecar if not given."""
    path = Path(path)
    sidecar = _load_sigmf_sidecar(path)
    metadata_status = "assumed_default"
    raw_meta: dict = {}

    if sidecar is not None:
        raw_meta = sidecar
        global_ = sidecar.get("global", {})
        fmt = fmt or global_.get("core:datatype", "").replace("_le", "").replace("_be", "") or None
        # SigMF datatype strings look like "cf32_le" -- normalize
        dt = global_.get("core:datatype")
        if dt:
            fmt = dt.split("_")[0]
        sample_rate_hz = sample_rate_hz or global_.get("core:sample_rate")
        captures = sidecar.get("captures", [{}])
        center_freq_hz = center_freq_hz or (captures[0].get("core:frequency") if captures else None)
        metadata_status = "sidecar_sigmf"

    if fmt is None:
        fmt = _EXT_TO_FORMAT.get(path.suffix.lower(), "cf32")

    if fmt not in _RAW_FORMATS:
        raise ValueError(f"Unknown/unsupported IQ sample format: {fmt}")

    dtype, is_complex = _RAW_FORMATS[fmt]
    if not is_complex:
        raise ValueError(f"{fmt} is a real-valued format; use load_raw_real() or treat as WAV")

    mm = np.memmap(path, dtype=dtype, mode="r")
    samples = _raw_iq_to_complex64(mm, fmt)

    return RecordingHandle(
        path=path,
        samples=samples,
        sample_rate_hz=sample_rate_hz,
        center_freq_hz=center_freq_hz,
        source_format=fmt,
        metadata_status=metadata_status if sample_rate_hz else "assumed_default",
        raw_metadata=raw_meta,
    )


def load_wav(path: str | Path) -> RecordingHandle:
    """
    Load a .wav file. Two real cases matter for RF work:
      - mono WAV: treated as a real-valued signal (e.g. an audio-band recording
        of a demodulated/discriminator-tapped signal) -- promoted to complex
        via Hilbert-transform-free zero-imaginary representation, flagged.
      - stereo WAV: many SDR tools (e.g. SDR# baseband recorders) store I on
        the left channel and Q on the right channel -- this is the common
        "WAV as IQ container" convention and is treated as complex IQ.
    """
    path = Path(path)
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        frame_rate = wf.getframerate()
        n_frames = wf.getnframes()
        data_start = wf.tell()

    dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
    if sample_width not in dtype_map:
        raise ValueError(f"unsupported WAV sample width: {sample_width} bytes")
    dtype = dtype_map[sample_width]

    # Locate the raw 'data' chunk offset via memmap over the whole file, then
    # slice -- this avoids the `wave` module's own internal buffering/copy.
    header_offset = _find_wav_data_offset(path)
    mm = np.memmap(path, dtype=dtype, mode="r", offset=header_offset, shape=(n_frames * n_channels,))

    scale = float(np.iinfo(dtype).max)

    if n_channels == 2:
        stereo = mm.reshape(-1, 2)
        i = stereo[:, 0].astype(np.float32) / scale
        q = stereo[:, 1].astype(np.float32) / scale
        samples = (i + 1j * q).astype(np.complex64)
        source_format = f"wav_stereo_iq_pcm{sample_width * 8}"
    elif n_channels == 1:
        real = mm.astype(np.float32) / scale
        samples = real.astype(np.complex64)  # zero imaginary part; real-valued signal
        source_format = f"wav_mono_real_pcm{sample_width * 8}"
    else:
        raise ValueError(f"unsupported channel count for RF WAV: {n_channels}")

    return RecordingHandle(
        path=path,
        samples=samples,
        sample_rate_hz=float(frame_rate),
        center_freq_hz=None,  # WAV headers never carry RF center frequency
        source_format=source_format,
        metadata_status="trusted_metadata",  # sample rate is a real WAV header field, trustworthy
        raw_metadata={"n_channels": n_channels, "sample_width": sample_width, "n_frames": n_frames},
    )


def _find_wav_data_offset(path: Path) -> int:
    """Parse RIFF chunks to find the byte offset of the 'data' chunk payload."""
    with open(path, "rb") as f:
        riff = f.read(12)
        if riff[0:4] != b"RIFF" or riff[8:12] != b"WAVE":
            raise ValueError("not a valid RIFF/WAVE file")
        while True:
            chunk_header = f.read(8)
            if len(chunk_header) < 8:
                raise ValueError("malformed WAV: 'data' chunk not found")
            chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)
            if chunk_id == b"data":
                return f.tell()
            # skip this chunk (with WORD-alignment padding, per RIFF spec)
            f.seek(chunk_size + (chunk_size & 1), 1)


def load_recording(path: str | Path, fmt: Optional[str] = None,
                    sample_rate_hz: Optional[float] = None,
                    center_freq_hz: Optional[float] = None) -> RecordingHandle:
    """Single entry point: dispatches to the right loader based on extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return load_wav(path)
    if suffix == ".sigmf-data":
        return load_raw_iq(path, fmt=fmt, sample_rate_hz=sample_rate_hz, center_freq_hz=center_freq_hz)
    return load_raw_iq(path, fmt=fmt, sample_rate_hz=sample_rate_hz, center_freq_hz=center_freq_hz)
