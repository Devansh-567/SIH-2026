"""
Format-agnostic, memory-mapped ingestion for .iq and .wav recordings.

Hard rule (see architecture report PART 19): nothing in this module ever
calls a whole-file read. Every access path returns a numpy.memmap-backed
view, or a chunk iterator over one, so a 100GB recording never touches RAM
except for the small window actually being processed.

SigMF support (see also rfplatform/pipeline/stages.py and
rfplatform/api/main.py, which consume RecordingHandle.sample_rate_hz /
center_freq_hz throughout): a `.sigmf-data` file is, by the SigMF spec
itself, not self-describing -- the accompanying `.sigmf-meta` JSON is the
only source of `core:datatype` (how to decode the bytes at all) and
`core:sample_rate` / `core:frequency` (how to interpret them in Hz). This
module therefore treats `.sigmf-data` specially: if no sidecar metadata
resolves `core:datatype` and no explicit `fmt` override is supplied, we
raise `MissingSigMFMetadataError` rather than silently guessing a format
(an earlier version of this code defaulted unresolved `.sigmf-data` files
to "cf32", which is exactly the kind of silent-incorrect-default this
module is now written to refuse). Sample rate is handled the same way one
layer up, in the pipeline (see stages.py) -- it is never fabricated here,
and the pipeline never substitutes a placeholder like 1 Hz; instead it
reports Status.UNKNOWN and skips every frequency-dependent stage.
"""

from __future__ import annotations

import json
import re
import struct
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import numpy as np


class MissingSigMFMetadataError(Exception):
    """
    Raised when a .sigmf-data file's sample format (core:datatype) cannot
    be resolved -- no matching .sigmf-meta sidecar was found/uploaded, and
    no explicit format override was supplied. Unlike a missing sample rate
    (which still permits time-domain-only inspection, see stages.py), a
    missing datatype means the raw bytes literally cannot be decoded into
    IQ samples at all, so this is a hard error rather than a degraded/
    UNKNOWN result.
    """


# --- SigMF sample-format parsing --------------------------------------------
# SigMF's core:datatype vocabulary: <c|r><f|i|u><8|16|32|64>[_le|_be]
#   c/r     = complex (interleaved I,Q) or real (single component)
#   f/i/u   = floating point / signed integer / unsigned integer
#   bits    = component width in bits (NOT total sample width for complex)
#   _le/_be = byte order; REQUIRED for every width except 8-bit, where
#             byte order is moot for a single byte.
# Reference: https://github.com/sigmf/SigMF-spec
_SIGMF_DATATYPE_RE = re.compile(r"^(?P<complex>c|r)(?P<kind>f|i|u)(?P<bits>8|16|32|64)(?:_(?P<endian>le|be))?$")


def _is_canonical_sigmf_datatype(fmt: str) -> bool:
    """
    True only for strings that are actually valid per the SigMF spec: an
    explicit _le/_be suffix is required for every width except 8-bit
    (where byte order is moot). This distinction matters -- without it, a
    bare width like "cf32" (missing its required suffix) would match the
    datatype *shape* and be accepted as already-canonical, silently
    skipping the legacy-alias normalization that maps our short "cf32"
    alias onto the real canonical string "cf32_le". Found via testing:
    parse_sample_format("cf32") returned "cf32" unnormalized until this
    check was added.
    """
    m = _SIGMF_DATATYPE_RE.match(fmt)
    if not m:
        return False
    bits = int(m.group("bits"))
    endian = m.group("endian")
    return endian is None if bits == 8 else endian is not None

# Legacy short aliases (as used by our own synthetic generator, inspectrum/
# SNAIL-style file extensions, and this project's own earlier code/tests)
# mapped onto the canonical SigMF datatype string, so both vocabularies
# funnel through one real parser instead of two parallel implementations.
_LEGACY_ALIASES = {
    "cf32": "cf32_le", "fc32": "cf32_le",
    "cf64": "cf64_le", "fc64": "cf64_le",
    "cs8": "ci8", "cs16": "ci16_le", "cs32": "ci32_le",
    "cu8": "cu8", "cu16": "cu16_le", "cu32": "cu32_le",
    "f32": "rf32_le", "f64": "rf64_le",
    "s8": "ri8", "s16": "ri16_le", "s32": "ri32_le",
    "u8": "ru8", "u16": "ru16_le", "u32": "ru32_le",
}

_EXT_TO_LEGACY_FORMAT = {
    ".cf32": "cf32", ".fc32": "cf32", ".cfile": "cf32",
    ".cf64": "cf64", ".fc64": "cf64",
    ".cs16": "cs16", ".cs8": "cs8", ".cu8": "cu8",
    ".iq": "cf32",  # default assumption when extension is generic and no SigMF sidecar exists
}


@dataclass
class SampleFormat:
    """A fully-resolved sample format: how to read raw bytes into complex64."""

    canonical: str          # canonical SigMF datatype string, e.g. "cf32_le"
    is_complex: bool
    component_dtype: np.dtype   # dtype of ONE component (I, or Q, or the lone real sample)
    is_float: bool
    max_abs_value: float    # normalization divisor for integer types (1.0 for float types)


def parse_sample_format(fmt: str) -> SampleFormat:
    """
    Parse either a canonical SigMF core:datatype string (e.g. "ci16_le",
    "cf32_le", "ru8") or one of this project's legacy short aliases (e.g.
    "cs16", "cf32") into a fully-resolved SampleFormat. This is the single
    parser both the SigMF sidecar path and the legacy-extension path funnel
    through, so fixing/extending format support happens in one place.
    """
    fmt = (fmt or "").strip()
    canonical = fmt if _is_canonical_sigmf_datatype(fmt) else _LEGACY_ALIASES.get(fmt)
    if canonical is None:
        raise ValueError(
            f"Unrecognized sample format '{fmt}'. Expected a SigMF core:datatype string "
            f"(e.g. 'cf32_le', 'ci16_le', 'cu8') or one of {sorted(_LEGACY_ALIASES)}."
        )

    m = _SIGMF_DATATYPE_RE.match(canonical)
    is_complex = m.group("complex") == "c"
    kind = m.group("kind")
    bits = int(m.group("bits"))
    endian = m.group("endian") or "le"
    endian_char = "<" if endian == "le" else ">"

    if kind == "f":
        if bits not in (32, 64):
            raise ValueError(f"unsupported float width in '{canonical}': {bits} bits")
        component_dtype = np.dtype(f"{endian_char}f{bits // 8}")
        is_float = True
        max_abs_value = 1.0
    elif kind in ("i", "u"):
        np_kind = "i" if kind == "i" else "u"
        # 8-bit types have no meaningful byte order
        prefix = "" if bits == 8 else endian_char
        component_dtype = np.dtype(f"{prefix}{np_kind}{bits // 8}")
        is_float = False
        max_abs_value = float(2 ** (bits - 1))
    else:
        raise ValueError(f"unknown SigMF datatype kind in '{canonical}': '{kind}'")

    return SampleFormat(canonical=canonical, is_complex=is_complex, component_dtype=component_dtype,
                         is_float=is_float, max_abs_value=max_abs_value)


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
    metadata_status: str           # "trusted_metadata" | "assumed_default" | "sidecar_sigmf" | "sidecar_sigmf_partial"
    raw_metadata: dict = field(default_factory=dict)
    sigmf_meta_path: Optional[Path] = None

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


def _find_sigmf_meta_path(data_path: Path) -> Optional[Path]:
    """
    Locate the .sigmf-meta sidecar for a given .sigmf-data file. Handles
    both the plain SigMF naming convention (`name.sigmf-data` /
    `name.sigmf-meta`) and this project's upload-time naming convention
    (`{file_id}__{original_stem}.sigmf-data`), since `Path.with_suffix`
    only ever touches the final `.sigmf-data`/`.sigmf-meta` extension and
    leaves everything before it (including a `{file_id}__` prefix) intact.
    """
    candidate = data_path.with_suffix(".sigmf-meta")
    if candidate.exists():
        return candidate
    # fallback for any caller that passes a bare stem without the standard suffix chain
    alt = data_path.with_name(data_path.stem + ".sigmf-meta")
    if alt.exists():
        return alt
    return None


def _load_sigmf_sidecar(data_path: Path) -> tuple[Optional[dict], Optional[Path]]:
    meta_path = _find_sigmf_meta_path(data_path)
    if meta_path is None:
        return None, None
    with open(meta_path, "r") as f:
        return json.load(f), meta_path


def _raw_to_complex64(raw: np.ndarray, spec: SampleFormat) -> np.ndarray:
    """Generic, format-driven conversion -- covers every SigMF datatype and
    legacy alias through the same normalization logic, rather than a
    per-format if/elif chain that has to be manually extended for each new
    bit width."""
    if spec.is_complex:
        flat = raw.view(spec.component_dtype).reshape(-1, 2)
        i_raw, q_raw = flat[:, 0], flat[:, 1]
    else:
        i_raw = raw.view(spec.component_dtype)
        q_raw = None

    def _normalize(component: np.ndarray) -> np.ndarray:
        if spec.is_float:
            return component.astype(np.float32, copy=False)
        if spec.component_dtype.kind == "u":
            # unsigned integer formats are offset-binary: midpoint = zero
            midpoint = spec.max_abs_value
            return (component.astype(np.float32) - midpoint) / midpoint
        return component.astype(np.float32) / spec.max_abs_value

    i = _normalize(i_raw)
    if spec.is_complex:
        q = _normalize(q_raw)
        return (i + 1j * q).astype(np.complex64)
    return i.astype(np.complex64)  # real-valued signal, zero imaginary part


def load_raw_iq(path: str | Path, fmt: Optional[str] = None,
                 sample_rate_hz: Optional[float] = None,
                 center_freq_hz: Optional[float] = None) -> RecordingHandle:
    """
    Load a raw binary IQ file via memmap. Format is resolved in this order:
    explicit `fmt` argument > SigMF sidecar `core:datatype` > legacy
    extension guess (only for non-SigMF extensions -- see
    MissingSigMFMetadataError docstring for why `.sigmf-data` is excluded
    from the extension-guess fallback).
    """
    path = Path(path)
    sidecar, meta_path = _load_sigmf_sidecar(path)
    metadata_status = "assumed_default"
    raw_meta: dict = {}
    is_sigmf_data = path.suffix.lower() == ".sigmf-data"

    if sidecar is not None:
        raw_meta = sidecar
        global_ = sidecar.get("global", {})
        fmt = fmt or global_.get("core:datatype")
        sample_rate_hz = sample_rate_hz if sample_rate_hz is not None else global_.get("core:sample_rate")
        captures = sidecar.get("captures") or [{}]
        sidecar_freq = captures[0].get("core:frequency") if captures else None
        center_freq_hz = center_freq_hz if center_freq_hz is not None else sidecar_freq
        metadata_status = "sidecar_sigmf" if sample_rate_hz is not None else "sidecar_sigmf_partial"

    if fmt is None:
        if is_sigmf_data:
            # A .sigmf-data file has no self-describing format; guessing one
            # (e.g. defaulting to cf32) would silently misinterpret the raw
            # bytes for any recording that isn't actually cf32. Refuse.
            raise MissingSigMFMetadataError(
                f"'{path.name}' is a SigMF data file but its sample format (core:datatype) "
                f"could not be determined: no matching .sigmf-meta sidecar was found, and no "
                f"explicit format was provided. Upload the accompanying .sigmf-meta file, or "
                f"specify the format explicitly."
            )
        fmt = _EXT_TO_LEGACY_FORMAT.get(path.suffix.lower(), "cf32")

    spec = parse_sample_format(fmt)
    if not spec.is_complex:
        raise ValueError(f"'{fmt}' is a real-valued format, not IQ; use a complex (c*) datatype for IQ ingestion")

    mm = np.memmap(path, dtype=np.uint8, mode="r")
    samples = _raw_to_complex64(mm, spec)

    return RecordingHandle(
        path=path,
        samples=samples,
        sample_rate_hz=sample_rate_hz,
        center_freq_hz=center_freq_hz,
        source_format=spec.canonical,
        metadata_status=metadata_status,
        raw_metadata=raw_meta,
        sigmf_meta_path=meta_path,
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
