# RF Signal Analysis Platform -- Frontend

React + TypeScript + Vite GUI for the backend in `../rfplatform`.

## Running

Terminal 1 (backend, from the repo root):
```bash
uvicorn rfplatform.api.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 (frontend):
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The Vite dev server proxies `/api/*` to the
backend on port 8000 (see `vite.config.ts`) -- no CORS configuration needed
in development.

Build check performed during development: `npx tsc -b` (clean) and
`npm run build` (clean, 171KB JS / 2.3KB CSS gzipped) -- both verified in
this repo's build environment. **Not yet verified: a live browser render.**
This environment has no display/browser available to screenshot against,
so the visual layout has been built carefully against the design system
below but has not been visually confirmed pixel-by-pixel. Please sanity-check
the actual rendered UI before a live demo.

## Design system

The product is called **Modulus**. The name, wordmark and all copy live in
`src/App.tsx` and `src/theme.css` — there is no hackathon or organisation
branding anywhere in the interface, deliberately: it should read as an
instrument someone bought, not an entry someone submitted.

**The design concept: this is an instrument, and its subject is measurement
under uncertainty.** Every choice below follows from that.

1. **Certainty is encoded in the typography, not just a coloured label.**
   This is the one bold idea, and everything else stays quiet to let it
   land. A `DETECTED` value renders solid at full weight; `INFERRED` is
   slightly lighter; `UNKNOWN` is hollow, lighter still, and italic (see
   `.value-*` in `theme.css`). You can scan a column of findings and see
   what the system is sure of without reading a single status word — the
   word is confirmation, not the signal.
2. **The UI chrome is near-monochrome warm graphite, and that is a rule
   with a reason.** The only saturated colour in the entire interface is
   the five-state confidence vocabulary and the spectrogram's own
   colormap. In a tool where colour *means* confidence, decorative colour
   would be lying to the analyst.
3. **Findings are a ledger, not a card grid.** Hairline-separated rows on a
   fixed column rhythm so values align and can be compared vertically.
   Identical rounded cards would scatter the numbers.
4. **Confidence reads as a tick scale**, not a progress bar — instruments
   read in graduations.
5. **Radius is assigned by role**: data surfaces are near-square (2px,
   they're readouts), controls are softer (5px, you touch them). One
   radius on everything is a tell, not a decision.
6. **Type: IBM Plex Sans + IBM Plex Mono.** Engineering heritage, real
   character, excellent tabular numerals with a slashed zero — and
   deliberately not the Inter/Geist default. Every number in the interface
   is tabular so columns line up.
7. **The header is a readout strip.** When a recording is loaded it shows
   sample rate, centre frequency, duration, format and signal count at all
   times — an instrument shows its operating conditions, it doesn't show
   marketing copy. Unset values render hollow rather than as "0".
8. **A status bar** reports pipeline state, stages run/skipped and warning
   count. Press 1–4 to move between views.

Deliberately avoided, because they are the common tells of generated UI:
tracked-out ALL-CAPS eyebrow labels, `A · B · C` meta strings, gradient
washes used as button fills, a single border-radius on everything, and
decorative colour with no meaning. The codebase is grep-clean of all five.

Accessibility floor: visible keyboard focus rings, `prefers-reduced-motion`
respected, and colour is never the sole carrier of meaning (status is
always also stated in words and in type weight).

## What's implemented## What's implemented

- File ingestion (drag-and-drop + click-to-browse)
- Recording summary (format, sample rate, duration, metadata trust status)
- Waterfall/spectrogram (canvas-rendered, using the signature colormap)
- Pipeline stage progress (vertical stepper, live per-stage status/timing)
- Automatic Analysis panel: one card per extracted parameter, with status
  badge, confidence bar, and an expandable **evidence trail** -- this is
  the direct visual expression of the confidence-fusion/explainability
  differentiator from the architecture report
- Demodulation panel: EVM/lock-quality gauges, recovered bit preview
- FEC & de-interleaving panel: ranked hypothesis tables, honest
  "unrecoverable" messaging for pseudo-random interleaving
- Bit-stream panel: hex/ASCII view, sync-word matches, framing hypotheses
- Analyst-in-the-loop: sample-rate/modulation/center-frequency override
  inputs, visible confirmation of which values were analyst-set vs.
  automatic, one-click re-run
- SigMF pair upload: multi-file dropzone, auto-pairs `.sigmf-data` +
  `.sigmf-meta` by filename, shows pairing status
- Export Report panel: PDF/JSON/CSV/SigMF download buttons, each
  triggering a real browser download of the current analysis
- **Four-tab navigation: Analyze / History / Batch / Compare.**
  - **History** -- browse every persisted analysis, reopen one (loads via
    `GET /analyses/{id}`; the waterfall honestly shows "not available" for
    a reopened historical entry rather than trying to re-fetch a spectrogram
    for a file that may no longer be uploaded), delete entries, select two
    for comparison.
  - **Batch** -- multi-file dropzone, uploads and analyzes each file via
    `/batch/analyze`, results table with per-file success/failure and a
    click-through to open any result in the Analyze tab.
  - **Compare** -- pick two history entries, see a parameter-by-parameter
    diff table (color-coded: same / changed / only-in-A / only-in-B).
  - **Inline analyst corrections** -- every `ParameterCard`'s expanded
    evidence view has a "Disagree? Submit a correction" affordance, posting
    to `/analyses/{id}/feedback` and visibly confirming once recorded.
  - **Similar Signals panel** -- shown alongside any analysis result,
    fingerprint-based nearest-neighbor search across history, click-through
    to open a similar signal's own analysis.

## What's NOT implemented yet

- **Waterfall click-to-annotate.** The backend (`/analyses/{id}/annotations`)
  is fully built and tested; the canvas has no click handler wired to it
  yet, so there's no way to mark a time/frequency region from the GUI.
- No constellation plot (backend doesn't yet expose recovered symbol I/Q
  points over the wire -- `demod_result` currently returns bits, not
  symbols; a follow-up backend change plus a scatter-plot component would
  close this gap)
- No time-domain I/Q waveform view
- No live progressive rendering during analysis (the "Analyzing..." button
  state exists, but results appear all at once when the single `/analyze`
  call resolves, rather than panel-by-panel as each pipeline stage
  completes -- true progressive rendering needs a WebSocket/SSE endpoint
  the backend doesn't have yet)
- Not yet tested against a very large (multi-GB) file's upload UX
  (progress bar, chunked upload) -- current upload is a single
  `fetch`/`FormData` call with no progress indicator
