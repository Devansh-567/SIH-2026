"""
Report generation -- the "Report Export" requirement from the PS (JSON,
CSV, PDF, SigMF annotations) and PART 16/21 of the architecture report.

Design choice: every export function operates on the same plain dict
structure /analyze already returns (AnalysisResultJSON on the frontend
side), rather than re-running the pipeline or maintaining server-side
state. This means an export is always "exactly what you're looking at" --
there's no separate code path that could drift from the GUI's own view of
an analysis, and the API stays stateless.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone


def to_json_bytes(result: dict) -> bytes:
    return json.dumps(result, indent=2, sort_keys=False).encode("utf-8")


def to_csv_bytes(result: dict) -> bytes:
    """
    A human-readable multi-table CSV (section headers + blank-line
    separators) rather than one flat table -- the underlying data genuinely
    has different shapes (a parameter list, a demod summary, several
    hypothesis rankings, a bitstream summary), and forcing all of it into
    one uniform row schema would either lose information or pad every row
    with mostly-empty columns.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    manifest = result.get("manifest", {})
    summary = result.get("recording_summary", {})

    writer.writerow(["RF Signal Analysis Report"])
    writer.writerow(["analysis_id", manifest.get("analysis_id", "")])
    writer.writerow(["pipeline_version", manifest.get("pipeline_version", "")])
    writer.writerow(["input_file", manifest.get("input_file", "")])
    writer.writerow([])

    writer.writerow(["Recording Summary"])
    for k, v in summary.items():
        writer.writerow([k, v])
    writer.writerow([])

    writer.writerow(["Parameters"])
    writer.writerow(["name", "value", "unit", "status", "confidence", "evidence_summary", "alternatives"])
    for p in result.get("parameters", []):
        evidence_summary = "; ".join(e.get("description", "") for e in p.get("evidence", []))
        alt_summary = "; ".join(f"{a.get('value')} ({a.get('confidence')})" for a in p.get("alternatives", []))
        writer.writerow([p.get("name"), p.get("value"), p.get("unit"), p.get("status"),
                          p.get("confidence"), evidence_summary, alt_summary])
    writer.writerow([])

    demod = result.get("demod_result")
    if demod:
        writer.writerow(["Demodulation"])
        for k, v in demod.items():
            if k == "bits_preview":
                v = "".join(str(b) for b in v)
            elif k == "notes":
                v = "; ".join(v)
            writer.writerow([k, v])
        writer.writerow([])

    fec = result.get("fec_hypotheses", {})
    if fec.get("convolutional"):
        writer.writerow(["FEC -- Convolutional Hypotheses"])
        writer.writerow(["preset", "reencode_distance_fraction"])
        for c in fec["convolutional"]:
            writer.writerow([c["preset"], c["reencode_distance_fraction"]])
        writer.writerow([])
    if fec.get("reed_solomon"):
        writer.writerow(["FEC -- Reed-Solomon Hypotheses"])
        writer.writerow(["preset", "success", "symbols_corrected", "byte_alignment", "parity_bytes"])
        for r in fec["reed_solomon"]:
            writer.writerow([r["preset"], r["success"], r["symbols_corrected"],
                              r["byte_alignment"], r["parity_bytes"]])
        writer.writerow([])

    deint = result.get("deinterleave_hypotheses", {})
    if deint.get("block"):
        writer.writerow(["De-interleaving -- Block Hypotheses"])
        writer.writerow(["rows", "cols", "structure_score"])
        for b in deint["block"]:
            writer.writerow([b["rows"], b["cols"], b["structure_score"]])
        writer.writerow([])
    if deint.get("pseudo_random_note"):
        writer.writerow(["De-interleaving -- Pseudo-random", deint["pseudo_random_note"]])
        writer.writerow([])

    bitstream = result.get("bitstream_analysis")
    if bitstream:
        writer.writerow(["Bitstream Analysis"])
        writer.writerow(["length_bits", bitstream.get("length_bits")])
        writer.writerow(["best_byte_alignment", bitstream.get("best_byte_alignment")])
        writer.writerow(["byte_alignment_confidence", bitstream.get("byte_alignment_confidence")])
        writer.writerow([])
        if bitstream.get("preamble_matches"):
            writer.writerow(["Preamble Matches"])
            writer.writerow(["name", "position", "hamming_distance"])
            for m in bitstream["preamble_matches"]:
                writer.writerow([m["name"], m["position"], m["hamming_distance"]])
            writer.writerow([])
        if bitstream.get("framing_hypotheses"):
            writer.writerow(["Framing Hypotheses"])
            writer.writerow(["frame_length_bits", "confidence"])
            for f in bitstream["framing_hypotheses"]:
                writer.writerow([f["frame_length_bits"], f["confidence"]])
            writer.writerow([])

    if manifest.get("warnings"):
        writer.writerow(["Warnings"])
        for w in manifest["warnings"]:
            writer.writerow([w])
        writer.writerow([])

    if manifest.get("parameters_used"):
        writer.writerow(["Analyst Overrides Applied"])
        for k, v in manifest["parameters_used"].items():
            writer.writerow([k, v])

    return buf.getvalue().encode("utf-8")


def to_sigmf_meta(result: dict) -> dict:
    """
    Produces a SigMF-compatible metadata document carrying this analysis's
    findings: `core:sample_rate`/`core:datatype`/`core:frequency` preserved
    from the original recording, plus one `annotations` entry per detected
    signal region, each tagged with our findings under SigMF's `rfplatform:`
    extension namespace. Can be dropped alongside the original .sigmf-data
    file as an updated .sigmf-meta, or kept standalone as a portable,
    reproducible analysis record -- directly closing the loop on this
    project's own SigMF ingestion work (PART "SigMF support" in the README).
    """
    summary = result.get("recording_summary", {})
    manifest = result.get("manifest", {})

    global_block: dict = {
        "core:version": "1.0.0",
        "rfplatform:analysis_id": manifest.get("analysis_id"),
        "rfplatform:pipeline_version": manifest.get("pipeline_version"),
    }
    if summary.get("source_format"):
        global_block["core:datatype"] = summary["source_format"]
    if summary.get("sample_rate_hz"):
        global_block["core:sample_rate"] = summary["sample_rate_hz"]

    capture: dict = {"core:sample_start": 0}
    if summary.get("center_freq_hz") is not None:
        capture["core:frequency"] = summary["center_freq_hz"]

    param_by_name = {p["name"]: p for p in result.get("parameters", [])}
    demod = result.get("demod_result")

    annotations = []
    for start, end in result.get("detected_regions", []):
        annotation: dict = {
            "core:sample_start": start,
            "core:sample_count": max(0, end - start),
            "rfplatform:parameters": {
                name: {"value": p.get("value"), "status": p.get("status"), "confidence": p.get("confidence")}
                for name, p in param_by_name.items()
            },
        }
        if demod:
            annotation["rfplatform:demodulation"] = {
                "modulation": demod.get("modulation"),
                "evm_percent": demod.get("evm_percent"),
                "lock_quality": demod.get("lock_quality"),
            }
        annotations.append(annotation)

    return {
        "global": global_block,
        "captures": [capture],
        "annotations": annotations,
    }


_STATUS_HEX = {
    "DETECTED": "#0f8f82",
    "ESTIMATED": "#1c72a8",
    "INFERRED": "#b3800a",
    "HYPOTHESIZED": "#c1601f",
    "UNKNOWN": "#6b7280",
}


def _table_style_commands(extra: list | None = None) -> list:
    from reportlab.lib import colors

    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1c2229")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    return cmds + (extra or [])


def to_pdf_bytes(result: dict) -> bytes:
    """
    A printable analyst report: recording summary, the full parameter list
    with status-colored values, an evidence appendix, demod/FEC/de-interleave/
    bitstream summaries, and a reproducibility block -- the PDF analogue of
    the GUI's own panels, so a judge or analyst can hold a physical record
    of exactly what the tool concluded and why (PART 22's "reproducibility
    report" differentiator, made concrete).
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="RF Signal Analysis Report",
                             leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("RFTitle", parent=styles["Title"], fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("RFH2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
    mono = ParagraphStyle("RFMono", parent=styles["Normal"], fontName="Courier", fontSize=7, leading=9)
    small = ParagraphStyle("RFSmall", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    body = styles["Normal"]

    elements = []
    manifest = result.get("manifest", {})
    summary = result.get("recording_summary", {})

    elements.append(Paragraph("RF Signal Analysis Report", title_style))
    elements.append(Paragraph(
        f"SIH 26147 &middot; NTRO &middot; Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        small))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Recording", h2))
    rows = [["Field", "Value"]] + [[str(k), str(v)] for k, v in summary.items()]
    t = Table(rows, colWidths=[140, 320])
    t.setStyle(TableStyle(_table_style_commands()))
    elements.append(t)

    elements.append(Paragraph("Automatic Analysis", h2))
    parameters = result.get("parameters", [])
    param_rows = [["Parameter", "Value", "Status", "Confidence"]]
    for p in parameters:
        conf = p.get("confidence") or 0
        param_rows.append([p.get("name", ""), str(p.get("value")), p.get("status", ""), f"{conf * 100:.0f}%"])
    color_cmds = []
    for i, p in enumerate(parameters, start=1):
        hexcolor = _STATUS_HEX.get(p.get("status"), "#6b7280")
        color_cmds.append(("TEXTCOLOR", (2, i), (2, i), colors.HexColor(hexcolor)))
    pt = Table(param_rows, colWidths=[150, 150, 90, 70])
    pt.setStyle(TableStyle(_table_style_commands(color_cmds)))
    elements.append(pt)

    elements.append(Paragraph("Evidence", h2))
    for p in parameters:
        if not p.get("evidence"):
            continue
        conf = p.get("confidence") or 0
        elements.append(Paragraph(
            f"<b>{p['name']}</b> = {p.get('value')} ({p.get('status')}, {conf * 100:.0f}%)", body))
        for e in p["evidence"]:
            elements.append(Paragraph(f"&bull; [{e.get('source')}] {e.get('description')}", small))
        elements.append(Spacer(1, 4))

    demod = result.get("demod_result")
    if demod:
        elements.append(Paragraph("Demodulation", h2))
        rows = [["Field", "Value"]]
        for k in ("modulation", "num_bits", "evm_percent", "lock_quality", "samples_per_symbol_used"):
            if k in demod:
                rows.append([k, str(demod[k])])
        t = Table(rows, colWidths=[180, 280])
        t.setStyle(TableStyle(_table_style_commands()))
        elements.append(t)
        bits_str = "".join(str(b) for b in demod.get("bits_preview", []))
        if bits_str:
            elements.append(Spacer(1, 4))
            elements.append(Paragraph("Bit preview:", small))
            elements.append(Paragraph(bits_str, mono))

    fec = result.get("fec_hypotheses", {})
    if fec.get("convolutional"):
        elements.append(Paragraph("FEC \u2014 Convolutional Hypotheses", h2))
        rows = [["Preset", "Re-encode distance"]] + [
            [c["preset"], f"{c['reencode_distance_fraction']:.4f}"] for c in fec["convolutional"]]
        t = Table(rows, colWidths=[220, 220])
        t.setStyle(TableStyle(_table_style_commands()))
        elements.append(t)
    if fec.get("reed_solomon"):
        elements.append(Paragraph("FEC \u2014 Reed-Solomon Hypotheses (top candidates)", h2))
        rows = [["Preset", "Result", "Corrected", "Byte offset"]]
        for r in fec["reed_solomon"][:6]:
            rows.append([r["preset"], "valid" if r["success"] else "failed",
                         str(r["symbols_corrected"]) if r["success"] else "\u2014", str(r["byte_alignment"])])
        t = Table(rows, colWidths=[140, 100, 100, 100])
        t.setStyle(TableStyle(_table_style_commands()))
        elements.append(t)

    deint = result.get("deinterleave_hypotheses", {})
    if deint.get("block"):
        elements.append(Paragraph("De-interleaving \u2014 Block Hypotheses", h2))
        rows = [["Rows", "Cols", "Structure score"]] + [
            [b["rows"], b["cols"], f"{b['structure_score']:.4f}"] for b in deint["block"]]
        t = Table(rows, colWidths=[150, 150, 150])
        t.setStyle(TableStyle(_table_style_commands()))
        elements.append(t)
    if deint.get("pseudo_random_note"):
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(f"<b>Pseudo-random interleaving:</b> {deint['pseudo_random_note']}", small))

    bitstream = result.get("bitstream_analysis")
    if bitstream:
        elements.append(Paragraph("Bit Stream Analysis", h2))
        elements.append(Paragraph(
            f"Length: {bitstream.get('length_bits')} bits &middot; Byte alignment: "
            f"{bitstream.get('best_byte_alignment')} "
            f"({(bitstream.get('byte_alignment_confidence') or 0) * 100:.0f}% confidence)", body))
        if bitstream.get("preamble_matches"):
            rows = [["Sync word", "Bit position", "Hamming distance"]] + [
                [m["name"], m["position"], m["hamming_distance"]] for m in bitstream["preamble_matches"][:10]]
            t = Table(rows, colWidths=[150, 150, 150])
            t.setStyle(TableStyle(_table_style_commands()))
            elements.append(t)
        hex_preview = bitstream.get("hex_preview", "")
        if hex_preview:
            elements.append(Spacer(1, 4))
            elements.append(Paragraph("Hex preview:", small))
            elements.append(Paragraph(hex_preview, mono))

    elements.append(Paragraph("Reproducibility", h2))
    rows = [["Field", "Value"],
            ["analysis_id", manifest.get("analysis_id", "")],
            ["pipeline_version", manifest.get("pipeline_version", "")],
            ["input_file_hash", (manifest.get("input_file_hash", "") or "")[:24]]]
    if manifest.get("parameters_used"):
        rows.append(["analyst_overrides", json.dumps(manifest["parameters_used"])])
    t = Table(rows, colWidths=[150, 350])
    t.setStyle(TableStyle(_table_style_commands()))
    elements.append(t)

    if manifest.get("warnings"):
        elements.append(Paragraph("Warnings", h2))
        for w in manifest["warnings"]:
            elements.append(Paragraph(f"\u26a0 {w}", small))

    doc.build(elements)
    return buf.getvalue()
