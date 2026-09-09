"""
Persistent storage -- SQLite, matching the architecture report's own
recommendation ("SQLite for local/single-analyst deployment"). This is
what turns a single stateless /analyze call into: analysis history,
shareable-by-ID reports, cross-recording signal comparison, and
fingerprint similarity search across everything ever analyzed.

Design choices:
- One connection per call, not a pooled/shared connection -- FastAPI runs
  sync `def` endpoints in a thread pool, and sqlite3 connections are not
  safe to share across threads by default. Per-call open/close overhead is
  negligible next to the cost of an /analyze pipeline run.
- The full AnalysisResultJSON is stored as a JSON blob (source of truth
  for "get this exact analysis back"), with a handful of columns
  duplicated out for cheap listing/filtering/search without needing to
  parse every blob. `signals` gets its own table specifically so
  fingerprint similarity search can scan just the small fingerprint
  vectors, not every full analysis blob.
- Default path is under /tmp, consistent with this project's existing
  upload-directory choice -- fine for a demo/single-session environment,
  but a real deployment should point DB_PATH at a persistent location
  (documented in README).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path("/tmp/rfplatform_history.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    input_file TEXT,
    file_hash TEXT,
    source_format TEXT,
    sample_rate_hz REAL,
    center_freq_hz REAL,
    primary_modulation TEXT,
    primary_status TEXT,
    num_signals INTEGER,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    signal_index INTEGER NOT NULL,
    region_start INTEGER,
    region_end INTEGER,
    modulation TEXT,
    confidence REAL,
    fingerprint_json TEXT,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    original_value TEXT,
    original_status TEXT,
    corrected_value TEXT NOT NULL,
    note TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL,
    freq_hz REAL,
    label TEXT,
    note TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses(created_at);
CREATE INDEX IF NOT EXISTS idx_signals_analysis_id ON signals(analysis_id);
CREATE INDEX IF NOT EXISTS idx_feedback_analysis_id ON feedback(analysis_id);
CREATE INDEX IF NOT EXISTS idx_annotations_analysis_id ON annotations(analysis_id);
"""


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Opens a connection AND guarantees the schema exists, every time --
    folded into one place rather than relying on every public function to
    remember to call init_db() first. Found via testing: get_analysis()
    on a brand-new db_path (nothing ever saved to it yet) threw
    "no such table: analyses" instead of the documented "returns None"
    behavior, because only save_analysis() called init_db(). CREATE TABLE
    IF NOT EXISTS is cheap enough to run on every connection.
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Kept as a public function for explicit/eager initialization (e.g.
    at app startup); _connect() also guarantees the schema exists on every
    call, so using this is optional, not required."""
    _connect(db_path).close()


def save_analysis(result_dict: dict, db_path: Optional[Path] = None) -> str:
    """
    Persists a full AnalysisResultJSON dict (as produced by
    AnalysisResult.as_dict()). Uses manifest.analysis_id as the primary
    key -- re-saving the same analysis_id overwrites the prior row
    (INSERT OR REPLACE), so re-running an analysis with the same manifest
    id is idempotent rather than accumulating duplicate history entries.
    """
    conn = _connect(db_path)
    try:
        manifest = result_dict.get("manifest", {})
        summary = result_dict.get("recording_summary", {})
        analysis_id = manifest.get("analysis_id")
        if not analysis_id:
            raise ValueError("result_dict.manifest.analysis_id is required to save an analysis")

        primary_mod_param = next((p for p in result_dict.get("parameters", []) if p["name"] == "modulation"), None)
        signals = result_dict.get("signals", [])

        conn.execute(
            "INSERT OR REPLACE INTO analyses "
            "(id, created_at, input_file, file_hash, source_format, sample_rate_hz, center_freq_hz, "
            " primary_modulation, primary_status, num_signals, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                analysis_id, manifest.get("created_at", time.time()), manifest.get("input_file"),
                manifest.get("input_file_hash"), summary.get("source_format"), summary.get("sample_rate_hz"),
                summary.get("center_freq_hz"),
                primary_mod_param.get("value") if primary_mod_param else None,
                primary_mod_param.get("status") if primary_mod_param else None,
                len(signals), json.dumps(result_dict),
            ),
        )
        conn.execute("DELETE FROM signals WHERE analysis_id = ?", (analysis_id,))
        for i, sig in enumerate(signals):
            mod_param = next((p for p in sig.get("parameters", []) if p["name"] == "modulation"), None)
            region = sig.get("region", [None, None])
            conn.execute(
                "INSERT INTO signals (id, analysis_id, signal_index, region_start, region_end, "
                "modulation, confidence, fingerprint_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{analysis_id}:{i}", analysis_id, i, region[0], region[1],
                    mod_param.get("value") if mod_param else None,
                    mod_param.get("confidence") if mod_param else None,
                    json.dumps(sig.get("fingerprint", [])),
                ),
            )
        conn.commit()
        return analysis_id
    finally:
        conn.close()


def get_analysis(analysis_id: str, db_path: Optional[Path] = None) -> Optional[dict]:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT result_json FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        return json.loads(row["result_json"]) if row else None
    finally:
        conn.close()


def list_analyses(limit: int = 50, offset: int = 0, db_path: Optional[Path] = None) -> list[dict]:
    """Summary rows only (not the full result blob) -- cheap for a history list view."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, created_at, input_file, source_format, sample_rate_hz, center_freq_hz, "
            "primary_modulation, primary_status, num_signals FROM analyses "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_analysis(analysis_id: str, db_path: Optional[Path] = None) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        conn.execute("DELETE FROM signals WHERE analysis_id = ?", (analysis_id,))
        conn.execute("DELETE FROM feedback WHERE analysis_id = ?", (analysis_id,))
        conn.execute("DELETE FROM annotations WHERE analysis_id = ?", (analysis_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def find_similar_signals(fingerprint_vector: list[float], exclude_analysis_id: Optional[str] = None,
                          top_k: int = 5, db_path: Optional[Path] = None) -> list[dict]:
    """Brute-force nearest-neighbor search over every stored signal's
    fingerprint. Fine at the scale this tool operates at (an analyst's own
    recording history); would need an ANN index at a much larger scale."""
    from rfplatform.dsp.fingerprint import fingerprint_distance

    conn = _connect(db_path)
    try:
        query = "SELECT id, analysis_id, signal_index, region_start, region_end, modulation, fingerprint_json FROM signals"
        params: tuple = ()
        if exclude_analysis_id:
            query += " WHERE analysis_id != ?"
            params = (exclude_analysis_id,)
        rows = conn.execute(query, params).fetchall()

        scored = []
        for row in rows:
            vec = json.loads(row["fingerprint_json"])
            if len(vec) != len(fingerprint_vector):
                continue  # different FINGERPRINT_VERSION; skip rather than error on a batch search
            dist = fingerprint_distance(fingerprint_vector, vec)
            scored.append({
                "signal_id": row["id"], "analysis_id": row["analysis_id"], "signal_index": row["signal_index"],
                "region": [row["region_start"], row["region_end"]], "modulation": row["modulation"],
                "distance": dist,
            })
        scored.sort(key=lambda s: s["distance"])
        return scored[:top_k]
    finally:
        conn.close()


def save_feedback(analysis_id: str, parameter_name: str, corrected_value, original_value=None,
                   original_status: Optional[str] = None, note: Optional[str] = None,
                   db_path: Optional[Path] = None) -> int:
    """
    Records an analyst correction -- distinct from the existing in-pipeline
    `overrides` mechanism (which affects a single re-run): this is a
    durable record of "an analyst corrected X to Y", kept for audit trail
    and as a foundation for future training-data curation. It does NOT
    currently feed back into model training automatically -- that's a
    documented, honest limitation, not a hidden gap.
    """
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO feedback (analysis_id, parameter_name, original_value, original_status, "
            "corrected_value, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (analysis_id, parameter_name, json.dumps(original_value), original_status,
             json.dumps(corrected_value), note, time.time()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_feedback(analysis_id: Optional[str] = None, db_path: Optional[Path] = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        if analysis_id:
            rows = conn.execute("SELECT * FROM feedback WHERE analysis_id = ? ORDER BY created_at DESC",
                                 (analysis_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM feedback ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["original_value"] = json.loads(d["original_value"]) if d["original_value"] else None
            d["corrected_value"] = json.loads(d["corrected_value"])
            out.append(d)
        return out
    finally:
        conn.close()


def save_annotation(analysis_id: str, start_s: float, end_s: Optional[float] = None,
                     freq_hz: Optional[float] = None, label: Optional[str] = None,
                     note: Optional[str] = None, db_path: Optional[Path] = None) -> int:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO annotations (analysis_id, start_s, end_s, freq_hz, label, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (analysis_id, start_s, end_s, freq_hz, label, note, time.time()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_annotations(analysis_id: str, db_path: Optional[Path] = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM annotations WHERE analysis_id = ? ORDER BY start_s ASC",
                             (analysis_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_annotation(annotation_id: int, db_path: Optional[Path] = None) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
