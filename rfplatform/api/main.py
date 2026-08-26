"""
FastAPI orchestration layer -- PART 8/9 of the architecture report.

Local-first by design: intended to run on 127.0.0.1, serving a future
React/TS GUI. No cloud calls, no external network dependency at runtime.
Run with: uvicorn rfplatform.api.main:app --reload --host 127.0.0.1
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rfplatform.io.formats import load_recording
from rfplatform.pipeline.stages import run_pipeline

app = FastAPI(
    title="RF Signal Analysis Platform API",
    version="0.1.0-mvp",
    description="Automated .IQ/.WAV signal analysis and parameter extraction -- SIH PS 26147",
)

# Local-first: CORS restricted to localhost origins for a locally-served GUI.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("/tmp/rfplatform_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Security note (architecture report PART 20): uploaded files are treated as
# untrusted. We cap upload size and restrict accepted extensions here; the
# ingestion layer itself (rfplatform.io.formats) is defensively written to
# bounds-check header fields before trusting them for allocation.
ALLOWED_EXTENSIONS = {".iq", ".wav", ".cf32", ".cs16", ".cs8", ".cu8", ".sigmf-data"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB -- large recordings are the whole point


class AnalyzeRequest(BaseModel):
    file_id: str
    fmt: str | None = None
    sample_rate_hz: float | None = None
    center_freq_hz: float | None = None
    overrides: dict = {}


class SpectrogramRequest(BaseModel):
    file_id: str
    fmt: str | None = None
    sample_rate_hz: float | None = None
    max_samples: int = 500_000       # cap analyzed window for MVP responsiveness
    time_bins: int = 220             # downsampled output resolution -- keeps payload small
    freq_bins: int = 220


@app.get("/health")
def health():
    return {"status": "ok", "pipeline_version": "0.1.0-mvp"}


@app.post("/upload")
async def upload_file(file: UploadFile):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file extension '{suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    file_id = str(uuid.uuid4())
    dest = UPLOAD_DIR / f"{file_id}{suffix}"

    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(8 * 1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "File exceeds maximum accepted upload size")
            out.write(chunk)

    # If the client also sent a matching .sigmf-meta, accept it as a sidecar
    # (handled separately in a real multipart flow; MVP: metadata via query params)
    return {"file_id": file_id, "filename": dest.name, "size_bytes": size}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    matches = list(UPLOAD_DIR.glob(f"{req.file_id}*"))
    if not matches:
        raise HTTPException(404, f"No uploaded file found for file_id={req.file_id}")
    file_path = matches[0]

    try:
        result = run_pipeline(
            str(file_path), fmt=req.fmt, sample_rate_hz=req.sample_rate_hz,
            center_freq_hz=req.center_freq_hz, overrides=req.overrides,
        )
    except Exception as e:
        raise HTTPException(500, f"Analysis pipeline failed: {e}")

    return result.as_dict()


@app.delete("/upload/{file_id}")
def delete_upload(file_id: str):
    matches = list(UPLOAD_DIR.glob(f"{file_id}*"))
    for m in matches:
        m.unlink(missing_ok=True)
    return {"deleted": len(matches)}


@app.post("/spectrogram")
def spectrogram(req: SpectrogramRequest):
    """
    Downsampled waterfall/spectrogram data for GUI rendering. Computes on a
    bounded window of the recording (never the whole multi-GB file -- see
    architecture report PART 19) and downsamples both axes server-side so
    the payload stays small regardless of FFT resolution used internally.
    """
    from scipy.signal import spectrogram as scipy_spectrogram
    import numpy as np

    matches = list(UPLOAD_DIR.glob(f"{req.file_id}*"))
    if not matches:
        raise HTTPException(404, f"No uploaded file found for file_id={req.file_id}")
    file_path = matches[0]

    try:
        handle = load_recording(str(file_path), fmt=req.fmt, sample_rate_hz=req.sample_rate_hz)
        fs = handle.sample_rate_hz or 1.0
        window = np.asarray(handle.samples[: min(handle.num_samples, req.max_samples)])
        if len(window) < 256:
            raise HTTPException(400, "Recording too short to compute a spectrogram")

        nperseg = min(1024, max(64, len(window) // req.time_bins))
        freqs, times, sxx = scipy_spectrogram(window, fs=fs, nperseg=nperseg, return_onesided=False)
        sxx_db = 10 * np.log10(sxx + 1e-20)

        # downsample both axes to the requested resolution for a small, fast-to-render payload
        f_idx = np.linspace(0, len(freqs) - 1, min(req.freq_bins, len(freqs))).astype(int)
        t_idx = np.linspace(0, len(times) - 1, min(req.time_bins, len(times))).astype(int)
        sxx_small = sxx_db[np.ix_(f_idx, t_idx)]
        freqs_small = np.fft.fftshift(freqs[f_idx])
        sxx_small = np.fft.fftshift(sxx_small, axes=0)

        return {
            "freqs_hz": freqs_small.tolist(),
            "times_s": times[t_idx].tolist(),
            "power_db": sxx_small.T.tolist(),  # shape [time][freq] for row-major GUI rendering
            "min_db": float(np.min(sxx_small)),
            "max_db": float(np.max(sxx_small)),
            "sample_rate_hz": fs,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Spectrogram computation failed: {e}")
