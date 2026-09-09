import json

import numpy as np
import pytest

from rfplatform.io.formats import (
    MissingSigMFMetadataError, load_raw_iq, load_recording, load_wav, parse_sample_format,
)


# --- parse_sample_format: canonical SigMF strings ---------------------------

@pytest.mark.parametrize("datatype", [
    "cf32_le", "cf64_le", "ci8", "ci16_le", "ci32_le", "cu8", "cu16_le", "cu32_le",
    "rf32_le", "rf64_le", "ri8", "ri16_le", "ru8", "ru16_le",
])
def test_parse_sample_format_accepts_full_sigmf_vocabulary(datatype):
    spec = parse_sample_format(datatype)
    assert spec.canonical == datatype
    assert spec.is_complex == datatype.startswith("c")


@pytest.mark.parametrize("legacy,canonical", [
    ("cf32", "cf32_le"), ("cs16", "ci16_le"), ("cs8", "ci8"), ("cu8", "cu8"),
    ("s16", "ri16_le"), ("u8", "ru8"), ("f32", "rf32_le"),
])
def test_parse_sample_format_legacy_aliases_map_to_canonical(legacy, canonical):
    assert parse_sample_format(legacy).canonical == canonical


def test_parse_sample_format_rejects_garbage():
    with pytest.raises(ValueError):
        parse_sample_format("not_a_real_format")


def test_parse_sample_format_big_endian():
    spec_le = parse_sample_format("ci16_le")
    spec_be = parse_sample_format("ci16_be")
    assert spec_le.component_dtype.byteorder in ("<", "=")  # native is LE on x86/most CI runners
    assert spec_be.component_dtype.byteorder == ">"


# --- byte-level conversion correctness across formats -----------------------

def test_ci16_le_conversion_exact(tmp_path):
    rng = np.random.default_rng(1)
    i = rng.integers(-32768, 32767, 200, dtype=np.int16)
    q = rng.integers(-32768, 32767, 200, dtype=np.int16)
    interleaved = np.empty(400, dtype=np.int16)
    interleaved[0::2], interleaved[1::2] = i, q

    path = tmp_path / "test.ci16"
    interleaved.tofile(path)
    handle = load_raw_iq(path, fmt="ci16_le", sample_rate_hz=1000.0)

    expected = (i.astype(np.float32) / 32768.0) + 1j * (q.astype(np.float32) / 32768.0)
    np.testing.assert_allclose(handle.samples, expected, atol=1e-6)


def test_cu8_offset_binary_conversion(tmp_path):
    i = np.array([0, 128, 255], dtype=np.uint8)
    q = np.array([255, 0, 128], dtype=np.uint8)
    interleaved = np.empty(6, dtype=np.uint8)
    interleaved[0::2], interleaved[1::2] = i, q

    path = tmp_path / "test.cu8"
    interleaved.tofile(path)
    handle = load_raw_iq(path, fmt="cu8", sample_rate_hz=1000.0)

    expected_i = (i.astype(np.float32) - 128) / 128
    expected_q = (q.astype(np.float32) - 128) / 128
    np.testing.assert_allclose(handle.samples.real, expected_i, atol=1e-6)
    np.testing.assert_allclose(handle.samples.imag, expected_q, atol=1e-6)


# --- SigMF sidecar resolution -------------------------------------------------

def test_sigmf_sidecar_resolves_datatype_rate_and_frequency(tmp_path):
    data_path = tmp_path / "recording.sigmf-data"
    meta_path = tmp_path / "recording.sigmf-meta"
    iq = np.zeros(1000, dtype=np.complex64)
    iq.tofile(data_path)
    meta = {
        "global": {"core:datatype": "cf32_le", "core:sample_rate": 2_000_000.0, "core:version": "1.0.0"},
        "captures": [{"core:sample_start": 0, "core:frequency": 915_000_000.0}],
        "annotations": [],
    }
    meta_path.write_text(json.dumps(meta))

    handle = load_recording(str(data_path))
    assert handle.source_format == "cf32_le"
    assert handle.sample_rate_hz == 2_000_000.0
    assert handle.center_freq_hz == 915_000_000.0
    assert handle.metadata_status == "sidecar_sigmf"
    assert handle.sigmf_meta_path == meta_path


def test_sigmf_sidecar_pairing_with_upload_style_filename(tmp_path):
    """Mirrors the API's upload-time naming: {file_id}__{stem}.sigmf-data /
    .sigmf-meta -- the sidecar lookup must still work with this prefix."""
    data_path = tmp_path / "abc123__bpsk_rect_20sps.sigmf-data"
    meta_path = tmp_path / "abc123__bpsk_rect_20sps.sigmf-meta"
    iq = np.zeros(100_000, dtype=np.complex64)
    iq.tofile(data_path)
    meta = {
        "global": {"core:datatype": "cf32_le", "core:sample_rate": 1_000_000.0, "core:version": "1.0.0"},
        "captures": [{"core:sample_start": 0, "core:frequency": 100_000_000.0}],
        "annotations": [],
    }
    meta_path.write_text(json.dumps(meta))

    handle = load_recording(str(data_path))
    assert handle.sample_rate_hz == 1_000_000.0
    assert handle.center_freq_hz == 100_000_000.0
    assert handle.num_samples == 100_000
    assert handle.duration_s() == pytest.approx(0.1)


def test_sigmf_data_without_meta_and_without_fmt_raises_clear_error(tmp_path):
    data_path = tmp_path / "orphan.sigmf-data"
    np.zeros(100, dtype=np.complex64).tofile(data_path)

    with pytest.raises(MissingSigMFMetadataError):
        load_recording(str(data_path))


def test_sigmf_data_with_explicit_fmt_override_works_without_meta(tmp_path):
    """An analyst-supplied format override should let ingestion proceed
    even with no sidecar -- only the ABSENCE of any format source is an
    error, not the absence of the sidecar specifically."""
    data_path = tmp_path / "orphan2.sigmf-data"
    iq = np.ones(50, dtype=np.complex64)
    iq.tofile(data_path)

    handle = load_raw_iq(data_path, fmt="cf32_le", sample_rate_hz=500_000.0)
    assert handle.sample_rate_hz == 500_000.0
    assert handle.num_samples == 50


def test_sigmf_partial_metadata_missing_sample_rate_reports_status_correctly(tmp_path):
    """A sidecar that exists but omits core:sample_rate: format resolves
    fine (bytes are decodable), but sample_rate_hz stays honestly None."""
    data_path = tmp_path / "partial.sigmf-data"
    meta_path = tmp_path / "partial.sigmf-meta"
    np.zeros(100, dtype=np.complex64).tofile(data_path)
    meta = {"global": {"core:datatype": "cf32_le", "core:version": "1.0.0"}, "captures": [], "annotations": []}
    meta_path.write_text(json.dumps(meta))

    handle = load_recording(str(data_path))
    assert handle.sample_rate_hz is None
    assert handle.metadata_status == "sidecar_sigmf_partial"
    assert handle.source_format == "cf32_le"  # datatype still resolved correctly


def test_non_sigmf_extension_never_raises_missing_metadata_error(tmp_path):
    """Legacy .cf32/.iq files without any sidecar should keep working via
    the extension-guess fallback -- MissingSigMFMetadataError is specific
    to .sigmf-data, which has no other self-describing convention."""
    path = tmp_path / "plain.cf32"
    np.zeros(100, dtype=np.complex64).tofile(path)
    handle = load_recording(str(path))  # should not raise
    assert handle.source_format == "cf32_le"
    assert handle.sample_rate_hz is None  # honestly unknown, but no exception


# --- WAV ingestion unaffected -------------------------------------------------

def test_wav_stereo_iq_still_works(tmp_path):
    import wave

    path = tmp_path / "test.wav"
    n = 1000
    rng = np.random.default_rng(2)
    i = (rng.standard_normal(n) * 3000).astype(np.int16)
    q = (rng.standard_normal(n) * 3000).astype(np.int16)
    interleaved = np.empty(n * 2, dtype=np.int16)
    interleaved[0::2], interleaved[1::2] = i, q

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(interleaved.tobytes())

    handle = load_wav(path)
    assert handle.sample_rate_hz == 48000.0
    assert handle.metadata_status == "trusted_metadata"
    assert handle.num_samples == n
