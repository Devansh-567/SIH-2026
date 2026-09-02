"""
Confidence fusion engine -- PART 11 / PART 21 of the architecture report.
This is the project's central original contribution: a deterministic,
explainable combination of DSP-rule-based hypotheses and (optional) ML
classifier hypotheses, producing one fused Parameter with a full evidence
trail. When sources agree, confidence is boosted. When they disagree, BOTH
hypotheses are surfaced rather than one silently overriding the other.

MVP note: the ML classifier is not yet trained/wired in this build (see
project README "Not yet built" section) -- `fuse_modulation` already
accepts an optional ML hypothesis argument so wiring in a trained model
later requires no changes to this module's logic, only a caller change.
"""

from __future__ import annotations

from rfplatform.models.schema import Evidence, Parameter, Status

# Minimum calibrated confidence below which we report UNKNOWN rather than a guess.
CONFIDENCE_FLOOR = 0.35


def fuse_modulation(dsp_param: Parameter, ml_param: Parameter | None = None) -> Parameter:
    """
    Fuse the DSP rule-based modulation Parameter with an optional ML
    classifier Parameter. Returns a new Parameter representing the fused
    conclusion, with both sources' evidence preserved.
    """
    if ml_param is None:
        # No ML hypothesis available -- fall back to the DSP-only result,
        # but note explicitly that fusion did not occur (transparency).
        evidence = list(dsp_param.evidence) + [
            Evidence(source="fusion:single_source",
                     description="No ML classifier hypothesis available; result is DSP-only.")
        ]
        status = dsp_param.status if dsp_param.confidence >= CONFIDENCE_FLOOR else Status.UNKNOWN
        value = dsp_param.value if status != Status.UNKNOWN else None
        return Parameter(name="modulation", value=value, status=status, confidence=dsp_param.confidence,
                          alternatives=dsp_param.alternatives, evidence=evidence)

    agree = dsp_param.value == ml_param.value
    evidence = list(dsp_param.evidence) + list(ml_param.evidence)

    if agree:
        # Both independent sources agree -- boost confidence, but cap below 1.0
        # (agreement is strong evidence, not proof).
        fused_confidence = min(0.97, 1 - (1 - dsp_param.confidence) * (1 - ml_param.confidence))
        evidence.append(Evidence(
            source="fusion:agreement",
            description=f"DSP ({dsp_param.confidence:.2f}) and ML ({ml_param.confidence:.2f}) "
                        f"classifiers independently agree on '{dsp_param.value}' -> confidence boosted.",
        ))
        status = Status.INFERRED if fused_confidence >= CONFIDENCE_FLOOR else Status.UNKNOWN
        alternatives = _merge_alternatives(dsp_param.alternatives, ml_param.alternatives)
        return Parameter(name="modulation", value=dsp_param.value if status != Status.UNKNOWN else None,
                          status=status, confidence=fused_confidence, alternatives=alternatives,
                          evidence=evidence)

    # Disagreement: do NOT silently pick a winner. Surface both as
    # alternatives, and report the higher-confidence one as the primary
    # value but with confidence penalized (disagreement is itself evidence
    # of uncertainty) and status downgraded toward HYPOTHESIZED.
    evidence.append(Evidence(
        source="fusion:disagreement",
        description=f"DSP classifier says '{dsp_param.value}' ({dsp_param.confidence:.2f}); "
                    f"ML classifier says '{ml_param.value}' ({ml_param.confidence:.2f}). "
                    f"Sources disagree -- reporting both as hypotheses, confidence penalized.",
    ))
    primary, secondary = (dsp_param, ml_param) if dsp_param.confidence >= ml_param.confidence else (ml_param, dsp_param)
    penalized_confidence = primary.confidence * 0.6
    status = Status.HYPOTHESIZED if penalized_confidence >= CONFIDENCE_FLOOR else Status.UNKNOWN
    alternatives = [(secondary.value, secondary.confidence)] + list(primary.alternatives)
    return Parameter(name="modulation", value=primary.value if status != Status.UNKNOWN else None,
                      status=status, confidence=penalized_confidence, alternatives=alternatives,
                      evidence=evidence)


def _merge_alternatives(a: list[tuple], b: list[tuple]) -> list[tuple]:
    merged: dict[str, float] = {}
    for value, conf in a + b:
        merged[value] = max(merged.get(value, 0.0), conf)
    return sorted(merged.items(), key=lambda kv: -kv[1])
