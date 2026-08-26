import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

from rfplatform.api.main import app
from rfplatform.synth.generator import SynthConfig, generate

client = TestClient(app)


def _cf32_bytes(cfg: SynthConfig) -> bytes:
    result = generate(cfg)
    buf = io.BytesIO()
    buf.write(result.iq.astype(np.complex64).tobytes())
    buf.seek(0)
    return buf.read()


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_rejects_disallowed_extension():
    r = client.post("/upload", files={"file": ("malware.exe", b"not a signal", "application/octet-stream")})
    assert r.status_code == 400


def test_upload_analyze_delete_round_trip():
    cfg = SynthConfig(modulation="qpsk", n_symbols=4000, snr_db=20, seed=3, sample_rate_hz=200_000)
    data = _cf32_bytes(cfg)

    r_upload = client.post("/upload", files={"file": ("signal.cf32", data, "application/octet-stream")})
    assert r_upload.status_code == 200
    file_id = r_upload.json()["file_id"]

    r_analyze = client.post("/analyze", json={"file_id": file_id, "sample_rate_hz": 200_000})
    assert r_analyze.status_code == 200
    body = r_analyze.json()

    mod = next(p for p in body["parameters"] if p["name"] == "modulation")
    assert mod["value"] == "qpsk"
    assert mod["status"] == "INFERRED"
    assert body["demod_result"] is not None
    assert all(s["status"] != "error" for s in body["stages"])

    r_delete = client.delete(f"/upload/{file_id}")
    assert r_delete.status_code == 200
    assert r_delete.json()["deleted"] == 1

    # analyzing again after deletion should now 404
    r_after = client.post("/analyze", json={"file_id": file_id})
    assert r_after.status_code == 404


def test_analyze_unknown_file_id_returns_404():
    r = client.post("/analyze", json={"file_id": "does-not-exist"})
    assert r.status_code == 404


def test_spectrogram_endpoint_returns_valid_grid():
    cfg = SynthConfig(modulation="qpsk", n_symbols=8000, snr_db=20, seed=2, sample_rate_hz=200_000,
                       freq_offset_hz=25_000)
    data = _cf32_bytes(cfg)
    r_upload = client.post("/upload", files={"file": ("sig.cf32", data, "application/octet-stream")})
    file_id = r_upload.json()["file_id"]

    r = client.post("/spectrogram", json={"file_id": file_id, "sample_rate_hz": 200_000,
                                           "time_bins": 100, "freq_bins": 100})
    assert r.status_code == 200
    body = r.json()
    assert len(body["freqs_hz"]) <= 100
    assert len(body["power_db"]) == len(body["times_s"])
    assert body["max_db"] > body["min_db"]

    client.delete(f"/upload/{file_id}")


def test_analyze_with_analyst_override():
    cfg = SynthConfig(modulation="bpsk", n_symbols=3000, snr_db=15, seed=9, sample_rate_hz=200_000)
    data = _cf32_bytes(cfg)
    r_upload = client.post("/upload", files={"file": ("sig.cf32", data, "application/octet-stream")})
    file_id = r_upload.json()["file_id"]

    r = client.post("/analyze", json={
        "file_id": file_id, "sample_rate_hz": 200_000, "overrides": {"modulation": "qpsk"},
    })
    body = r.json()
    mod = next(p for p in body["parameters"] if p["name"] == "modulation")
    assert mod["value"] == "qpsk"
    assert mod["status"] == "DETECTED"
    assert body["manifest"]["parameters_used"]["modulation"] == "qpsk"

    client.delete(f"/upload/{file_id}")
