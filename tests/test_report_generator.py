import io
import json

import pypdf
import pytest

from rfplatform.pipeline.stages import run_pipeline
from rfplatform.report import generator as report
from rfplatform.synth.generator import SynthConfig, generate, save_sigmf


@pytest.fixture
def analyzed_result(tmp_path):
    cfg = SynthConfig(modulation="qpsk", n_symbols=6000, snr_db=20, seed=1,
                       sample_rate_hz=200_000.0, samples_per_symbol=8)
    synth = generate(cfg)
    path = tmp_path / "test.sigmf-data"
    save_sigmf(synth, str(path), center_freq_hz=915_000_000.0)
    analysis = run_pipeline(str(path))
    return analysis.as_dict()


def test_json_export_round_trips_exactly(analyzed_result):
    raw = report.to_json_bytes(analyzed_result)
    parsed = json.loads(raw)
    # JSON has no tuple type, so detected_regions' tuples legitimately
    # become lists after a round trip -- normalize the original the same
    # way before comparing, rather than asserting exact Python-type identity.
    normalized_original = json.loads(json.dumps(analyzed_result))
    assert parsed == normalized_original


def test_csv_export_contains_key_sections_and_values(analyzed_result):
    raw = report.to_csv_bytes(analyzed_result).decode()
    assert "Recording Summary" in raw
    assert "Parameters" in raw
    assert "qpsk" in raw
    assert "sample_rate_hz" in raw
    assert "200000" in raw


def test_csv_export_is_valid_csv(analyzed_result):
    import csv as csv_module

    raw = report.to_csv_bytes(analyzed_result).decode()
    rows = list(csv_module.reader(io.StringIO(raw)))
    assert len(rows) > 5
    # the parameters header row should be present with the expected columns
    assert ["name", "value", "unit", "status", "confidence", "evidence_summary", "alternatives"] in rows


def test_sigmf_meta_export_preserves_recording_metadata(analyzed_result):
    meta = report.to_sigmf_meta(analyzed_result)
    assert meta["global"]["core:datatype"] == "cf32_le"
    assert meta["global"]["core:sample_rate"] == 200_000.0
    assert meta["captures"][0]["core:frequency"] == 915_000_000.0


def test_sigmf_meta_export_annotations_carry_findings(analyzed_result):
    meta = report.to_sigmf_meta(analyzed_result)
    assert len(meta["annotations"]) >= 1
    ann = meta["annotations"][0]
    assert "core:sample_start" in ann
    assert "core:sample_count" in ann
    assert ann["rfplatform:parameters"]["modulation"]["value"] == "qpsk"
    assert ann["rfplatform:demodulation"]["modulation"] == "qpsk"


def test_sigmf_meta_export_is_valid_json_serializable(analyzed_result):
    meta = report.to_sigmf_meta(analyzed_result)
    # must round-trip through JSON cleanly to actually be a valid .sigmf-meta file
    reparsed = json.loads(json.dumps(meta))
    assert reparsed == meta


def test_pdf_export_is_structurally_valid(analyzed_result):
    pdf_bytes = report.to_pdf_bytes(analyzed_result)
    assert pdf_bytes[:4] == b"%PDF"
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1


def test_pdf_export_contains_real_analysis_values_not_placeholders(analyzed_result):
    """The point of this test: confirm the PDF contains the ACTUAL computed
    values from this specific analysis, not boilerplate/placeholder text."""
    pdf_bytes = report.to_pdf_bytes(analyzed_result)
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(p.extract_text() for p in reader.pages)

    assert "qpsk" in text.lower()
    assert "DETECTED" in text
    assert "sigmf_metadata" in text
    assert "915000000" in text  # the actual center frequency value
    assert "Reproducibility" in text
    assert analyzed_result["manifest"]["analysis_id"] in text


def test_pdf_export_handles_missing_optional_sections_gracefully(tmp_path):
    """A recording with unknown sample rate produces a result with no
    demod/FEC/bitstream sections -- the PDF generator must skip those
    sections cleanly rather than crashing on missing keys."""
    import numpy as np

    iq = np.random.default_rng(1).standard_normal(5000).astype(np.complex64)
    path = tmp_path / "unknown_rate.cf32"
    iq.tofile(path)
    analysis = run_pipeline(str(path))
    result_dict = analysis.as_dict()

    assert result_dict["demod_result"] is None  # confirms this test exercises the gap

    pdf_bytes = report.to_pdf_bytes(result_dict)
    assert pdf_bytes[:4] == b"%PDF"
    csv_bytes = report.to_csv_bytes(result_dict)
    assert b"Parameters" in csv_bytes
