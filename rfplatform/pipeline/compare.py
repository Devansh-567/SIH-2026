"""
Signal comparison -- PART 22 differentiator ("Comparison mode: Recording A
vs Recording B"). Operates on two already-computed AnalysisResultJSON
dicts (typically fetched from storage by analysis_id), producing a
parameter-by-parameter diff rather than requiring the caller/GUI to
re-implement matching logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParameterDiff:
    name: str
    status: str          # "same" | "changed" | "only_in_a" | "only_in_b"
    value_a: object
    value_b: object
    status_a: str | None
    status_b: str | None

    def as_dict(self) -> dict:
        return {
            "name": self.name, "status": self.status,
            "value_a": self.value_a, "value_b": self.value_b,
            "status_a": self.status_a, "status_b": self.status_b,
        }


def compare_analyses(a: dict, b: dict) -> dict:
    """
    Compares two AnalysisResultJSON dicts' top-level `parameters` lists
    (the primary-signal parameters -- see pipeline/stages.py's
    backward-compatibility mirroring for multi-signal files) by name.
    Also reports the recording-level basics (sample rate, format,
    duration) side by side, since those are often exactly what an analyst
    wants to confirm are (or aren't) the same between two captures.
    """
    params_a = {p["name"]: p for p in a.get("parameters", [])}
    params_b = {p["name"]: p for p in b.get("parameters", [])}
    all_names = sorted(set(params_a) | set(params_b))

    diffs: list[ParameterDiff] = []
    for name in all_names:
        pa, pb = params_a.get(name), params_b.get(name)
        if pa is None:
            diffs.append(ParameterDiff(name, "only_in_b", None, pb["value"], None, pb["status"]))
        elif pb is None:
            diffs.append(ParameterDiff(name, "only_in_a", pa["value"], None, pa["status"], None))
        else:
            same = pa["value"] == pb["value"] and pa["status"] == pb["status"]
            diffs.append(ParameterDiff(
                name, "same" if same else "changed", pa["value"], pb["value"], pa["status"], pb["status"],
            ))

    summary_a = a.get("recording_summary", {})
    summary_b = b.get("recording_summary", {})
    recording_diff = {
        key: {"a": summary_a.get(key), "b": summary_b.get(key), "same": summary_a.get(key) == summary_b.get(key)}
        for key in sorted(set(summary_a) | set(summary_b))
    }

    n_changed = sum(1 for d in diffs if d.status != "same")
    return {
        "analysis_id_a": a.get("manifest", {}).get("analysis_id"),
        "analysis_id_b": b.get("manifest", {}).get("analysis_id"),
        "recording": recording_diff,
        "parameters": [d.as_dict() for d in diffs],
        "num_parameters_compared": len(diffs),
        "num_parameters_changed": n_changed,
    }
