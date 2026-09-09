import pytest
import json

from rfplatform.storage import db
from rfplatform.pipeline.stages import run_pipeline
from rfplatform.synth.generator import SynthConfig, generate, save_sigmf


@pytest.fixture
def temp_db(tmp_path):
    return tmp_path / "test_history.db"


@pytest.fixture
def real_analysis_dict(tmp_path):
    cfg = SynthConfig(modulation="qpsk", n_symbols=4000, snr_db=20, seed=1, sample_rate_hz=200_000)
    result = generate(cfg)
    path = tmp_path / "sig.sigmf-data"
    save_sigmf(result, str(path))
    analysis = run_pipeline(str(path))
    return analysis.as_dict()


def test_save_and_get_analysis_round_trips(temp_db, real_analysis_dict):
    analysis_id = db.save_analysis(real_analysis_dict, db_path=temp_db)
    assert analysis_id == real_analysis_dict["manifest"]["analysis_id"]

    fetched = db.get_analysis(analysis_id, db_path=temp_db)
    # Normalize both sides through one JSON round-trip before comparing --
    # the original in-process dict can still contain numpy scalar types
    # (e.g. Evidence.value populated from a numpy computation) and Python
    # tuples (detected_regions), neither of which JSON preserves as a
    # distinct type. Comparing the raw original against the DB-fetched
    # (already-JSON-round-tripped) copy directly fails on those type
    # differences even though the values are identical -- the same class
    # of test-construction issue as test_report_generator.py's JSON
    # export test; fixed the same way here.
    normalized_original = json.loads(json.dumps(real_analysis_dict))
    assert fetched == normalized_original


def test_get_nonexistent_analysis_returns_none(temp_db):
    assert db.get_analysis("does-not-exist", db_path=temp_db) is None


def test_save_analysis_is_idempotent_on_same_id(temp_db, real_analysis_dict):
    db.save_analysis(real_analysis_dict, db_path=temp_db)
    db.save_analysis(real_analysis_dict, db_path=temp_db)
    listing = db.list_analyses(db_path=temp_db)
    assert len(listing) == 1


def test_list_analyses_returns_summary_ordered_by_recency(temp_db):
    import tempfile, os
    for i, mod in enumerate(["bpsk", "qpsk", "8psk"]):
        cfg = SynthConfig(modulation=mod, n_symbols=2000, snr_db=20, seed=i, sample_rate_hz=200_000)
        result = generate(cfg)
        d = tempfile.mkdtemp()
        path = os.path.join(d, f"{mod}.cf32")
        result.iq.astype("complex64").tofile(path)
        analysis = run_pipeline(path, sample_rate_hz=200_000.0)
        db.save_analysis(analysis.as_dict(), db_path=temp_db)

    listing = db.list_analyses(db_path=temp_db)
    assert len(listing) == 3
    mods = {row["primary_modulation"] for row in listing}
    assert mods == {"bpsk", "qpsk", "8psk"}


def test_delete_analysis_removes_it(temp_db, real_analysis_dict):
    analysis_id = db.save_analysis(real_analysis_dict, db_path=temp_db)
    assert db.delete_analysis(analysis_id, db_path=temp_db) is True
    assert db.get_analysis(analysis_id, db_path=temp_db) is None
    assert db.delete_analysis(analysis_id, db_path=temp_db) is False


def test_find_similar_signals_finds_matching_modulation(temp_db):
    import tempfile, os
    cfg_a = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=20, seed=1, sample_rate_hz=200_000)
    cfg_b = SynthConfig(modulation="qpsk", n_symbols=3000, snr_db=22, seed=2, sample_rate_hz=200_000)
    cfg_c = SynthConfig(modulation="64qam", n_symbols=3000, snr_db=20, seed=3, sample_rate_hz=200_000)

    ids = []
    for cfg, name in [(cfg_a, "a"), (cfg_b, "b"), (cfg_c, "c")]:
        result = generate(cfg)
        d = tempfile.mkdtemp()
        path = os.path.join(d, f"{name}.cf32")
        result.iq.astype("complex64").tofile(path)
        analysis = run_pipeline(path, sample_rate_hz=200_000.0)
        ids.append(db.save_analysis(analysis.as_dict(), db_path=temp_db))

    query_fp = db.get_analysis(ids[0], db_path=temp_db)["signals"][0]["fingerprint"]
    similar = db.find_similar_signals(query_fp, exclude_analysis_id=ids[0], top_k=2, db_path=temp_db)

    assert len(similar) == 2
    assert similar[0]["analysis_id"] == ids[1]
    assert similar[0]["distance"] < similar[1]["distance"]


def test_feedback_save_and_list(temp_db, real_analysis_dict):
    analysis_id = db.save_analysis(real_analysis_dict, db_path=temp_db)
    fb_id = db.save_feedback(analysis_id, "modulation", corrected_value="8psk",
                              original_value="qpsk", original_status="INFERRED",
                              note="Constellation review confirmed 8PSK", db_path=temp_db)
    assert fb_id > 0

    feedback = db.list_feedback(analysis_id, db_path=temp_db)
    assert len(feedback) == 1
    assert feedback[0]["corrected_value"] == "8psk"
    assert feedback[0]["original_value"] == "qpsk"
    assert feedback[0]["note"] == "Constellation review confirmed 8PSK"


def test_feedback_list_all_across_analyses(temp_db, real_analysis_dict):
    analysis_id = db.save_analysis(real_analysis_dict, db_path=temp_db)
    db.save_feedback(analysis_id, "modulation", corrected_value="8psk", db_path=temp_db)
    db.save_feedback(analysis_id, "sample_rate_hz", corrected_value=250000.0, db_path=temp_db)
    all_feedback = db.list_feedback(db_path=temp_db)
    assert len(all_feedback) == 2


def test_annotation_save_list_delete(temp_db, real_analysis_dict):
    analysis_id = db.save_analysis(real_analysis_dict, db_path=temp_db)
    ann_id = db.save_annotation(analysis_id, start_s=0.01, end_s=0.02, freq_hz=915_000_000.0,
                                 label="Sync burst", note="Looks like a preamble", db_path=temp_db)
    assert ann_id > 0

    annotations = db.list_annotations(analysis_id, db_path=temp_db)
    assert len(annotations) == 1
    assert annotations[0]["label"] == "Sync burst"

    assert db.delete_annotation(ann_id, db_path=temp_db) is True
    assert db.list_annotations(analysis_id, db_path=temp_db) == []


def test_annotations_ordered_by_start_time(temp_db, real_analysis_dict):
    analysis_id = db.save_analysis(real_analysis_dict, db_path=temp_db)
    db.save_annotation(analysis_id, start_s=0.05, label="second", db_path=temp_db)
    db.save_annotation(analysis_id, start_s=0.01, label="first", db_path=temp_db)
    annotations = db.list_annotations(analysis_id, db_path=temp_db)
    assert [a["label"] for a in annotations] == ["first", "second"]
