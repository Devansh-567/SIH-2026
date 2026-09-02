import numpy as np
import pytest
import torch

from rfplatform.ml.calibration import calibrated_probs, expected_calibration_error, fit_temperature
from rfplatform.ml.dataset import ModulationDataset, UNKNOWN_LABEL_IDX
from rfplatform.ml.model import INPUT_LENGTH, LABELS, ModulationCNN, iq_to_tensor
from rfplatform.models.schema import Status
from rfplatform.synth.generator import SUPPORTED_MODULATIONS


def test_labels_match_synth_generator_plus_unknown():
    assert LABELS[:-1] == SUPPORTED_MODULATIONS
    assert LABELS[-1] == "unknown"


def test_model_forward_pass_shape():
    model = ModulationCNN()
    x = torch.randn(4, 2, INPUT_LENGTH)
    out = model(x)
    assert out.shape == (4, len(LABELS))


def test_model_is_small_enough_for_cpu_training():
    """Sanity guard: if someone accidentally makes this model huge, CPU
    training time (and checkpoint size shipped in the repo) blows up."""
    model = ModulationCNN()
    n_params = sum(p.numel() for p in model.parameters())
    assert n_params < 500_000


def test_iq_to_tensor_pads_short_input():
    iq = (np.random.default_rng(1).standard_normal(50) + 1j * np.random.default_rng(2).standard_normal(50))
    t = iq_to_tensor(iq.astype(np.complex64))
    assert t.shape == (2, INPUT_LENGTH)


def test_iq_to_tensor_crops_long_input():
    iq = (np.random.default_rng(1).standard_normal(5000) + 1j * np.random.default_rng(2).standard_normal(5000))
    t = iq_to_tensor(iq.astype(np.complex64))
    assert t.shape == (2, INPUT_LENGTH)


def test_iq_to_tensor_normalizes_power():
    iq = (np.ones(1000) * 5.0).astype(np.complex64)  # large, constant amplitude
    t = iq_to_tensor(iq)
    power = (t ** 2).sum(dim=0).mean().item()
    assert abs(power - 1.0) < 0.1  # normalized to ~unit average power


def test_dataset_produces_correct_shapes_and_valid_labels():
    ds = ModulationDataset(epoch_size=10, seed=1)
    assert len(ds) == 10
    for i in range(10):
        x, y = ds[i]
        assert x.shape == (2, INPUT_LENGTH)
        assert 0 <= y < len(LABELS)


def test_dataset_produces_unknown_examples():
    ds = ModulationDataset(epoch_size=200, seed=2, unknown_fraction=0.5)
    labels = [ds[i][1] for i in range(50)]
    assert UNKNOWN_LABEL_IDX in labels


def test_dataset_zero_unknown_fraction_never_produces_unknown():
    ds = ModulationDataset(epoch_size=50, seed=3, unknown_fraction=0.0)
    labels = [ds[i][1] for i in range(50)]
    assert UNKNOWN_LABEL_IDX not in labels


# --- calibration --------------------------------------------------------

def test_fit_temperature_increases_for_genuinely_overconfident_predictions():
    """
    Unambiguous construction: predictions are maximally confident
    (near-100% softmax) REGARDLESS of whether they're actually correct,
    and only 70% of them are correct -- this is genuine overconfidence by
    definition (stated confidence >> actual accuracy), so temperature
    fitting must increase T to reduce NLL, unlike an earlier version of
    this test that multiplied already-accurate logits by a constant and
    incorrectly assumed that alone creates miscalibration -- it doesn't,
    if the underlying accuracy was already high enough to justify high
    confidence. Found via testing: that construction gave T=0.49 (sharper,
    not softer), which was correct behavior for genuinely well-separated
    logits, just not what the test intended to check.
    """
    torch.manual_seed(0)
    n, k = 1000, 2
    labels = torch.randint(0, k, (n,))
    correct_mask = torch.rand(n) < 0.70
    predicted = torch.where(correct_mask, labels, 1 - labels)
    logits = torch.zeros(n, k)
    logits[torch.arange(n), predicted] = 10.0  # maximally confident regardless of correctness

    ece_before = expected_calibration_error(torch.softmax(logits, dim=-1), labels)
    t = fit_temperature(logits, labels)
    ece_after = expected_calibration_error(calibrated_probs(logits, t), labels)

    assert t > 1.0
    assert ece_after < ece_before


def test_expected_calibration_error_zero_for_perfect_calibration():
    n = 1000
    torch.manual_seed(0)
    labels = torch.randint(0, 2, (n,))
    probs = torch.full((n, 2), 0.5)
    ece = expected_calibration_error(probs, labels)
    assert ece < 0.05


# --- inference (requires a trained checkpoint) ---------------------------

@pytest.fixture(scope="module")
def trained_checkpoint():
    from rfplatform.ml.inference import CHECKPOINT_PATH
    if not CHECKPOINT_PATH.exists():
        pytest.skip("No trained checkpoint present -- run `python -m rfplatform.ml.train` first")
    return CHECKPOINT_PATH


def test_classify_returns_parameter_with_full_evidence(trained_checkpoint):
    from rfplatform.ml.inference import classify
    from rfplatform.synth.generator import SynthConfig, generate

    cfg = SynthConfig(modulation="qpsk", n_symbols=1000, snr_db=20, seed=1, sample_rate_hz=200_000)
    result = generate(cfg)
    param = classify(result.iq)

    assert param.name == "modulation"
    assert param.status in (Status.INFERRED, Status.UNKNOWN)
    assert 0.0 <= param.confidence <= 1.0
    assert len(param.evidence) >= 1
    assert param.evidence[0].source == "ml:cnn_classifier_v1"
    assert len(param.alternatives) == 3  # top-3 alternatives beyond the primary


def test_classify_on_pure_noise_tends_toward_unknown(trained_checkpoint):
    from rfplatform.ml.inference import classify

    rng = np.random.default_rng(42)
    noise = (rng.standard_normal(600) + 1j * rng.standard_normal(600)).astype(np.complex64)
    param = classify(noise)
    assert param.value is None or param.status == Status.UNKNOWN


def test_classify_family_correct_at_high_snr_across_all_modulations(trained_checkpoint):
    """Not asserting perfect order accuracy (measured confusion exists
    within PSK/QAM/FSK families -- see README) but family-level correctness
    at high SNR should hold for a model that trained to >60% val accuracy."""
    from rfplatform.ml.inference import classify
    from rfplatform.synth.generator import SynthConfig, generate

    family_of = {"bpsk": "psk", "qpsk": "psk", "8psk": "psk", "16qam": "qam", "64qam": "qam",
                 "2fsk": "fsk", "4fsk": "fsk"}
    correct_family = 0
    for mod in SUPPORTED_MODULATIONS:
        cfg = SynthConfig(modulation=mod, n_symbols=1000, snr_db=20, seed=5, sample_rate_hz=200_000)
        result = generate(cfg)
        param = classify(result.iq)
        if param.value and family_of.get(param.value) == family_of[mod]:
            correct_family += 1
    assert correct_family >= 5  # allow some slack, but most families should be right


def test_pipeline_uses_real_ml_classifier_when_checkpoint_present(trained_checkpoint, tmp_path):
    from rfplatform.pipeline.stages import run_pipeline
    from rfplatform.synth.generator import SynthConfig, generate, save_sigmf

    cfg = SynthConfig(modulation="qpsk", n_symbols=5000, snr_db=20, seed=1, sample_rate_hz=200_000)
    result = generate(cfg)
    path = tmp_path / "test.sigmf-data"
    save_sigmf(result, str(path))

    analysis = run_pipeline(str(path))
    ai_stage = next(s for s in analysis.stages if s.name == "ai_classification")
    assert ai_stage.status == "ok"

    mod_param = next(p for p in analysis.parameters if p.name == "modulation")
    sources = {e.source for e in mod_param.evidence}
    assert "ml:cnn_classifier_v1" in sources
    assert any(s.startswith("dsp:") for s in sources)
