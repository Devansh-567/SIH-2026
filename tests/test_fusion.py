from rfplatform.models.schema import Evidence, Parameter, Status
from rfplatform.pipeline.fusion import fuse_modulation


def _param(value, confidence, status=Status.INFERRED):
    return Parameter(name="modulation", value=value, status=status, confidence=confidence,
                      evidence=[Evidence(source="test", description="synthetic test evidence")])


def test_fusion_agreement_boosts_confidence():
    dsp = _param("qpsk", 0.7)
    ml = _param("qpsk", 0.8)
    fused = fuse_modulation(dsp, ml)
    assert fused.value == "qpsk"
    assert fused.confidence > max(dsp.confidence, ml.confidence)
    assert fused.status == Status.INFERRED


def test_fusion_disagreement_surfaces_both_and_penalizes_confidence():
    dsp = _param("fsk", 0.8)
    ml = _param("gfsk", 0.6)
    fused = fuse_modulation(dsp, ml)
    assert fused.value == "fsk"  # higher-confidence source wins as primary
    assert fused.confidence < dsp.confidence  # penalized for disagreement
    alt_values = [v for v, c in fused.alternatives]
    assert "gfsk" in alt_values  # the disagreeing hypothesis must not be discarded


def test_fusion_single_source_dsp_only_still_works():
    dsp = _param("bpsk", 0.9)
    fused = fuse_modulation(dsp, None)
    assert fused.value == "bpsk"
    assert fused.confidence == dsp.confidence
    assert any("single_source" in e.source for e in fused.evidence)


def test_fusion_low_confidence_reports_unknown():
    dsp = _param("64qam", 0.2)
    fused = fuse_modulation(dsp, None)
    assert fused.status == Status.UNKNOWN
    assert fused.value is None


def test_fusion_never_silently_drops_disagreeing_evidence():
    """Core honesty requirement: disagreement must be visible in the evidence
    trail, not swallowed."""
    dsp = _param("qam", 0.5)
    ml = _param("psk", 0.5)
    fused = fuse_modulation(dsp, ml)
    descriptions = " ".join(e.description for e in fused.evidence)
    assert "disagree" in descriptions.lower()
