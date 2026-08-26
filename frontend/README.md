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

Built around one idea: **the waterfall/spectrogram colormap gradient is
already this domain's own visual signature** -- so rather than picking an
arbitrary accent color, the same 5-stop gradient (indigo -> blue -> teal ->
amber -> red) that colors the spectrogram is reused throughout the UI: as
confidence bars, the header accent line, and hypothesis-table highlights.
This ties the whole interface back to something that is unmistakably "RF
analysis tool" rather than a generic dark dashboard template.

The five-state honesty vocabulary (DETECTED/ESTIMATED/INFERRED/
HYPOTHESIZED/UNKNOWN) gets its own distinct color scale (cool/certain ->
warm/uncertain, cyan through orange to neutral gray for UNKNOWN) rather than
a generic green/red pass-fail treatment -- this is deliberate: a pass/fail
color scheme would visually lie about a spectrum of certainty that the
whole architecture is built to represent honestly.

Typography: **Space Grotesk** for headings (technical, slightly
distinctive), **Inter** for body/labels, **JetBrains Mono** for every
number, hex byte, and bit value -- an RF analysis tool is fundamentally
about numbers and raw data, so those get a dedicated monospace treatment
throughout rather than inheriting the body font.

## What's implemented

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
- Analyst-in-the-loop: sample-rate/modulation override inputs, visible
  confirmation of which values were analyst-set vs. automatic, one-click
  re-run

## What's NOT implemented yet

- No constellation plot (backend doesn't yet expose recovered symbol I/Q
  points over the wire -- `demod_result` currently returns bits, not
  symbols; a follow-up backend change plus a scatter-plot component would
  close this gap)
- No time-domain I/Q waveform view
- No comparison mode (recording A vs B)
- No report export (PDF/CSV/SigMF annotations) -- UI or backend
- No live progressive rendering during analysis (the "Analyzing..." button
  state exists, but results appear all at once when the single `/analyze`
  call resolves, rather than panel-by-panel as each pipeline stage
  completes -- true progressive rendering needs a WebSocket/SSE endpoint
  the backend doesn't have yet)
- Not yet tested against a very large (multi-GB) file's upload UX
  (progress bar, chunked upload) -- current upload is a single
  `fetch`/`FormData` call with no progress indicator
