# LocalLexis — desktop UI design

Cross-platform desktop app for the existing `stt` CLI. Wraps the
`speechtotext` Python package in a Tauri shell with full feature
parity plus a transcript library, leaving room for Phase 2
summarize and RAG search.

Product name: **LocalLexis** (`/ˈloʊkəlˌlɛksɪs/`). The brand is
manuscript-themed — ink, marginalia, hand-set type — and the
dominant product signal is privacy: nothing leaves the machine.

## Goals

- Cover every CLI workflow (transcribe, record, watch, relabel,
  config) through a GUI for users who do not live in a terminal.
- Make past transcripts a first-class object: browseable, searchable,
  re-openable from disk.
- Keep the `.json` sidecar on disk as the source of truth. The UI is
  a view over the filesystem, not a new database.
- Provide a stable HTTP contract that Phase 2 features (summarize,
  RAG) can extend without touching the frontend.
- Ship on macOS, Windows, and Linux with a single codebase.

## Non-goals

- Cloud sync, multi-user accounts, server deployment.
- Re-implementing ML logic. The UI calls existing `Pipeline.run()`.
- Real-time streaming transcription of microphone input.
  Record-then-transcribe is enough.
- Mobile-responsive layout. Desktop only.

## Visual design — see handoff

The complete visual design (layout, typography, color tokens, copy,
component structure) is defined in the handoff under
[docs/design_handoff_locallexis/](../../design_handoff_locallexis/).
That folder contains:

- `README.md` — narrative handoff: what's high-fi, what's stub,
  every screen's layout in precise detail.
- `LocalLexis-standalone.html` — runnable prototype (double-click
  to open offline).
- `app.jsx`, `sidebar.jsx`, `screens.jsx`, `primitives.jsx`,
  `tweaks-panel.jsx` — split source for the prototype.
- `styles.css` — all design tokens and component styles.
- `spec.md` — older copy of this spec.

That handoff is the canonical reference for **how the UI looks**.
This spec is the canonical reference for **how the UI is wired**.

Production stack: **Tauri + React + Vite**. The handoff HTML uses
Babel-in-browser to keep the prototype self-contained — production
recreates the same visuals with a normal build pipeline.

**Design fidelity status:**

| Screen        | Status                                          |
| ------------- | ----------------------------------------------- |
| Idle          | High-fi, recreate pixel-close                   |
| Record        | High-fi, recreate pixel-close                   |
| Complete      | High-fi, recreate pixel-close                   |
| In progress   | **Not designed** — design before building       |
| Library       | Stub placeholder — design before building       |
| Watch folder  | Stub placeholder — design before building       |
| Settings      | Stub placeholder — design before building       |

The in-progress state and the three stubbed screens are open
design work that lands during their respective build steps.

## Architecture

Three layers, each with a clear contract:

```
┌─────────────────────────────────────────────────┐
│  UI    Tauri shell + React frontend             │
│        Sidebar, screens per the handoff         │
└──────────────────────┬──────────────────────────┘
                       │ REST + Server-Sent Events
                       │ over localhost:<random>
┌──────────────────────┴──────────────────────────┐
│  API   FastAPI server (bundled sidecar)         │
│        Job orchestration, transcript index      │
└──────────────────────┬──────────────────────────┘
                       │ Python imports
┌──────────────────────┴──────────────────────────┐
│  ML    speechtotext package (unchanged)         │
│        Pipeline, ASR, diarize, ingest, writer   │
└─────────────────────────────────────────────────┘
```

**Why three layers, not two:**

- A direct Tauri-to-Python subprocess model can launch jobs but
  cannot stream live progress without parsing stdout. A persistent
  HTTP server with SSE is a clean fit and the natural home for
  `/summarize` and `/search` endpoints later.
- A Rust-rewrite of the ML layer abandons the existing Python
  codebase and its model integrations. Not worth it.

**Packaging:** Tauri bundles the FastAPI process as a sidecar
binary built with PyInstaller (or a uv-managed standalone runtime).
On launch, Tauri starts the sidecar on a random local port, passes
the URL to the frontend, and terminates the sidecar on quit. No
separate Python install required for end users.

## UI layer

The UI is a single window split into a fixed-width left sidebar
(232 px) and a flexible main panel. macOS chrome (titlebar with
traffic lights) is on by default, togglable. The handoff is
canonical for visual detail; this section names the screens and
states each one needs to wire up.

### Sidebar (constant)

- Brand block: "LocalLexis" wordmark + pronunciation guide.
- `+ New transcription` primary button (`⌘N`).
- Nav: Transcribe · Record · Watch folder · Library (count badge)
  · Settings. Active item shows an accent-green marginalia tick.
- Recent list (~5 transcripts) under a `RECENT` mono label. Click a
  row → deep-links to the Complete view for that transcript.
- Footer: "All processing on-device" line with a pulsing accent dot.

Recording state replaces any Record nav badge with a pulsing live
dot. Watch state is similar.

### Main header (constant)

- Route crumb + title on the left.
- Right cluster of `24 px` pill chips:
  - On Complete: `Done in 4:12` (check icon).
  - On Record: `Live` (pulsing dot, accent variant).
  - Always: `On-device` (lock icon). The persistent privacy signal.

### Screen states

**Idle (`/transcribe`)** — high-fi.
- Hero `"What did you say?"`, subhead, drop zone, options row
  (Language / Speakers / Backend), Recent files list, etymology
  flourish card.
- Drag + drop and Browse click both `POST /jobs/transcribe`, then
  navigate to the In-progress state.

**In progress (`/jobs/{id}`)** — **needs design**. Will reuse the
Complete view's transcript typography with a top progress strip +
the stage list (`Load → Diarize → Transcribe → Merge → Write`) as
a row of chips. Live lines stream into the transcript area as they
arrive over SSE.

**Complete (`/transcripts/{id}`)** — high-fi.
- Doc head: file path, transcript title, model/duration/speakers
  meta line, action icon buttons (Copy / Open .txt / Open .json).
- Relabel row: speaker swatches + name inputs + Apply button.
  Wires to `PATCH /transcripts/{id}/relabel` with `{SPEAKER_00:
  "Alice", …}`.
- Transcript body: 3-col grid (timestamp gutter, speaker block,
  paragraph) or single-column "inline" layout — togglable. Comfy /
  Compact density toggle.

**Record (`/record`)** — high-fi.
- Device pill (wires to `GET /devices`).
- Lexis canvas (animated SVG waveform).
- Status label + mono timer.
- Pause / Record / Discard controls. Record start → `POST
  /jobs/record`. Stop → `POST /jobs/{id}/stop`, auto-chains into the
  In-progress state for the resulting WAV.
- Privacy line at the bottom showing the absolute output path.

**Library (`/library`)** — **stub, needs design**.
- Spec: search box + transcript list, one row per `.json` sidecar.
  Click → Complete view.
- Wires to `GET /transcripts`.

**Watch folder (`/watch`)** — **stub, needs design**.
- Spec: folder picker, start/stop toggle, recent-events log.
- Wires to `POST /watch/start`, `POST /watch/stop`, `GET
  /watch/status`.

**Settings (`/settings`)** — **stub, needs design**.
- Spec: form editor for `config.toml` (backend, asr_model,
  hf_token, model_cache_dir, watch.debounce_seconds).
- Wires to `GET /config`, `PATCH /config`.

### Design tokens

The full token list lives in
[docs/design_handoff_locallexis/styles.css](../../design_handoff_locallexis/styles.css)
and the handoff README. Production should expose them as CSS custom
properties on `:root` (or the equivalent in the chosen styling
system) and never hardcode hex values.

Key tokens (full list in handoff):

- Backgrounds: `--bg #0c0c0d`, `--bg-sidebar #08080a`, `--bg-elev
  #131315`, `--bg-active #1f1f22`.
- Ink: `--ink #ece9e1` (primary, warm off-white), `--ink-muted
  #a8a59b`, `--ink-dim #65635c`.
- Accent: `--accent #6fd99a` (sage/quill green), `--accent-faint`
  (10% alpha), `--accent-line` (35% alpha).
- States: `--warn #d97757`, `--danger #e0584b`.
- Speaker palette (5 round-robin hues): `#6fd99a · #e8b169 ·
  #7aa5e8 · #d97e94 · #c2a3e8`.
- Fonts: Newsreader (serif/display), Geist (sans/UI), Geist Mono
  (labels/timestamps). All from Google Fonts.

The Tweaks panel in the prototype is **not part of the product** —
it exists to compare design variants during handoff review.

## API layer (FastAPI)

A small set of endpoints wrapping the existing `Pipeline` and
`speechtotext` modules.

| Method | Path                          | Purpose                                  |
| ------ | ----------------------------- | ---------------------------------------- |
| POST   | `/jobs/transcribe`            | Start a job for an existing audio file   |
| POST   | `/jobs/record`                | Start a recording job (returns `job_id`) |
| POST   | `/jobs/{id}/stop`             | Stop an in-flight recording              |
| GET    | `/jobs/{id}`                  | Snapshot of job state                    |
| GET    | `/jobs/{id}/stream`           | SSE stream of progress events            |
| GET    | `/transcripts`                | List all `.json` sidecars (library)      |
| GET    | `/transcripts/{id}`           | Full transcript JSON                     |
| PATCH  | `/transcripts/{id}/relabel`   | Apply a speaker map                      |
| GET    | `/devices`                    | Audio inputs (wraps `list_inputs()`)     |
| GET    | `/config`                     | Current config                           |
| PATCH  | `/config`                     | Update + persist config                  |
| POST   | `/watch/start`                | Start the watch-folder daemon            |
| POST   | `/watch/stop`                 | Stop the watch-folder daemon             |
| GET    | `/watch/status`               | Watcher state + recent events            |

Phase 2 placeholders (not built now, but the contract is reserved):

| Method | Path                            | Purpose           |
| ------ | ------------------------------- | ----------------- |
| POST   | `/transcripts/{id}/summarize`   | Local summary     |
| POST   | `/search`                       | RAG Q&A           |

**SSE event shape:**

```json
{ "type": "stage",    "stage": "transcribe", "percent": 62 }
{ "type": "line",     "speaker": "SPEAKER_00", "ts": 12.3, "text": "..." }
{ "type": "complete", "transcript_id": "meeting-2026-05-15", "paths": {"txt": "...", "json": "..."} }
{ "type": "error",    "message": "..." }
```

The shape mirrors the existing `progress.py` renderers, so progress
plumbing inside `Pipeline.run()` does not change.

## ML layer (unchanged)

The existing `speechtotext` package is consumed as-is. The FastAPI
endpoints import `Pipeline`, `FasterWhisperASR`, `PyannoteDiarizer`,
`record_to_wav`, `run_watch`, `list_inputs`, `write_transcript`,
`relabel`, and `load_config`. No changes to the ML layer are
required for v1.

## Frontend state

Per the handoff, expect roughly:

- A top-level router (current screen).
- A `jobs` store keyed by `job_id`, holding `{ status, stage,
  percent, transcript: [...], error? }`. Populated from SSE.
- A `transcripts` store keyed by transcript id, lazily populated
  from `GET /transcripts/{id}`. Updated optimistically on relabel.
- A `library` store — array of transcript metadata from `GET
  /transcripts`, refreshed on `complete` events.
- A `recording` store — `{ active, paused, elapsed, deviceId,
  jobId? }`.
- A `config` store — read once on launch, mutated via `PATCH
  /config`.

All other UI state (open dropdowns, drag-over, input focus, etc.)
is local component state. Specific store library (Zustand, Jotai,
Redux Toolkit, plain Context) is a planning-time decision.

## Data flow

**Transcribing a dropped file:**

1. User drops `meeting.mp3` on the drop zone.
2. Frontend `POST /jobs/transcribe` with `{path, language?,
   num_speakers?, backend?}`.
3. API generates a `job_id`, spawns a background thread running
   `Pipeline.run()` with an `on_progress` callback that pushes
   events onto a per-job queue.
4. Frontend navigates to the In-progress view and opens `GET
   /jobs/{id}/stream` (SSE). API drains the queue and sends events.
5. On completion, the existing `write_transcript()` writes
   `meeting.txt` + `meeting.json` next to the audio file. API
   sends the `complete` event with sidecar paths.
6. Frontend transitions to the Complete view. Library re-fetches on
   next visit.

**Recording then transcribing:**

1. `POST /jobs/record` with `{device?, out?}`. API starts
   `record_to_wav()` in a thread.
2. `POST /jobs/{id}/stop`. API sets the stop event, waits for the
   WAV header to finalize.
3. API auto-chains into a transcribe job using the recording's
   path. Frontend follows the new `job_id` into the In-progress
   view.

**Library:**

- `GET /transcripts` scans output directories (config setting;
  default is the watch folder + any directory that contains a
  `.json` file the user has previously opened). Each sidecar is
  parsed for metadata (duration, speakers, date) and cached in
  memory.
- No SQLite, no separate index file. The `.json` sidecars are the
  index.

**Relabeling:**

- `PATCH /transcripts/{id}/relabel` with `{SPEAKER_00: "Alice",
  ...}` calls the existing `relabel_module.relabel()` which
  rewrites both the `.json` and `.txt` files. Frontend re-fetches
  the transcript.

## Error handling

- Job failure inside `Pipeline.run()` → API catches, emits an SSE
  `error` event, marks job state failed. Frontend shows an inline
  error banner with the message + a Retry button. The job stays in
  the sidebar's Recent list with a red badge until dismissed.
- Missing Hugging Face token at startup → API `GET /config`
  returns `hf_token_set: false`. Frontend shows a one-time
  onboarding banner on first launch pointing at the Settings panel.
- Sidecar parse failure in the library → the row renders with a
  warning badge; the transcript still opens but speaker/duration
  metadata reads "unknown".
- Watch-folder errors → the existing `.stt-error.txt` sidecar
  mechanism is preserved. The library surfaces failed entries with
  a red badge.

## Testing

- **API layer:** `pytest` with `httpx.AsyncClient` against the
  FastAPI app. No Tauri, no browser. Mock the `Pipeline` for fast
  tests; one integration test wires up the existing `whisper-tiny`
  fixture end-to-end.
- **Frontend:** Vitest + React Testing Library for component-level
  tests (drop zone behavior, progress rendering, relabel form
  validation, waveform render-without-crash). API calls go through
  a thin client module that is easy to mock.
- **Tauri shell:** smoke test only — verify the app launches and
  the sidecar process starts and stops cleanly. No E2E
  click-driving in v1.
- The existing `pytest -m "not integration"` fast suite stays
  fast. All new ML-heavy tests live under `-m integration`.

## Build sequence (v1 milestones)

1. FastAPI app module (`speechtotext.api`) exposing the endpoints
   above. Tests against an in-process client. The CLI still works
   unchanged.
2. PyInstaller / uv packaging of the FastAPI app as a standalone
   binary. CI builds for macOS, Windows, Linux.
3. Tauri + Vite + React project scaffold. Set up the design
   tokens, fonts (Newsreader / Geist / Geist Mono), window chrome,
   sidebar component matching the handoff. Wire to start/stop the
   sidecar.
4. **Idle screen** (high-fi from handoff). Drop zone + options +
   Recent list + etymology card. Browse / drop both navigate
   forward.
5. **Design the In-progress state**, then build it. Progress strip
   + stage chips + live transcript area. Subscribes to SSE.
6. **Complete screen** (high-fi from handoff). Doc head + relabel
   row + transcript body with margin/inline + comfy/compact
   variants.
7. **Record screen** (high-fi from handoff). Device pill +
   animated waveform + timer + controls. Auto-chains into the
   In-progress state on stop.
8. **Design the Library screen**, then build it. Search + list of
   transcripts.
9. **Design the Watch folder screen**, then build it. Folder
   picker + status + event log.
10. **Design the Settings screen**, then build it. Form editor for
    `config.toml`.
11. Phase 2 endpoints — out of scope for this design.

Each "design X, then build it" step produces a short design note
(or screenshot annotation) committed under
`docs/design_handoff_locallexis/` before that build step starts,
so the high-fi reference stays complete as the app grows.

## Open questions

None at design time. Open questions surface during planning go in
the implementation plan, not here.
