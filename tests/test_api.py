import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from rfplatform.api.main import app
<<<<<<< HEAD
from rfplatform.storage import db as storage_db
=======
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
from rfplatform.synth.generator import SynthConfig, generate

client = TestClient(app)


<<<<<<< HEAD
@pytest.fixture(autouse=True)
def isolated_history_db(tmp_path, monkeypatch):
    """Every test gets its own fresh SQLite file for analysis history --
    without this, tests would share (and pollute) the real default
    DB_PATH, making history/comparison/similarity tests order-dependent
    and flaky."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test_history.db")


=======
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
def _cf32_bytes(cfg: SynthConfig) -> bytes:
    result = generate(cfg)
    buf = io.BytesIO()
    buf.write(result.iq.astype(np.complex64).tobytes())
    buf.seek(0)
    return buf.read()


def _upload_standalone(filename: str, data: bytes) -> str:
    r = client.post("/upload", files=[("files", (filename, data, "application/octet-stream"))])
    assert r.status_code == 200, r.text
    uploads = r.json()["uploads"]
    assert len(uploads) == 1
    return uploads[0]["file_id"]


def _sigmf_meta_bytes(sample_rate_hz: float, center_freq_hz: float | None = None,
                       datatype: str = "cf32_le") -> bytes:
    meta = {
        "global": {"core:datatype": datatype, "core:sample_rate": sample_rate_hz, "core:version": "1.0.0"},
        "captures": [{"core:sample_start": 0}],
        "annotations": [],
    }
    if center_freq_hz is not None:
        meta["captures"][0]["core:frequency"] = center_freq_hz
    return json.dumps(meta).encode()


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_rejects_disallowed_extension():
    r = client.post("/upload", files=[("files", ("malware.exe", b"not a signal", "application/octet-stream"))])
    assert r.status_code == 400


def test_upload_analyze_delete_round_trip():
    cfg = SynthConfig(modulation="qpsk", n_symbols=4000, snr_db=20, seed=3, sample_rate_hz=200_000)
    data = _cf32_bytes(cfg)
    file_id = _upload_standalone("signal.cf32", data)

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
    file_id = _upload_standalone("sig.cf32", data)

    r = client.post("/spectrogram", json={"file_id": file_id, "sample_rate_hz": 200_000,
                                           "time_bins": 100, "freq_bins": 100})
    assert r.status_code == 200
    body = r.json()
    assert len(body["freqs_hz"]) <= 100
    assert len(body["power_db"]) == len(body["times_s"])
    assert body["max_db"] > body["min_db"]
    assert body["is_absolute_frequency"] is False  # no center frequency was provided

    client.delete(f"/upload/{file_id}")


def test_analyze_with_analyst_override():
    cfg = SynthConfig(modulation="bpsk", n_symbols=3000, snr_db=15, seed=9, sample_rate_hz=200_000)
    data = _cf32_bytes(cfg)
    file_id = _upload_standalone("sig.cf32", data)

    r = client.post("/analyze", json={
        "file_id": file_id, "sample_rate_hz": 200_000, "overrides": {"modulation": "qpsk"},
    })
    body = r.json()
    mod = next(p for p in body["parameters"] if p["name"] == "modulation")
    assert mod["value"] == "qpsk"
    assert mod["status"] == "DETECTED"
    assert body["manifest"]["parameters_used"]["modulation"] == "qpsk"

    client.delete(f"/upload/{file_id}")


# --- SigMF-specific tests ----------------------------------------------------

def test_sigmf_pair_uploaded_together_is_recognized_and_analyzed_correctly():
    """The exact scenario from the task: bpsk_rect_20sps.sigmf-data +
    .sigmf-meta uploaded together, auto-paired by filename, metadata used
    throughout ingestion/analysis/spectrogram."""
    sample_rate_hz = 1_000_000.0
    center_freq_hz = 100_000_000.0
    cfg = SynthConfig(modulation="bpsk", n_symbols=25_000, snr_db=20, seed=11,
                       sample_rate_hz=sample_rate_hz, samples_per_symbol=4)
    data_bytes = _cf32_bytes(cfg)
    meta_bytes = _sigmf_meta_bytes(sample_rate_hz, center_freq_hz)

    r = client.post("/upload", files=[
        ("files", ("bpsk_rect_20sps.sigmf-data", data_bytes, "application/octet-stream")),
        ("files", ("bpsk_rect_20sps.sigmf-meta", meta_bytes, "application/json")),
    ])
    assert r.status_code == 200, r.text
    uploads = r.json()["uploads"]
    assert len(uploads) == 1  # one recording, not two files
    upload = uploads[0]
    assert upload["kind"] == "sigmf"
    assert upload["sigmf_pair_complete"] is True
    file_id = upload["file_id"]

    r_analyze = client.post("/analyze", json={"file_id": file_id})
    assert r_analyze.status_code == 200, r_analyze.text
    body = r_analyze.json()

    assert body["recording_summary"]["sample_rate_hz"] == sample_rate_hz
    assert body["recording_summary"]["center_freq_hz"] == center_freq_hz
    assert body["recording_summary"]["source_format"] == "cf32_le"
    assert body["recording_summary"]["num_samples"] == len(data_bytes) // 8  # complex64 = 8 bytes/sample
    assert abs(body["recording_summary"]["duration_s"] - len(data_bytes) / 8 / sample_rate_hz) < 1e-9
    assert body["recording_summary"]["metadata_status"] == "sidecar_sigmf"

    sr_param = next(p for p in body["parameters"] if p["name"] == "sample_rate_hz")
    assert sr_param["status"] == "DETECTED"
    assert sr_param["value"] == sample_rate_hz
    assert sr_param["evidence"][0]["source"] == "sigmf_metadata"

    cf_param = next(p for p in body["parameters"] if p["name"] == "center_frequency_hz")
    assert cf_param["status"] == "DETECTED"
    assert cf_param["value"] == center_freq_hz

    mod_param = next(p for p in body["parameters"] if p["name"] == "modulation")
    assert mod_param["value"] == "bpsk"

    # spectrogram should also honor the metadata and report an absolute frequency axis
    r_spec = client.post("/spectrogram", json={"file_id": file_id})
    assert r_spec.status_code == 200
    spec = r_spec.json()
    assert spec["is_absolute_frequency"] is True
    assert spec["center_freq_hz"] == center_freq_hz
    assert spec["sample_rate_hz"] == sample_rate_hz
    # frequencies should be centered around 100 MHz, not baseband 0
    assert min(spec["freqs_hz"]) > 90_000_000

    client.delete(f"/upload/{file_id}")


def test_exact_task_scenario_datatype_rate_samples_duration_center_freq():
    """Explicit check of the exact numbers given in the task description."""
    n_samples = 100_000
    sample_rate_hz = 1_000_000.0
    center_freq_hz = 100_000_000.0

    rng = np.random.default_rng(0)
    iq = (rng.standard_normal(n_samples) + 1j * rng.standard_normal(n_samples)).astype(np.complex64)
    data_bytes = iq.tobytes()
    meta_bytes = _sigmf_meta_bytes(sample_rate_hz, center_freq_hz, datatype="cf32_le")

    r = client.post("/upload", files=[
        ("files", ("bpsk_rect_20sps.sigmf-data", data_bytes, "application/octet-stream")),
        ("files", ("bpsk_rect_20sps.sigmf-meta", meta_bytes, "application/json")),
    ])
    file_id = r.json()["uploads"][0]["file_id"]

    r_analyze = client.post("/analyze", json={"file_id": file_id})
    summary = r_analyze.json()["recording_summary"]
    assert summary["source_format"] == "cf32_le"
    assert summary["sample_rate_hz"] == 1_000_000.0
    assert summary["num_samples"] == 100_000
    assert summary["duration_s"] == pytest.approx(0.1)
    assert summary["center_freq_hz"] == 100_000_000.0

    client.delete(f"/upload/{file_id}")


def test_sigmf_data_without_meta_and_without_override_gives_clear_400_not_500_or_wrong_guess():
    """Uploading an orphan .sigmf-data (no accompanying .sigmf-meta, ever)
    and analyzing without an explicit fmt must fail loudly and clearly --
    never silently guess cf32."""
    iq = np.zeros(5000, dtype=np.complex64)
    file_id = _upload_standalone("orphan.sigmf-data", iq.tobytes())

    r = client.post("/analyze", json={"file_id": file_id})
    assert r.status_code == 400
    assert "sigmf" in r.json()["detail"].lower() or "metadata" in r.json()["detail"].lower()

    client.delete(f"/upload/{file_id}")


def test_meta_uploaded_alone_without_data_is_rejected():
    meta_bytes = _sigmf_meta_bytes(1_000_000.0)
    r = client.post("/upload", files=[("files", ("orphan2.sigmf-meta", meta_bytes, "application/json"))])
    assert r.status_code == 400


def test_sigmf_pair_uploaded_in_two_separate_requests_still_pairs():
    sample_rate_hz = 500_000.0
    cfg = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=4, sample_rate_hz=sample_rate_hz)
    data_bytes = _cf32_bytes(cfg)
    meta_bytes = _sigmf_meta_bytes(sample_rate_hz)

    r1 = client.post("/upload", files=[("files", ("split_test.sigmf-data", data_bytes, "application/octet-stream"))])
    file_id_1 = r1.json()["uploads"][0]["file_id"]
    assert r1.json()["uploads"][0]["sigmf_pair_complete"] is False

    r2 = client.post("/upload", files=[("files", ("split_test.sigmf-meta", meta_bytes, "application/json"))])
    file_id_2 = r2.json()["uploads"][0]["file_id"]
    assert r2.json()["uploads"][0]["sigmf_pair_complete"] is True

    # both uploads should resolve to the SAME recording/file_id
    assert file_id_1 == file_id_2

    r_analyze = client.post("/analyze", json={"file_id": file_id_2})
    assert r_analyze.status_code == 200
    assert r_analyze.json()["recording_summary"]["sample_rate_hz"] == sample_rate_hz

    client.delete(f"/upload/{file_id_2}")


def test_missing_sample_rate_skips_frequency_stages_without_fabricating_a_rate():
    """A raw .cf32 file with no sidecar and no override -- sample_rate_hz
    must be reported as UNKNOWN, and no frequency-dependent stage should
    silently run against a fabricated placeholder rate."""
    iq = np.random.default_rng(1).standard_normal(5000).astype(np.complex64)
    file_id = _upload_standalone("unknown_rate.cf32", iq.tobytes())

    r = client.post("/analyze", json={"file_id": file_id})
    assert r.status_code == 200
    body = r.json()

    sr_param = next(p for p in body["parameters"] if p["name"] == "sample_rate_hz")
    assert sr_param["status"] == "UNKNOWN"
    assert sr_param["value"] is None

    skipped = {s["name"] for s in body["stages"] if s["status"] == "skipped"}
    assert "noise_estimation" in skipped
    assert "demodulation_symbol_sync" in skipped
    assert any("sample rate" in w.lower() for w in body["manifest"]["warnings"])

    client.delete(f"/upload/{file_id}")


def test_spectrogram_with_unknown_sample_rate_returns_400_not_fake_1hz():
    iq = np.random.default_rng(2).standard_normal(5000).astype(np.complex64)
    file_id = _upload_standalone("unknown_rate2.cf32", iq.tobytes())

    r = client.post("/spectrogram", json={"file_id": file_id})
    assert r.status_code == 400
    assert "sample rate" in r.json()["detail"].lower()

    client.delete(f"/upload/{file_id}")


def test_sample_rate_override_provides_full_analysis_and_correct_provenance():
    iq = np.random.default_rng(3).standard_normal(5000).astype(np.complex64)
    file_id = _upload_standalone("override_rate.cf32", iq.tobytes())

    r = client.post("/analyze", json={"file_id": file_id, "overrides": {"sample_rate_hz": 250_000.0}})
    assert r.status_code == 200
    body = r.json()
    sr_param = next(p for p in body["parameters"] if p["name"] == "sample_rate_hz")
    assert sr_param["status"] == "DETECTED"
    assert sr_param["value"] == 250_000.0
    assert sr_param["evidence"][0]["source"] == "analyst_override"
    assert body["manifest"]["parameters_used"]["sample_rate_hz"] == 250_000.0

    client.delete(f"/upload/{file_id}")


# --- export endpoint tests ---------------------------------------------------

def test_export_all_formats_via_real_endpoint():
    cfg = SynthConfig(modulation="qpsk", n_symbols=5000, snr_db=20, seed=1, sample_rate_hz=200_000)
    data = _cf32_bytes(cfg)
    file_id = _upload_standalone("sig.cf32", data)

    r_analyze = client.post("/analyze", json={"file_id": file_id, "sample_rate_hz": 200_000})
    analysis = r_analyze.json()

    expected = {
        "json": ("application/json", b"{"),
        "csv": ("text/csv", b"RF Signal Analysis Report"),
        "pdf": ("application/pdf", b"%PDF"),
        "sigmf": ("application/json", b"{"),
    }
    for fmt, (content_type, magic) in expected.items():
        r = client.post("/export", json={"format": fmt, "analysis": analysis, "filename_hint": "my_recording"})
        assert r.status_code == 200, r.text
        assert content_type in r.headers["content-type"]
        assert r.content.startswith(magic)
        assert "attachment" in r.headers["content-disposition"]
        assert "my_recording" in r.headers["content-disposition"]

    client.delete(f"/upload/{file_id}")


def test_export_rejects_unknown_format():
    r = client.post("/export", json={"format": "xml", "analysis": {}})
    assert r.status_code == 400


def test_export_filename_is_sanitized():
    r = client.post("/export", json={
        "format": "json", "analysis": {}, "filename_hint": "../../etc/passwd; rm -rf",
    })
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]
    assert ".." not in disposition
    assert "/" not in disposition
<<<<<<< HEAD


# --- Analysis history / shareable reports ------------------------------------

def test_analyze_persists_to_history_and_is_retrievable():
    cfg = SynthConfig(modulation="qpsk", n_symbols=4000, snr_db=20, seed=1, sample_rate_hz=200_000)
    file_id = _upload_standalone("sig.cf32", _cf32_bytes(cfg))
    r = client.post("/analyze", json={"file_id": file_id, "sample_rate_hz": 200_000})
    analysis_id = r.json()["manifest"]["analysis_id"]

    r_get = client.get(f"/analyses/{analysis_id}")
    assert r_get.status_code == 200
    assert r_get.json()["manifest"]["analysis_id"] == analysis_id

    r_list = client.get("/analyses")
    assert r_list.status_code == 200
    ids = [a["id"] for a in r_list.json()["analyses"]]
    assert analysis_id in ids

    client.delete(f"/upload/{file_id}")


def test_get_nonexistent_analysis_404():
    r = client.get("/analyses/does-not-exist")
    assert r.status_code == 404


def test_delete_analysis_removes_from_history():
    cfg = SynthConfig(modulation="bpsk", n_symbols=3000, snr_db=20, seed=2, sample_rate_hz=200_000)
    file_id = _upload_standalone("sig.cf32", _cf32_bytes(cfg))
    r = client.post("/analyze", json={"file_id": file_id, "sample_rate_hz": 200_000})
    analysis_id = r.json()["manifest"]["analysis_id"]

    r_del = client.delete(f"/analyses/{analysis_id}")
    assert r_del.status_code == 200
    assert client.get(f"/analyses/{analysis_id}").status_code == 404

    client.delete(f"/upload/{file_id}")


def test_export_by_analysis_id_without_resending_blob():
    cfg = SynthConfig(modulation="qpsk", n_symbols=4000, snr_db=20, seed=3, sample_rate_hz=200_000)
    file_id = _upload_standalone("sig.cf32", _cf32_bytes(cfg))
    r = client.post("/analyze", json={"file_id": file_id, "sample_rate_hz": 200_000})
    analysis_id = r.json()["manifest"]["analysis_id"]

    r_export = client.post("/export", json={"format": "pdf", "analysis_id": analysis_id})
    assert r_export.status_code == 200
    assert r_export.content[:4] == b"%PDF"

    client.delete(f"/upload/{file_id}")


def test_export_requires_analysis_or_analysis_id():
    r = client.post("/export", json={"format": "json"})
    assert r.status_code == 400


# --- Signal comparison ---------------------------------------------------------

def test_compare_two_analyses_reports_changed_parameters():
    cfg_a = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=1, sample_rate_hz=200_000)
    cfg_b = SynthConfig(modulation="bpsk", n_symbols=3000, snr_db=15, seed=2, sample_rate_hz=200_000)
    id_a = _upload_standalone("a.cf32", _cf32_bytes(cfg_a))
    id_b = _upload_standalone("b.cf32", _cf32_bytes(cfg_b))
    aid_a = client.post("/analyze", json={"file_id": id_a, "sample_rate_hz": 200_000}).json()["manifest"]["analysis_id"]
    aid_b = client.post("/analyze", json={"file_id": id_b, "sample_rate_hz": 200_000}).json()["manifest"]["analysis_id"]

    r = client.get(f"/analyses/compare?a={aid_a}&b={aid_b}")
    assert r.status_code == 200
    body = r.json()
    mod_diff = next(p for p in body["parameters"] if p["name"] == "modulation")
    assert mod_diff["status"] == "changed"
    assert mod_diff["value_a"] == "qpsk"
    assert mod_diff["value_b"] == "bpsk"

    client.delete(f"/upload/{id_a}")
    client.delete(f"/upload/{id_b}")


def test_compare_route_not_shadowed_by_analysis_id_route():
    """Regression test for a real routing bug found during development:
    /analyses/compare was being matched by the /analyses/{analysis_id}
    route (registered first) instead of reaching the dedicated compare
    handler, because 'compare' is a valid string for a path parameter."""
    r = client.get("/analyses/compare?a=nonexistent1&b=nonexistent2")
    assert r.status_code == 404
    assert "nonexistent1" in r.json()["detail"]  # confirms it reached compare(), not get_analysis()


# --- Batch analysis ---------------------------------------------------------

def test_batch_analyze_multiple_files():
    cfg_a = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=1, sample_rate_hz=200_000)
    cfg_b = SynthConfig(modulation="bpsk", n_symbols=3000, snr_db=20, seed=2, sample_rate_hz=200_000)
    id_a = _upload_standalone("a.cf32", _cf32_bytes(cfg_a))
    id_b = _upload_standalone("b.cf32", _cf32_bytes(cfg_b))

    r = client.post("/batch/analyze", json={"file_ids": [id_a, id_b], "sample_rate_hz": 200_000})
    assert r.status_code == 200
    body = r.json()
    assert body["num_ok"] == 2
    assert body["num_failed"] == 0
    mods = {entry["modulation"] for entry in body["results"]}
    assert mods == {"qpsk", "bpsk"}

    # both should now be in history
    r_list = client.get("/analyses")
    ids_in_history = {a["id"] for a in r_list.json()["analyses"]}
    for entry in body["results"]:
        assert entry["analysis_id"] in ids_in_history

    client.delete(f"/upload/{id_a}")
    client.delete(f"/upload/{id_b}")


def test_batch_analyze_partial_failure_does_not_abort_whole_batch():
    cfg = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=1, sample_rate_hz=200_000)
    good_id = _upload_standalone("good.cf32", _cf32_bytes(cfg))

    r = client.post("/batch/analyze", json={"file_ids": [good_id, "nonexistent-file-id"], "sample_rate_hz": 200_000})
    assert r.status_code == 200
    body = r.json()
    assert body["num_ok"] == 1
    assert body["num_failed"] == 1

    client.delete(f"/upload/{good_id}")


def test_batch_analyze_rejects_oversized_batch():
    r = client.post("/batch/analyze", json={"file_ids": [f"id{i}" for i in range(25)]})
    assert r.status_code == 400


def test_batch_analyze_rejects_empty_batch():
    r = client.post("/batch/analyze", json={"file_ids": []})
    assert r.status_code == 400


# --- Analyst feedback ---------------------------------------------------------

def test_submit_and_get_feedback():
    cfg = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=1, sample_rate_hz=200_000)
    file_id = _upload_standalone("sig.cf32", _cf32_bytes(cfg))
    analysis_id = client.post("/analyze", json={"file_id": file_id, "sample_rate_hz": 200_000}).json()["manifest"]["analysis_id"]

    r = client.post(f"/analyses/{analysis_id}/feedback", json={
        "parameter_name": "modulation", "corrected_value": "8psk", "note": "Reviewed constellation manually",
    })
    assert r.status_code == 200
    assert r.json()["feedback_id"] > 0

    r_get = client.get(f"/analyses/{analysis_id}/feedback")
    feedback = r_get.json()["feedback"]
    assert len(feedback) == 1
    assert feedback[0]["corrected_value"] == "8psk"
    assert feedback[0]["original_value"] == "qpsk"  # captured automatically from the stored analysis

    client.delete(f"/upload/{file_id}")


def test_feedback_on_nonexistent_analysis_404():
    r = client.post("/analyses/does-not-exist/feedback", json={"parameter_name": "modulation", "corrected_value": "bpsk"})
    assert r.status_code == 404


# --- Waterfall annotations ---------------------------------------------------

def test_add_list_delete_annotation():
    cfg = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=1, sample_rate_hz=200_000)
    file_id = _upload_standalone("sig.cf32", _cf32_bytes(cfg))
    analysis_id = client.post("/analyze", json={"file_id": file_id, "sample_rate_hz": 200_000}).json()["manifest"]["analysis_id"]

    r = client.post(f"/analyses/{analysis_id}/annotations", json={
        "start_s": 0.01, "end_s": 0.02, "freq_hz": 915_000_000.0, "label": "Sync burst", "note": "Possible preamble",
    })
    assert r.status_code == 200
    ann_id = r.json()["annotation_id"]

    r_list = client.get(f"/analyses/{analysis_id}/annotations")
    annotations = r_list.json()["annotations"]
    assert len(annotations) == 1
    assert annotations[0]["label"] == "Sync burst"

    r_del = client.delete(f"/annotations/{ann_id}")
    assert r_del.status_code == 200
    assert client.get(f"/analyses/{analysis_id}/annotations").json()["annotations"] == []

    client.delete(f"/upload/{file_id}")


def test_annotation_on_nonexistent_analysis_404():
    r = client.post("/analyses/does-not-exist/annotations", json={"start_s": 0.0})
    assert r.status_code == 404


# --- Fingerprint similarity search --------------------------------------------

def test_similar_signals_finds_matching_modulation_across_analyses():
    cfg_a = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=1, sample_rate_hz=200_000)
    cfg_b = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=22, seed=2, sample_rate_hz=200_000)
    cfg_c = SynthConfig(modulation="64qam", n_symbols=3000, snr_db=20, seed=3, sample_rate_hz=200_000)

    id_a = _upload_standalone("a.cf32", _cf32_bytes(cfg_a))
    id_b = _upload_standalone("b.cf32", _cf32_bytes(cfg_b))
    id_c = _upload_standalone("c.cf32", _cf32_bytes(cfg_c))
    aid_a = client.post("/analyze", json={"file_id": id_a, "sample_rate_hz": 200_000}).json()["manifest"]["analysis_id"]
    aid_b = client.post("/analyze", json={"file_id": id_b, "sample_rate_hz": 200_000}).json()["manifest"]["analysis_id"]
    aid_c = client.post("/analyze", json={"file_id": id_c, "sample_rate_hz": 200_000}).json()["manifest"]["analysis_id"]

    r = client.get(f"/analyses/{aid_a}/similar?signal_index=0&top_k=2")
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 2
    assert results[0]["analysis_id"] == aid_b  # the other QPSK signal ranks closer than the 64QAM one

    for i in (id_a, id_b, id_c):
        client.delete(f"/upload/{i}")


def test_similar_signals_on_nonexistent_analysis_404():
    r = client.get("/analyses/does-not-exist/similar")
    assert r.status_code == 404
=======
>>>>>>> a3c4a362ce8c34e33e815450bd7bf44d268ac5c2
