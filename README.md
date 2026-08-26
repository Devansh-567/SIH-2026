# RF Signal Analysis Platform -- MVP Backend

SIH Problem Statement 26147 (NTRO) -- "Automated model for analysis of .IQ
and .wav files along with signal parameter extraction"

This is the **DSP/FEC/pipeline/API backend** for the platform described in
the accompanying architecture report (`SIH_26147_Architecture_Report.md`).
It is a working, tested foundation -- **not** the finished product. See
"What's not built yet" below before presenting this as complete.

## Status: 63/63 tests passing

```
pip install -r requirements.txt
python -m pytest tests/ -v
```

## What's implemented and verified

| Module | What it does | Tests |
|---|---|---|
| `rfplatform/models/schema.py` | The five-state honesty vocabulary (DETECTED/ESTIMATED/INFERRED/HYPOTHESIZED/UNKNOWN) as an enforced dataclass | — |
| `rfplatform/io/formats.py` | Memory-mapped WAV + raw IQ ingestion (cf32/cf64/cs16/cs8/cu8), SigMF sidecar support | via pipeline tests |
| `rfplatform/synth/generator.py` | Synthetic signal generator: BPSK/QPSK/8PSK/16QAM/64QAM/2FSK/4FSK with SNR, freq/phase/timing offsets, RRC pulse shaping | `test_synth_generator.py` |
| `rfplatform/dsp/estimators.py` | Noise floor, PSD/spectral features, IQ statistics, symbol-rate estimation, energy-based signal detection | `test_classifier_calibration.py` |
| `rfplatform/dsp/classifier.py` | Rule-based, explainable modulation classifier (family + exact order via M-th power method) | `test_classifier_calibration.py` |
| `rfplatform/dsp/demodulate.py` | PSK/QAM/FSK demodulators with matched filtering, carrier correction, EVM/lock metrics | `test_demodulate.py` |
| `rfplatform/fec/convolutional.py` | Convolutional coding + Viterbi (via scikit-commpy), hypothesis search | `test_fec.py` |
| `rfplatform/fec/reed_solomon.py` | Reed-Solomon (via reedsolo), syndrome-based self-verification | `test_fec.py` |
| `rfplatform/interleave/interleavers.py` | Block, convolutional, diagonal, pseudo-random (honestly unrecoverable without seed) | `test_interleave.py` |
| `rfplatform/pipeline/bitstream.py` | Entropy, sync-word/preamble correlation, periodic framing, byte alignment | `test_bitstream.py` |
| `rfplatform/pipeline/fusion.py` | Confidence-fusion engine (DSP + ML evidence combination, agreement/disagreement handling) | `test_fusion.py` |
| `rfplatform/pipeline/stages.py` | Full 17-stage pipeline orchestration, analyst-override support | `test_pipeline_integration.py` |
| `rfplatform/api/main.py` | FastAPI backend: `/upload`, `/analyze`, `/spectrogram`, `/health`, `/upload/{id}` (delete) | `test_api.py` |
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
curl -X POST http://127.0.0.1:8000/upload -F "file=@your_signal.cf32"
# -> {"file_id": "...", ...}
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
   downsampling -- a single RRC does not satisfy the zero-ISI Nyquist
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

None of these were caught by "does it import" or "does it run without
throwing" -- they only surfaced by testing against known ground truth
(exact bits in, exact bits expected out) and noticing when the numbers
were wrong. This is the same discipline the architecture report's PART 18
(testing strategy) calls for applied to the actual build.

## What's NOT built yet

- **ML classifier.** `pipeline/stages.py::_run_ml_classifier` is a
  documented stub returning `None`. The fusion engine already handles this
  gracefully (falls back to DSP-only with a note in the evidence trail),
  so wiring in a trained PyTorch/ONNX model later is a localized change,
  not a pipeline rewrite.
- **Multi-signal-per-file separation.** The pipeline currently analyzes the
  single largest detected region per file. Full time-frequency clustering
  for simultaneous multi-signal recordings is a documented roadmap item
  (architecture report PART 25).
- **Chunked/streaming analysis for very large files.** Ingestion is
  memory-mapped (correct for large files), but the detection/feature-
  extraction stages currently cap analysis at the first 2M samples per
  file for MVP responsiveness. Full chunked scanning across a multi-GB
  file is a documented roadmap item, not yet implemented.
- **Closed-loop timing/carrier recovery.** Current carrier/timing recovery
  is feed-forward/coarse (M-th power + fixed matched-filter offset), not a
  tracking Costas/Gardner loop -- adequate for the synthetic MVP test
  signals, not yet validated against drifting real-world signals.
- **LDPC and RS/conv concatenated-code decoding.** Architected for
  (registries support it) but not implemented -- `fec_hypotheses` currently
  only actually runs convolutional-code hypothesis search end-to-end in
  the pipeline; Reed-Solomon module exists and is tested standalone but
  isn't yet wired into `pipeline/stages.py`.
- **Report export (PDF/CSV/SigMF annotations).** Not implemented; `/analyze`
  returns JSON only.
- **Security hardening beyond basic upload validation.** Extension/size
  checks exist; process isolation, fuzz-testing against malformed files,
  and resource-exhaustion defenses are not yet implemented.

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
tests/                    63 tests, one file per module above
requirements.txt
```
