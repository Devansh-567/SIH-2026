---
title: Modulus RF Signal Analysis
emoji: 📡
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# RF Signal Analysis Platform -- MVP Backend

SIH Problem Statement 26147 (NTRO) -- "Automated model for analysis of .IQ
and .wav files along with signal parameter extraction"

This is the **DSP/FEC/pipeline/API backend** for the platform described in
the accompanying architecture report (`SIH_26147_Architecture_Report.md`).
It is a working, tested foundation -- **not** the finished product. See
"What's not built yet" below before presenting this as complete.

## Status: 188/188 tests passing

**SIH pitch deck:** `docs/SIH_26147_Pitch_Deck.pptx` (6 slides: Idea, Technical
Approach, Feasibility & Viability, Impact & Benefits, Research & Roadmap --
built around this repo's actual test results and measured ML accuracy
numbers, not placeholder figures). **Fill in the team name / team leader
placeholders on the title slide before submitting.**

```
pip install -r requirements.txt
python -m pytest tests/ -v
```

## What's implemented and verified

| Module | What it does | Tests |
|---|---|---|
| `rfplatform/models/schema.py` | The five-state honesty vocabulary (DETECTED/ESTIMATED/INFERRED/HYPOTHESIZED/UNKNOWN) as an enforced dataclass | — |
| `rfplatform/io/formats.py` | Memory-mapped WAV + raw IQ ingestion, full SigMF `core:datatype` vocabulary parser, sidecar pairing, `MissingSigMFMetadataError` for unresolvable `.sigmf-data` | `test_sigmf_formats.py`, plus via pipeline tests |
| `rfplatform/synth/generator.py` | Synthetic signal generator: BPSK/QPSK/8PSK/16QAM/64QAM/2FSK/4FSK with SNR, freq/phase/timing offsets, RRC pulse shaping | `test_synth_generator.py` |
| `rfplatform/dsp/estimators.py` | Noise floor, PSD/spectral features, IQ statistics, symbol-rate estimation, energy-based signal detection | `test_classifier_calibration.py` |
| `rfplatform/dsp/classifier.py` | Rule-based, explainable modulation classifier (family + exact order via M-th power method) | `test_classifier_calibration.py` |
| `rfplatform/dsp/demodulate.py` | PSK/QAM/FSK demodulators with matched filtering, carrier correction, EVM/lock metrics | `test_demodulate.py` |
| `rfplatform/fec/convolutional.py` | Convolutional coding + Viterbi (via scikit-commpy), hypothesis search | `test_fec.py` |
| `rfplatform/fec/reed_solomon.py` | Reed-Solomon (via reedsolo), syndrome-based self-verification, blind byte-alignment search | `test_fec.py` |
| `rfplatform/dsp/chunked.py` | Full-file streaming noise estimation + signal detection (chunk-by-chunk, peak memory bounded) | `test_chunked.py`, plus `test_pipeline_integration.py`'s large-file regression test |
| `rfplatform/report/generator.py` | Report export: JSON, CSV, PDF (via reportlab), and SigMF `.sigmf-meta` annotations -- all from the same analysis result, no recomputation | `test_report_generator.py` (PDF verified via real text extraction, not just "didn't crash") |
| `rfplatform/ml/` | Modulation classifier: small 1D CNN over raw IQ, trained on the synthetic generator (incl. a genuine noise-only 'unknown' class), temperature calibration (applied only when it measurably helps), wired into the real confidence-fusion pipeline | `test_ml.py` (15 tests: model/dataset/calibration math, real inference behavior, live pipeline integration) |
| `rfplatform/dsp/fingerprint.py` | Fixed-length signal feature vector (from already-computed Parameters) + Euclidean similarity search | `test_fingerprint.py` |
| `rfplatform/storage/db.py` | SQLite-backed analysis history, per-signal fingerprint index, analyst feedback, waterfall annotations | `test_storage.py` (10 tests) |
| `rfplatform/pipeline/compare.py` | Parameter-by-parameter diff between two stored analyses | via `test_api.py`'s compare tests |
| `rfplatform/interleave/interleavers.py` | Block, convolutional, diagonal, pseudo-random (honestly unrecoverable without seed) | `test_interleave.py` |
| `rfplatform/pipeline/bitstream.py` | Entropy, sync-word/preamble correlation, periodic framing, byte alignment | `test_bitstream.py` |
| `rfplatform/pipeline/fusion.py` | Confidence-fusion engine (DSP + ML evidence combination, agreement/disagreement handling) | `test_fusion.py` |
| `rfplatform/pipeline/stages.py` | Full 17-stage pipeline orchestration, analyst-override support | `test_pipeline_integration.py` |
| `rfplatform/api/main.py` | FastAPI backend: `/upload` (multi-file, SigMF auto-pairing), `/analyze`, `/batch/analyze`, `/spectrogram`, `/export` (by blob or by id), `/analyses` (history/get/delete/compare/similar), `/analyses/{id}/feedback`, `/analyses/{id}/annotations`, `/health`, `/upload/{id}` (delete) | `test_api.py` (34 tests) |
| `frontend/` | React/TS analyst GUI: waterfall, automatic-analysis panel with evidence trails, demod/FEC/bitstream panels, analyst overrides | manual `tsc -b` + `vite build` verified clean; see `frontend/README.md` |

## Running the API

```bash
uvicorn rfplatform.api.main:app --reload --host 127.0.0.1 --port 8000
```

## Running the GUI

```bash
cd frontend
npm install
npm run dev
```
Then open http://localhost:3000 (with the backend running per above --
the Vite dev server proxies `/api/*` to it). See `frontend/README.md` for
the design rationale and what's implemented/not yet implemented in the UI.

Then:
```bash
curl -X POST http://127.0.0.1:8000/upload -F "files=@your_signal.cf32"
# -> {"uploads": [{"file_id": "...", "kind": "standalone", ...}]}

# SigMF pair -- upload both files together (auto-paired by filename):
curl -X POST http://127.0.0.1:8000/upload \
  -F "files=@bpsk_rect_20sps.sigmf-data" \
  -F "files=@bpsk_rect_20sps.sigmf-meta"
# -> {"uploads": [{"file_id": "...", "kind": "sigmf", "sigmf_pair_complete": true, ...}]}

curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"file_id": "...", "sample_rate_hz": 200000}'
```

Or generate a synthetic test file first:
```python
from rfplatform.synth.generator import SynthConfig, generate, save_sigmf
cfg = SynthConfig(modulation="qpsk", n_symbols=5000, snr_db=20, seed=1, sample_rate_hz=200_000)
result = generate(cfg)
save_sigmf(result, "test_signal.sigmf-data")  # writes .sigmf-data + .sigmf-meta
```
Upload the `.sigmf-data` file -- the sidecar `.sigmf-meta` is read automatically for sample rate.

## SigMF support

`.sigmf-data` + `.sigmf-meta` pairs are first-class citizens throughout the
system, not just in the upload UI:

- **Upload**: drop both files together (or upload them separately, in
  either order) and the backend auto-pairs them by original filename stem
  (`bpsk_rect_20sps.sigmf-data` + `bpsk_rect_20sps.sigmf-meta` -> one
  recording), storing them under a shared `file_id` so the pairing survives
  even across two separate upload requests. See `api/main.py::upload_files`.
- **Ingestion**: `core:datatype` drives byte-level decoding via a real
  parser covering the full SigMF vocabulary (`cf32_le`, `ci16_le`, `cu8`,
  `ru16_be`, etc. -- complex and real, all four integer/float kinds, both
  byte orders), not just the handful of formats this project started with.
  See `io/formats.py::parse_sample_format`.
- **Everything downstream** -- noise floor, detection, spectral/symbol-rate
  estimation, modulation classification, demodulation, FEC/de-interleave
  hypothesis search, bitstream framing, and the waterfall's frequency axis
  -- consumes the *same* `sample_rate_hz`/`center_freq_hz` resolved at
  ingestion. There is no second, independent place where these values get
  re-derived or re-guessed.
- **No silent fallback.** A `.sigmf-data` file whose datatype can't be
  resolved (no sidecar, no override) raises `MissingSigMFMetadataError` --
  a clear 400 at the API layer -- rather than guessing a format. A
  recording whose *sample rate* is unresolved (format known, rate isn't)
  is ingested fine, but every frequency-dependent pipeline stage is
  explicitly skipped with a stated reason, and `/spectrogram` returns 400
  rather than computing a physically meaningless Hz axis. `sample_rate_hz`
  is never silently set to a placeholder like `1 Hz` anywhere in the
  codebase -- this was a real bug found and fixed during development (see
  git history / the debugging notes below).
- **Provenance**: `sample_rate_hz` and `center_frequency_hz` are exposed as
  ordinary `Parameter` objects (same evidence/status model as every other
  extracted value) tagged `DETECTED` with evidence citing `sigmf_metadata`,
  `wav_header`, or `analyst_override` -- or `UNKNOWN` with an explanation
  when genuinely unavailable. This means the GUI shows their provenance
  for free, with no SigMF-specific frontend code required.

## ML classifier

`rfplatform/ml/` is a real, trained, working component -- not architected-
but-unimplemented. Run `python -m rfplatform.ml.train` to retrain it
yourself (~35s on this environment); the trained checkpoint (~208KB) is
bundled at `rfplatform/ml/checkpoints/modulation_classifier.pt` so a fresh
checkout works immediately.

**What it is:** a small 1D CNN (~50K parameters) over raw IQ samples (2
channels: I and Q, 512-sample window), trained on the synthetic
generator across all 7 modulations plus a genuine noise-only `unknown`
class, with temperature calibration applied only when it measurably
improves calibration error on held-out data (see debugging notes).

**Honestly-reported results** (run `python -m rfplatform.ml.evaluate` to
reproduce):
- Validation accuracy: ~68-70% (8-way classification: 7 modulations + unknown)
- Noise/unknown rejection rate: 100% in testing (100/100 pure-noise inputs
  correctly classified as `unknown`)
- **Family-level classification (PSK vs. QAM vs. FSK) is reliable.**
  **Order-level classification within a family is weak** -- confusion
  matrix at 10-25dB SNR shows 8PSK misclassified as QPSK in ~87% of cases,
  and real (bidirectional) confusion between 16QAM/64QAM and between
  2FSK/4FSK. This is a genuine, measured limitation of a small model
  trained briefly on CPU, not hidden or dressed up.
- Accuracy vs. SNR is not perfectly monotonic in the current checkpoint
  (small evaluation sample sizes, ~40-60 examples/bucket, contribute
  meaningful binomial noise to these numbers; this hasn't been run at a
  larger sample size to separate real effects from noise).

**Why this limitation is actually a good demonstration of the project's
own thesis, not just a flaw to fix later:** the DSP classifier's M-th
power method (`dsp/classifier.py`) is specifically *strong* at PSK-order
discrimination -- it gets BPSK/QPSK/8PSK right essentially every time at
usable SNR (see `test_classifier_calibration.py`). Confirmed directly
(see `test_ml.py` and the fusion engine's own tests): when the ML
classifier confuses an 8PSK signal for QPSK, the DSP classifier gets it
right, and the confidence-fusion engine correctly surfaces both
hypotheses, ranks the correct one first (higher DSP confidence), and
honestly downgrades status to `HYPOTHESIZED` with penalized confidence
rather than either silently trusting the wrong ML answer or silently
overriding it without saying so. This is the "hybrid DSP+AI, use each
where it's strong" architecture from PART 11 actually working, measured
on a real disagreement, not just described.

## Analyst visualizations

The problem statement names four visualizations. All four are now built:

| Visualization | Component | Notes |
|---|---|---|
| Waterfall / spectrogram | `Waterfall.tsx` | Canvas, signature 5-stop colormap, absolute-frequency axis when center freq is known |
| **Constellation** | `ConstellationPlot.tsx` | Canvas scatter with *additive blending* so cluster density reads visually; EVM + lock-quality shown alongside |
| **Time domain** | `SignalPlots.tsx` | I, Q and envelope traces on a shared axis |
| **Frequency domain (PSD)** | `SignalPlots.tsx` | Welch PSD with the detected peak marked and labelled |

Backend support: the demodulator always computed constellation points but
previously discarded them before the API boundary -- they are now exposed
on `demod_result.constellation`, decimated to at most 2000 points
(`CONSTELLATION_MAX_POINTS`) so the payload stays bounded no matter how
long the recording is. Time-domain and PSD traces come from a new
`POST /signal-view` endpoint, likewise decimated server-side: a plot a few
hundred pixels wide cannot resolve more, so shipping a million points to
draw eight hundred would be waste.

## Live demo: built-in sample signals

For a hosted/judged demo where the evaluator has no `.iq` file of their own,
the Analyze tab's empty state shows a **"No recording handy? Try one of
these"** gallery. One click loads a sample and runs the complete pipeline.

Four samples, each chosen to demonstrate a different capability:
| Sample | Demonstrates |
|---|---|
| QPSK @ 20 dB | Clean end-to-end success; SigMF metadata read, not guessed |
| 2-FSK @ 3 dB | **Honest degradation** -- low confidence / HYPOTHESIZED, not a confident wrong answer |
| Two signals in one file | Automatic multi-signal segmentation |
| BPSK + convolutional FEC | FEC hypothesis search finding the real CCSDS K=7 r1/2 code (0.0000 re-encode distance) |

Implementation notes that matter for credibility:
- Samples are **generated on demand** by `rfplatform/synth/samples.py` from
  this project's own tested signal generator, cached under `/tmp` after
  first build -- not binary blobs committed to the repo.
- Loading a sample registers it in the **normal upload area** and analyzes
  it through the **same `/analyze` endpoint** a real upload uses. A demo on
  a special-case code path would prove nothing about the real one.
- The UI labels them plainly as **synthetic signals, not off-air captures**,
  and shows each sample's known ground truth next to what the pipeline
  actually found -- including when they disagree on the deliberately hard
  low-SNR case.

## Analyst workflow features: history, batch, comparison, feedback, annotations, fingerprinting

All of the following are real, tested backend capabilities (see
`tests/test_storage.py`, `tests/test_fingerprint.py`, and the relevant
sections of `tests/test_api.py` and `tests/test_pipeline_integration.py`).
**Frontend coverage:** history, batch upload, comparison, feedback
submission, and similar-signal lookup all have GUI support -- the app now
has four tabs (Analyze / History / Batch / Compare); see
`frontend/src/components/HistoryView.tsx`, `BatchView.tsx`, `CompareView.tsx`,
and `SimilarSignalsPanel.tsx`, plus the inline correction widget added to
`ParameterCard.tsx`. Waterfall click-to-annotate is the one piece still
GUI-less (backend fully built and tested; see "What's NOT built yet").


- **Automatic multi-signal segmentation.** The pipeline no longer analyzes
  only the single largest detected region in a file. `run_pipeline` now
  runs the full parameter-extraction/demod/FEC/bitstream chain on up to
  `MAX_SIGNALS_PER_FILE` (5) detected regions, returned as `signals: [...]`
  in the analysis result -- each with its own parameters, demod result,
  FEC hypotheses, and fingerprint. The single largest ("primary") signal's
  results are still mirrored onto the top-level `parameters`/`demod_result`/
  etc. fields for backward compatibility with every existing consumer.
  Verified with a real two-signal recording (BPSK + QPSK, well-separated in
  time) where the pipeline correctly identifies both.
- **Analysis history.** Every `/analyze` and `/batch/analyze` call
  persists its full result to a local SQLite database (`rfplatform/storage/db.py`).
  `GET /analyses` lists history (newest first); `GET /analyses/{id}`
  retrieves one in full.
- **Shareable analysis/report.** Because every analysis is persisted under
  its `analysis_id`, sharing a report is just sharing that id: `/export`
  now accepts either a full `analysis` blob (as before) or an `analysis_id`
  to fetch from history, so a recipient's own client can pull the exact
  same PDF/JSON/CSV/SigMF export without the original caller re-sending
  the full result.
- **Signal comparison.** `GET /analyses/compare?a={id}&b={id}` returns a
  parameter-by-parameter diff (`rfplatform/pipeline/compare.py`) between
  two stored analyses, plus a recording-level (sample rate/format/duration)
  comparison.
- **Batch/multi-file analysis.** `POST /batch/analyze` runs the full
  pipeline across up to 20 already-uploaded files in one call, persisting
  each to history and reporting per-file success/failure independently (one
  bad file doesn't abort the batch). Runs synchronously in a loop, not a
  background job queue -- see "What's NOT built yet".
- **Analyst corrections + feedback.** `POST /analyses/{id}/feedback`
  records a correction to *any* named parameter (not just the three the
  in-pipeline `overrides` mechanism supports for re-running), automatically
  capturing the original value/status alongside the analyst's corrected
  value and an optional note. This is a durable audit trail, not a live
  re-run mechanism -- it does **not** automatically retrain the ML
  classifier or change future analyses. That's an honest, stated
  limitation: this is feedback *capture* infrastructure, not an online-
  learning loop, which would be a substantial separate project.
- **Waterfall/signal-region annotations.** `POST /analyses/{id}/annotations`
  records a time/frequency-scoped note (start/end time, frequency, label,
  free-text note) against a stored analysis. The backend has no opinion on
  how these are drawn -- a GUI could render them as markers on the
  waterfall, a list, or both.
- **Automatic signal similarity/fingerprinting.** Every analyzed signal
  gets a fixed-length feature vector (`rfplatform/dsp/fingerprint.py`) built
  from already-computed Parameters (bandwidth, SNR, spectral entropy,
  symbol rate, noise floor, modulation one-hot) -- deliberately not a
  learned embedding, so every dimension is traceable to a named, evidenced
  value. `GET /analyses/{id}/similar` does a brute-force nearest-neighbor
  search (plain Euclidean distance) across every other signal in history.
  Verified to correctly rank same-modulation signals as more similar than
  different-modulation ones.

## Environment deviation from the architecture report (and why)

The architecture report's PART 9 recommended liquid-dsp as the primary
linked DSP core, with GNU Radio as an isolated fallback. Neither installs
cleanly via pip in a constrained sandbox environment (GNU Radio isn't
meaningfully pip-installable at all; liquid-dsp needs a C toolchain and
isn't reliably on PyPI). This build instead uses:

- **scikit-commpy** (BSD-3) for PSK/QAM modem primitives and convolutional
  coding/Viterbi -- pip-installable, permissively licensed, no change to
  the license-compliance story in the report.
- **reedsolo** (MIT) for Reed-Solomon.
- Custom NumPy/SciPy implementations for FSK, interleaving, spectral
  estimation, and bitstream analysis.

This is a legitimate substitution consistent with the report's own
licensing logic (prefer permissive, pip-installable libraries), not a
scope cut. One real upstream limitation was found along the way:
scikit-commpy's `Trellis` builder overflows an internal `int8` state-index
array for convolutional constraint lengths >= 8 under current NumPy's
strict integer-overflow checking. Our convolutional-code presets are
therefore capped at K=7, which conveniently is also literally what the PS
asks for ("short-constrained convolutional codes").

## Debugging notes worth knowing about

Several non-obvious DSP bugs were found and fixed by testing against known
synthetic ground truth rather than trusting the math on paper. If you
extend this code, be aware of:

1. **SNR estimation requires unit conversion.** Comparing a PSD-per-Hz
   noise floor against total time-domain power without integrating over
   bandwidth gives wildly wrong SNR. Fixed in `dsp/classifier.py`.
2. **RRC-shaped signals need a matched filter at the receiver**, not direct
   downsampling -- a single RRC does not satisfy the zero-ISI Modulus
   criterion by itself; only the TX+RX RRC cascade does. Fixed in
   `dsp/demodulate.py::_matched_filter`.
3. **The correct symbol-sampling phase after matched filtering was offset=0,
   not `sps//2`** -- the intuitive "sample the middle of the symbol" guess
   was empirically the *worst* phase for this pulse-shaping implementation.
   Confirmed by sweeping all candidate offsets against known BPSK bits.
4. **Carrier-offset correction must not blindly exclude a window around
   DC.** A guard band intended to avoid DC-bias artifacts was instead
   deleting the true signal peak whenever the real offset was near zero,
   corrupting the most common case. Fixed by using the full spectrum with
   only a confidence gate (peak-to-median ratio) rather than an exclusion
   window.
5. **QAM's non-constant modulus breaks naive M-th-power carrier recovery**
   -- squaring a QAM signal doesn't cleanly collapse to one tone. Fixed
   with the same peak-to-median confidence gate: skip correction rather
   than apply a confident-looking wrong one.
6. **FSK frequency-discriminator demod needs averaging, not single-sample
   readout** -- differentiator-based instantaneous-frequency demod
   amplifies noise (a known FM "click noise" effect). Averaging over the
   symbol interior (excluding transition edges) took 4FSK from 19% BER to
   <0.1% BER at the same SNR.
7. **The convolutional interleaver's fixed system delay is
   `depth * (depth-1) * span`**, not the more intuitive `(depth-1) * span`
   -- derived empirically, not assumed, and documented in
   `interleave/interleavers.py::convolutional_system_delay`.
8. **Structure-detection heuristics for de-interleaving must score
   periodicity as *positive* evidence, not negative** -- an early version
   of the block-interleaver hypothesis search had the direction backwards
   (favoring scrambled data over correctly-recovered periodic data), which
   is the opposite of what "does this look correctly deinterleaved" should
   mean.
9. **A regex with an "optional" suffix group can silently defeat its own
   normalization step.** `parse_sample_format`'s SigMF-datatype regex
   originally made `_le`/`_be` optional for every bit width, so a bare
   `"cf32"` matched the "already-canonical" branch directly (by accident of
   shape) and skipped the legacy-alias table that was supposed to map it to
   `"cf32_le"` -- returning an un-normalized, format-inconsistent value. Per
   the actual SigMF spec, the endianness suffix is required for every width
   except 8-bit; fixing the regex to reflect that (rather than loosely
   accepting anything shaped like a datatype string) fixed the bug.
10. **A first-match glob over `{file_id}*` can return the wrong half of a
    SigMF pair.** Once `.sigmf-data` and `.sigmf-meta` share a `file_id`
    prefix, resolving "the file for this file_id" by taking the first glob
    result is order-dependent and can hand `load_recording` the metadata
    file instead of the data file. Fixed by explicitly excluding
    `.sigmf-meta` from candidacy in `api/main.py::_resolve_data_file`.
11. **`reedsolo.RSCodec` does not encode to a fixed total codeword length.**
    It appends `n-k` parity bytes to whatever payload length it's given --
    encoding a 200-byte payload with the "rs_255_223" preset produces a
    232-byte codeword, not 255. An early version of the blind byte-alignment
    RS search assumed a fixed 255-byte block and silently produced zero
    candidates as a result.
12. **A successful Reed-Solomon decode is necessary but not sufficient
    evidence.** A preset with fewer parity bytes (weaker syndrome check)
    can report `success=True` at the *correct* byte alignment while
    decoding to the *wrong* content -- confirmed directly: decoding an
    `rs_255_223`-encoded block with the `rs_255_239` preset reported a
    clean decode (0 symbols corrected) but produced different bytes than
    the original payload. Hypothesis ranking now tie-breaks toward more
    parity bytes for exactly this reason, and the GUI surfaces the caveat
    rather than presenting "success" as certainty.
13. **Comparing time-domain windowed power against a PSD-density noise
    floor without unit conversion silently breaks signal detection.** This
    is the same class of bug as the earlier SNR fix, but in
    `detect_signal_regions` this time: `noise_floor_db` is a power-per-Hz
    quantity, while the detector's windowed power is a raw time-domain
    total. Without integrating the PSD over the sampled bandwidth first,
    the effective detection threshold sat ~30dB too low, so an early
    version of the chunked-scanning test (which was the first test to
    actually check *which* samples got flagged, not just "some region
    exists") found the detector flagging an entire 5,000,000-sample file
    -- mostly plain noise, with one real burst -- as a single active
    region. This was a pre-existing bug, not something introduced by the
    chunking work; the chunking work is just what surfaced it.
14. **A test asserting exact dict/JSON equality has to account for JSON
    having no tuple type.** `test_json_export_round_trips_exactly` first
    compared the parsed-back JSON against the original Python dict
    directly, which legitimately fails because `detected_regions`' tuples
    become lists after any JSON round trip -- not a bug in `to_json_bytes`,
    a bug in comparing against an un-normalized original. Fixed by
    normalizing both sides through one `json.dumps`/`json.loads` pass
    before comparing.
15. **An attacker-controlled filename hint reflected into a response
    header needs stricter sanitization than "replace disallowed
    characters."** `_safe_stem`'s character-class filter correctly turned
    slashes into underscores but left repeated dots alone (dots were never
    a disallowed character), so `"../../etc/passwd"` survived sanitization
    as `".._.._etc_passwd"` -- not exploitable here (the value only ever
    reaches a `Content-Disposition` header, never a filesystem path), but
    worth closing defensively since export filenames are the first
    user-controlled string this project reflects straight into an HTTP
    response. Fixed by collapsing repeated dots and stripping leading dots
    in addition to the existing character-class filter.
16. **Applying temperature scaling only if it demonstrably helps required
    building the guard, not just calling the fitting function.** An early
    training run's NLL-minimizing temperature (T=0.783, later T=0.686 on a
    rerun) actually made expected calibration error *worse*, because the
    model was already reasonably well-calibrated (BatchNorm + Dropout both
    push against overconfidence) and NLL-minimization on a few thousand
    calibration samples isn't the same objective as ECE-minimization.
    `train.py` now computes ECE with and without the fitted temperature
    and only applies it if ECE actually improves, falling back to T=1.0
    (a no-op) otherwise -- confirmed this fallback actually triggers on the
    real training run, not just in a contrived test.
17. **A calibration test that assumes "sharpening logits creates
    overconfidence" needs to verify that assumption, not assert it.** An
    early version of `test_fit_temperature_...` multiplied already-accurate
    synthetic logits by a constant and expected the fitted temperature to
    come back >1 (softening); it came back at T=0.49 instead, which was
    *correct* behavior for that input (the underlying separation was
    already accuracy-consistent, not miscalibrated) -- the test's premise
    was unverified, not the code under test. Fixed by constructing an
    unambiguous case instead: predictions that are always maximally
    confident regardless of correctness, with a known 70% true accuracy,
    which is overconfidence by definition and reliably drives T upward.
18. **A path parameter in a route can silently shadow a literal-segment
    route registered after it.** `GET /analyses/compare` was registered
    AFTER `GET /analyses/{analysis_id}`, so FastAPI/Starlette matched
    `compare` as if it were an `analysis_id` value and the dedicated
    compare handler was completely unreachable -- confirmed live (`curl`
    against the running server returned `"No stored analysis found for
    analysis_id=compare"`, a 404 from the WRONG handler, not the compare
    endpoint's own error). Fixed by moving the literal-segment route
    (`/compare`) before the path-parameter route (`/{analysis_id}`) --
    registration order matters whenever a literal segment could also be a
    syntactically valid path-parameter value, which is essentially always
    true for a `str` parameter.
19. **A default-argument helper (`_connect`) assumed its `db_path` argument
    was always a `Path`, but nothing enforced that.** Calling it with a
    plain `str` (an easy mistake -- `os.path.join` and `tempfile.mkdtemp`
    both return strings) threw `AttributeError: 'str' object has no
    attribute 'parent'` instead of working or failing with a clear message.
    Fixed by coercing with `Path(db_path)` inside `_connect` rather than
    trusting every caller to pass the right type.
20. **Only one function (`save_analysis`) called `init_db()`, so calling
    any OTHER storage function first (e.g. `get_analysis` on a database
    that had never been written to) threw `sqlite3.OperationalError: no
    such table: analyses`** instead of the documented "returns None for a
    nonexistent id" behavior. Fixed by folding schema creation into
    `_connect()` itself (`CREATE TABLE IF NOT EXISTS` is cheap enough to
    run on every call) so every public function is safe regardless of
    call order, rather than relying on every function remembering to
    initialize the schema first.
21. **The sandbox environment itself reset mid-session while building the
    History/Batch/Compare frontend views**, wiping the entire working
    directory (`/home/claude`). Not a code bug, but worth recording
    plainly: the project's recoverability depended entirely on having
    already packaged a zip checkpoint to a separate, persistent output
    mount earlier in the session. Recovery was: restore from that zip,
    re-verify the full 176-test backend suite and a clean frontend build
    from the restored state, then rebuild only the handful of frontend
    files that had been created after the last checkpoint. This is the
    practical argument for packaging and delivering working checkpoints
    regularly during a long build, not just at the very end.

None of these were caught by "does it import" or "does it run without
throwing" -- they only surfaced by testing against known ground truth
(exact bits in, exact bits expected out) and noticing when the numbers
were wrong. This is the same discipline the architecture report's PART 18
(testing strategy) calls for applied to the actual build.

## What's NOT built yet

- **Waterfall annotation UI specifically.** History browser, batch-upload
  flow, side-by-side comparison view, feedback-submission form, and
  "similar signals" panel are now all built into the GUI (Analyze/History/
  Batch/Compare tabs -- see below). The one piece still missing GUI
  coverage is drawing/clicking annotation markers directly on the
  waterfall; the backend (`/analyses/{id}/annotations`) is fully built and
  tested, just not wired into a click handler on the canvas yet.
- **Batch analysis is synchronous, not a background job queue.** A batch of
  20 files runs in a single HTTP request, one after another -- fine for a
  demo, but a real deployment would want the async job-graph design the
  architecture report's PART 8 describes (submit a batch, poll/subscribe
  for progress, don't hold one HTTP connection open for the whole run).
- **Feedback capture does not feed back into anything.** `/feedback`
  durably records analyst corrections but nothing currently reads them --
  no retraining, no confidence-model adjustment, no aggregate "the model
  is often wrong about X" reporting. It's an audit trail and a foundation
  for that future work, not the future work itself.
- **Fingerprint similarity is brute-force and un-indexed.** Fine at the
  scale of an analyst's own recording history (hundreds to low thousands of
  signals); would need a proper ANN index (e.g. FAISS/HNSW) to scale
  further, which hasn't been necessary to build yet.
- **ONNX export for lighter-weight inference.** The architecture report's
  PART 9 recommends training in PyTorch and exporting to ONNX Runtime so
  the shipped tool doesn't require a full PyTorch install on an analyst's
  machine. Not done -- inference currently runs directly on the PyTorch
  checkpoint (`rfplatform/ml/inference.py`), which is fine for this
  environment but is the documented next step for a lighter deployment.
- **Larger/longer training run.** The bundled checkpoint trained in ~35s on
  4000 on-the-fly synthetic examples per epoch, 10 epochs, CPU-only,
  single-threaded -- deliberately sized for this environment's constraints,
  not for maximum accuracy. See "ML classifier" below for honestly-reported
  results and a concrete idea (given more compute) of what to improve.
- **Multi-signal-per-file separation.** The pipeline currently analyzes the
  single largest detected region per file. Full time-frequency clustering
  for simultaneous multi-signal recordings is a documented roadmap item
  (architecture report PART 25).
- **Chunked/streaming analysis for very large files -- now implemented.**
  `rfplatform/dsp/chunked.py` scans the entire file chunk-by-chunk (peak
  memory bounded by one chunk) for noise estimation and signal detection,
  replacing an earlier hardcoded 2M-sample cap that silently made any
  signal later in a large file invisible to the pipeline. The *deep*
  per-sample stages (feature extraction, classification, demod) still
  bound how much of the *selected* signal-of-interest region they process
  (`SOI_ANALYSIS_MAX_SAMPLES`, 2M samples) -- a deliberate scoping choice
  (a bounded sample of a long continuous signal is enough for these
  estimates), not a silent truncation of what gets detected. Not yet
  tested at true multi-GB scale in this environment -- validated up to a
  5,000,000-sample (~80MB) file with a signal deliberately placed past the
  old cutoff; the chunking approach itself has no reason not to scale
  further, but that's an inference, not a measurement.
- **Closed-loop timing/carrier recovery.** Current carrier/timing recovery
  is feed-forward/coarse (M-th power + fixed matched-filter offset), not a
  tracking Costas/Gardner loop -- adequate for the synthetic MVP test
  signals, not yet validated against drifting real-world signals.
- **Reed-Solomon -- now wired into the pipeline.** `fec_hypotheses` includes
  both `convolutional` and `reed_solomon` candidate lists, the latter via a
  blind byte-alignment search (RS operates on bytes; a demodulated
  bitstream's byte phase isn't known in advance). **LDPC and joint
  conv+RS concatenated-code decoding remain unimplemented** -- registries
  support adding them, but no LDPC decoder is wired in yet.
- **FEC hypothesis testing is capped to a 4000-bit prefix of the
  demodulated stream** (`FEC_HYPOTHESIS_MAX_BITS`), not the full
  bitstream. This was a deliberate fix, not an oversight: `commpy`'s
  Viterbi decoder is pure Python with no vectorization, and testing the
  full bitstream against 3 convolutional presets was taking 10-20+ seconds
  per `/analyze` call -- a real problem for live use, not just test speed.
  A representative prefix is methodologically sufficient for a hypothesis
  test (which preset best matches), not just faster.
- **Report export -- now implemented.** `/export` (backend) + the GUI's
  Export Report panel produce JSON, CSV, PDF (via reportlab, verified by
  actually extracting and checking its text content, not just confirming a
  valid PDF structure), and a SigMF `.sigmf-meta` annotations document
  (carrying findings forward as `rfplatform:`-namespaced annotations,
  closing the loop with this project's own SigMF ingestion work). Export
  is stateless -- it operates on whatever `AnalysisResultJSON` the caller
  already has, with no server-side recomputation or caching, so an export
  is always exactly what's on screen.
- **Security hardening beyond basic upload validation.** Extension/size
  checks exist; a real gap was found and fixed while building the export
  filename handling (see debugging notes below) -- but broader process
  isolation, fuzz-testing against malformed files, and resource-exhaustion
  defenses are not yet implemented.

## Project layout

```
rfplatform/
  models/schema.py       Parameter/Evidence/Status data model
  io/formats.py           WAV/IQ/SigMF ingestion (memory-mapped)
  synth/generator.py      Synthetic signal generator
  dsp/estimators.py       Noise/spectral/IQ feature extraction
  dsp/classifier.py       Rule-based modulation classifier
  dsp/demodulate.py       PSK/QAM/FSK demodulator registry
  fec/convolutional.py    Convolutional + Viterbi
  fec/reed_solomon.py     Reed-Solomon
  interleave/interleavers.py   Block/convolutional/diagonal/pseudo-random
  pipeline/bitstream.py   Sync-word/framing/entropy analysis
  pipeline/fusion.py      Confidence fusion engine
  pipeline/stages.py      Full pipeline orchestration
  api/main.py             FastAPI backend
tests/                    104 tests across 10 files (one per module above, plus test_sigmf_formats.py)
requirements.txt
```
