"""
FastAPI orchestration layer -- PART 8/9 of the architecture report.

Local-first by design: intended to run on 127.0.0.1, serving a future
React/TS GUI. No cloud calls, no external network dependency at runtime.
Run with: uvicorn rfplatform.api.main:app --reload --host 127.0.0.1
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from rfplatform.io.formats import MissingSigMFMetadataError, load_recording
from rfplatform.pipeline.compare import compare_analyses
from rfplatform.pipeline.stages import run_pipeline
from rfplatform.report import generator as report_generator
from rfplatform.storage import db as storage_db

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
ALLOWED_EXTENSIONS = {".iq", ".wav", ".cf32", ".cs16", ".cs8", ".cu8", ".sigmf-data", ".sigmf-meta"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB -- large recordings are the whole point

_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9_.\-]")


def _safe_stem(name: str) -> str:
    """Filesystem-safe version of an original filename's stem, used to pair
    .sigmf-data/.sigmf-meta uploads by filename (see upload_files below)
    and to build export download filenames. Collapses repeated dots (not
    just disallowed characters) so a path-traversal-looking input like
    "../../etc/passwd" can't survive as ".._.._etc_passwd" -- found via
    testing the export endpoint's filename_hint, which is attacker-
    controlled input reflected into a response header."""
    cleaned = _SAFE_STEM_RE.sub("_", name)
    cleaned = re.sub(r"\.{2,}", "_", cleaned)
    cleaned = cleaned.lstrip(".")
    return cleaned[:120] or "recording"


def _split_sigmf_suffix(filename: str) -> tuple[str, str | None]:
    """Returns (stem, 'sigmf-data' | 'sigmf-meta' | None) -- SigMF's dual
    extensions (.sigmf-data / .sigmf-meta) aren't a single dotted suffix
    Path.suffix would reliably isolate alongside arbitrary stems, so this
    matches them explicitly."""
    lower = filename.lower()
    if lower.endswith(".sigmf-data"):
        return filename[: -len(".sigmf-data")], "sigmf-data"
    if lower.endswith(".sigmf-meta"):
        return filename[: -len(".sigmf-meta")], "sigmf-meta"
    return filename, None


async def _save_upload(file: UploadFile, dest: Path) -> int:
    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(8 * 1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "File exceeds maximum accepted upload size")
            out.write(chunk)
    return size


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


class ExportRequest(BaseModel):
    format: str          # "json" | "csv" | "pdf" | "sigmf"
    analysis: dict | None = None   # the AnalysisResultJSON as already returned by /analyze
    analysis_id: str | None = None  # alternative to `analysis`: fetch from history by id
    filename_hint: str | None = None


class BatchAnalyzeRequest(BaseModel):
    file_ids: list[str]
    sample_rate_hz: float | None = None
    overrides: dict = {}


class FeedbackRequest(BaseModel):
    parameter_name: str
    corrected_value: object
    note: str | None = None


class AnnotationRequest(BaseModel):
    start_s: float
    end_s: float | None = None
    freq_hz: float | None = None
    label: str | None = None
    note: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "pipeline_version": "0.1.0-mvp"}


@app.post("/upload")
async def upload_files(files: list[UploadFile]):
    """
    Accepts one or more files in a single request. `.sigmf-data` and
    `.sigmf-meta` files are automatically paired by their original
    filename's stem (e.g. "bpsk_rect_20sps.sigmf-data" pairs with
    "bpsk_rect_20sps.sigmf-meta") and stored under one shared file_id --
    `{file_id}__{safe_stem}.sigmf-data` / `.sigmf-meta` -- so the ingestion
    layer's sidecar lookup (which matches by replacing just the final
    .sigmf-data/.sigmf-meta suffix) finds the pair regardless of upload
    order, and works whether both files arrive in the same request or two
    separate ones (we scan for an already-uploaded partner by stem before
    minting a new file_id). Non-SigMF files (.wav, .cf32, etc.) are stored
    standalone exactly as before.

    Returns one entry per logical recording (a SigMF pair counts as one),
    not one entry per uploaded file.
    """
    if not files:
        raise HTTPException(400, "No files provided")

    sigmf_uploads: dict[str, UploadFile] = {}     # stem -> data file
    sigmf_meta_uploads: dict[str, UploadFile] = {} # stem -> meta file
    standalone: list[UploadFile] = []

    for f in files:
        filename = f.filename or ""
        stem, kind = _split_sigmf_suffix(filename)
        if kind == "sigmf-data":
            sigmf_uploads[stem] = f
        elif kind == "sigmf-meta":
            sigmf_meta_uploads[stem] = f
        else:
            suffix = Path(filename).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                raise HTTPException(400, f"Unsupported file extension '{suffix}'. "
                                         f"Allowed: {sorted(ALLOWED_EXTENSIONS)}")
            standalone.append(f)

    results = []

    # Orphaned .sigmf-meta with no .sigmf-data in this same request, and no
    # previously-uploaded orphan .sigmf-data waiting for it, is a clear
    # user error worth rejecting up front rather than silently storing an
    # unpaired metadata file.
    all_stems = set(sigmf_uploads) | set(sigmf_meta_uploads)
    for stem in all_stems:
        safe = _safe_stem(stem)
        existing_data = list(UPLOAD_DIR.glob(f"*__{safe}.sigmf-data"))
        existing_meta = list(UPLOAD_DIR.glob(f"*__{safe}.sigmf-meta"))

        has_data = stem in sigmf_uploads or bool(existing_data)
        has_meta = stem in sigmf_meta_uploads or bool(existing_meta)

        if not has_data:
            raise HTTPException(400, f"'{stem}.sigmf-meta' was uploaded without a matching "
                                     f"'{stem}.sigmf-data' -- upload both together, or the .sigmf-data "
                                     f"file first.")

        # Reuse the file_id of an already-uploaded half of this pair so a
        # second, separate upload request still lands in the same recording.
        existing_any = existing_data + existing_meta
        if existing_any:
            file_id = existing_any[0].name.split("__", 1)[0]
        else:
            file_id = str(uuid.uuid4())

        saved = {}
        if stem in sigmf_uploads:
            dest = UPLOAD_DIR / f"{file_id}__{safe}.sigmf-data"
            saved["data_size_bytes"] = await _save_upload(sigmf_uploads[stem], dest)
        if stem in sigmf_meta_uploads:
            dest = UPLOAD_DIR / f"{file_id}__{safe}.sigmf-meta"
            saved["meta_size_bytes"] = await _save_upload(sigmf_meta_uploads[stem], dest)

        results.append({
            "file_id": file_id,
            "recording_name": stem,
            "kind": "sigmf",
            "sigmf_pair_complete": has_data and has_meta,
            **saved,
        })

    for f in standalone:
        suffix = Path(f.filename or "").suffix.lower()
        file_id = str(uuid.uuid4())
        dest = UPLOAD_DIR / f"{file_id}{suffix}"
        size = await _save_upload(f, dest)
        results.append({
            "file_id": file_id, "recording_name": Path(f.filename or "").stem,
            "kind": "standalone", "sigmf_pair_complete": None, "size_bytes": size,
        })

    return {"uploads": results}


def _resolve_data_file(file_id: str) -> Path:
    """
    Finds the primary data file for a file_id, explicitly excluding a
    `.sigmf-meta` sidecar from candidacy -- for a SigMF pair, both files
    share the same file_id prefix, so a naive first-match glob could return
    the metadata file instead of the data file `load_recording` expects as
    its entry point (it locates the sidecar itself from the data path).
    """
    matches = [p for p in UPLOAD_DIR.glob(f"{file_id}*") if not p.name.endswith(".sigmf-meta")]
    if not matches:
        raise HTTPException(404, f"No uploaded file found for file_id={file_id}")
    return matches[0]


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    file_path = _resolve_data_file(req.file_id)

    try:
        result = run_pipeline(
            str(file_path), fmt=req.fmt, sample_rate_hz=req.sample_rate_hz,
            center_freq_hz=req.center_freq_hz, overrides=req.overrides,
        )
    except MissingSigMFMetadataError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Analysis pipeline failed: {e}")

    result_dict = result.as_dict()
    try:
        storage_db.save_analysis(result_dict)
    except Exception:
        pass  # history persistence must never block returning a completed analysis
    return result_dict


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

    Never substitutes a placeholder sample rate: an unresolvable sample
    rate makes the frequency axis physically meaningless (every bin
    boundary, occupied bandwidth, and center-frequency calculation would be
    silently wrong), so this returns a clear 400 rather than a Hz-labeled
    plot computed against a fabricated 1 Hz rate.
    """
    from scipy.signal import spectrogram as scipy_spectrogram
    import numpy as np

    file_path = _resolve_data_file(req.file_id)

    try:
        handle = load_recording(str(file_path), fmt=req.fmt, sample_rate_hz=req.sample_rate_hz)
    except MissingSigMFMetadataError as e:
        raise HTTPException(400, str(e))

    if not handle.sample_rate_hz:
        raise HTTPException(
            400,
            "Sample rate is unknown for this recording (no .sigmf-meta sidecar, WAV header, or "
            "explicit sample_rate_hz was provided) -- a spectrogram's frequency axis would be "
            "meaningless without it. Provide sample_rate_hz explicitly, or upload the matching "
            ".sigmf-meta file.",
        )

    try:
        fs = handle.sample_rate_hz
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

        # When center_freq_hz is known (from SigMF metadata or an analyst
        # override), report an absolute RF frequency axis; otherwise the
        # axis is baseband-relative and the GUI is told so explicitly
        # rather than silently mislabeling it as absolute.
        is_absolute = handle.center_freq_hz is not None
        freq_offset = handle.center_freq_hz if is_absolute else 0.0

        return {
            "freqs_hz": (freqs_small + freq_offset).tolist(),
            "times_s": times[t_idx].tolist(),
            "power_db": sxx_small.T.tolist(),  # shape [time][freq] for row-major GUI rendering
            "min_db": float(np.min(sxx_small)),
            "max_db": float(np.max(sxx_small)),
            "sample_rate_hz": fs,
            "center_freq_hz": handle.center_freq_hz,
            "is_absolute_frequency": is_absolute,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Spectrogram computation failed: {e}")


_EXPORT_CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "pdf": "application/pdf",
    "sigmf": "application/json",  # a .sigmf-meta file is JSON with a conventional extension
}
_EXPORT_EXTENSIONS = {"json": "json", "csv": "csv", "pdf": "pdf", "sigmf": "sigmf-meta"}


@app.post("/export")
def export_report(req: ExportRequest):
    """
    Exports an already-computed analysis -- either passed directly as
    `analysis` (typically the exact response the GUI just received from
    /analyze) or fetched from history by `analysis_id` (this is what makes
    a report genuinely "shareable": share the id, and the recipient's own
    client can call /export themselves without needing the full JSON blob
    resent to them first) -- as JSON, CSV, PDF, or a SigMF `.sigmf-meta`
    annotations document.
    """
    fmt = req.format.lower()
    if fmt not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(400, f"Unsupported export format '{req.format}'. "
                                 f"Allowed: {sorted(_EXPORT_CONTENT_TYPES)}")

    analysis = req.analysis
    if analysis is None:
        if not req.analysis_id:
            raise HTTPException(400, "Either 'analysis' or 'analysis_id' is required")
        analysis = storage_db.get_analysis(req.analysis_id)
        if analysis is None:
            raise HTTPException(404, f"No stored analysis found for analysis_id={req.analysis_id}")

    try:
        if fmt == "json":
            body = report_generator.to_json_bytes(analysis)
        elif fmt == "csv":
            body = report_generator.to_csv_bytes(analysis)
        elif fmt == "sigmf":
            import json as _json
            body = _json.dumps(report_generator.to_sigmf_meta(analysis), indent=2).encode("utf-8")
        else:  # pdf
            body = report_generator.to_pdf_bytes(analysis)
    except Exception as e:
        raise HTTPException(500, f"Report generation failed: {e}")

    stem = _safe_stem(req.filename_hint or "rf_analysis_report")
    filename = f"{stem}.{_EXPORT_EXTENSIONS[fmt]}"

    return Response(
        content=body,
        media_type=_EXPORT_CONTENT_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Analysis history / shareable reports -----------------------------------

@app.get("/analyses")
def list_analyses(limit: int = 50, offset: int = 0):
    """History listing -- summary rows only (not full result blobs), newest first."""
    if limit > 200:
        raise HTTPException(400, "limit must be <= 200")
    return {"analyses": storage_db.list_analyses(limit=limit, offset=offset)}


@app.get("/analyses/compare")
def compare(a: str, b: str):
    """
    Parameter-by-parameter diff between two stored analyses, by id.
    Registered BEFORE the /analyses/{analysis_id} route below -- FastAPI/
    Starlette matches routes in registration order, and a literal segment
    ("compare") would otherwise be shadowed by the earlier-registered
    {analysis_id} path parameter, which matches any string. Confirmed this
    was a real bug during testing: with the routes in the opposite order,
    GET /analyses/compare?... returned 404 "No stored analysis found for
    analysis_id=compare" instead of ever reaching this handler.
    """
    analysis_a = storage_db.get_analysis(a)
    if analysis_a is None:
        raise HTTPException(404, f"No stored analysis found for analysis_id={a}")
    analysis_b = storage_db.get_analysis(b)
    if analysis_b is None:
        raise HTTPException(404, f"No stored analysis found for analysis_id={b}")
    return compare_analyses(analysis_a, analysis_b)


@app.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str):
    """Fetch a full stored analysis by id -- the shareable-report mechanism:
    share this id (or a URL containing it), and anyone with API access can
    retrieve the exact same analysis, or feed it to /export themselves."""
    result = storage_db.get_analysis(analysis_id)
    if result is None:
        raise HTTPException(404, f"No stored analysis found for analysis_id={analysis_id}")
    return result


@app.delete("/analyses/{analysis_id}")
def delete_analysis(analysis_id: str):
    deleted = storage_db.delete_analysis(analysis_id)
    if not deleted:
        raise HTTPException(404, f"No stored analysis found for analysis_id={analysis_id}")
    return {"deleted": True}


@app.get("/analyses/{analysis_id}/similar")
def similar_signals(analysis_id: str, signal_index: int = 0, top_k: int = 5):
    """
    Fingerprint-based similarity search: finds the most similar signals
    (by feature-vector distance, see dsp/fingerprint.py) across every
    OTHER analysis in history to the given signal within this analysis.
    """
    analysis = storage_db.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(404, f"No stored analysis found for analysis_id={analysis_id}")
    signals = analysis.get("signals", [])
    if not signals or signal_index >= len(signals):
        raise HTTPException(404, f"No signal at index {signal_index} in analysis {analysis_id}")
    query_fp = signals[signal_index].get("fingerprint", [])
    if not query_fp:
        raise HTTPException(400, "This signal has no fingerprint to search with")
    return {
        "query_analysis_id": analysis_id,
        "query_signal_index": signal_index,
        "results": storage_db.find_similar_signals(query_fp, exclude_analysis_id=analysis_id, top_k=top_k),
    }


# --- Batch analysis -----------------------------------------------------------

@app.post("/batch/analyze")
def batch_analyze(req: BatchAnalyzeRequest):
    """
    Runs the full pipeline on multiple already-uploaded files in one call,
    persisting each to history. Runs synchronously in a loop (matching
    /analyze's own synchronous pattern) rather than a background job
    queue -- a real async job system is a documented roadmap item (see
    architecture report PART 8's job-graph design), so batch size is
    capped to keep a single request's duration bounded in the meantime.
    """
    MAX_BATCH_SIZE = 20
    if len(req.file_ids) == 0:
        raise HTTPException(400, "file_ids must not be empty")
    if len(req.file_ids) > MAX_BATCH_SIZE:
        raise HTTPException(400, f"Batch size {len(req.file_ids)} exceeds the maximum of {MAX_BATCH_SIZE}")

    results = []
    for file_id in req.file_ids:
        entry = {"file_id": file_id}
        try:
            file_path = _resolve_data_file(file_id)
            analysis = run_pipeline(str(file_path), sample_rate_hz=req.sample_rate_hz, overrides=req.overrides)
            result_dict = analysis.as_dict()
            storage_db.save_analysis(result_dict)
            entry["status"] = "ok"
            entry["analysis_id"] = result_dict["manifest"]["analysis_id"]
            mod_param = next((p for p in result_dict["parameters"] if p["name"] == "modulation"), None)
            entry["modulation"] = mod_param["value"] if mod_param else None
            entry["num_signals"] = len(result_dict.get("signals", []))
        except HTTPException as e:
            entry["status"] = "error"
            entry["error"] = e.detail
        except MissingSigMFMetadataError as e:
            entry["status"] = "error"
            entry["error"] = str(e)
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = f"Analysis pipeline failed: {e}"
        results.append(entry)

    return {
        "results": results,
        "num_ok": sum(1 for r in results if r["status"] == "ok"),
        "num_failed": sum(1 for r in results if r["status"] == "error"),
    }


# --- Analyst feedback -----------------------------------------------------------

@app.post("/analyses/{analysis_id}/feedback")
def submit_feedback(analysis_id: str, req: FeedbackRequest):
    """
    Records an analyst correction for ANY parameter -- distinct from the
    /analyze `overrides` mechanism (which re-runs the pipeline with a
    forced value): this is a durable, queryable record of "an analyst
    reviewed X and corrected it to Y", for audit trail and as a foundation
    for future training-data curation. It does not automatically retrain
    anything -- that's an honest, documented limitation.
    """
    analysis = storage_db.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(404, f"No stored analysis found for analysis_id={analysis_id}")
    original = next((p for p in analysis.get("parameters", []) if p["name"] == req.parameter_name), None)
    fb_id = storage_db.save_feedback(
        analysis_id, req.parameter_name, corrected_value=req.corrected_value,
        original_value=original["value"] if original else None,
        original_status=original["status"] if original else None,
        note=req.note,
    )
    return {"feedback_id": fb_id}


@app.get("/analyses/{analysis_id}/feedback")
def get_feedback(analysis_id: str):
    return {"feedback": storage_db.list_feedback(analysis_id)}


# --- Waterfall / signal-region annotations ---------------------------------

@app.post("/analyses/{analysis_id}/annotations")
def add_annotation(analysis_id: str, req: AnnotationRequest):
    analysis = storage_db.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(404, f"No stored analysis found for analysis_id={analysis_id}")
    ann_id = storage_db.save_annotation(
        analysis_id, start_s=req.start_s, end_s=req.end_s, freq_hz=req.freq_hz,
        label=req.label, note=req.note,
    )
    return {"annotation_id": ann_id}


@app.get("/analyses/{analysis_id}/annotations")
def get_annotations(analysis_id: str):
    return {"annotations": storage_db.list_annotations(analysis_id)}


@app.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: int):
    deleted = storage_db.delete_annotation(annotation_id)
    if not deleted:
        raise HTTPException(404, f"No annotation found with id={annotation_id}")
    return {"deleted": True}
