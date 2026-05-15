# stt desktop UI — design

Cross-platform desktop UI for the existing `stt` CLI. Wraps the
`speechtotext` Python package in a Tauri shell with full feature parity
plus a transcript library, leaving room for Phase 2 summarize and RAG
search.

## Goals

- Cover every CLI workflow (transcribe, record, watch, relabel, config)
  through a GUI for users who do not live in a terminal.
- Make past transcripts a first-class object: browseable, searchable,
  re-openable from disk.
- Keep the `.json` sidecar on disk as the source of truth. The UI is a
  view over the filesystem, not a new database.
- Provide a stable HTTP contract that Phase 2 features (summarize,
  RAG) can extend without touching the frontend.
- Ship on macOS, Windows, and Linux with a single codebase.

## Non-goals

- Cloud sync, multi-user accounts, server deployment.
- Re-implementing ML logic. The UI calls existing `Pipeline.run()`.
- Real-time streaming transcription of microphone input. Record-then-
  transcribe is enough.
- A pixel-perfect mobile-responsive layout. Desktop only.

## Architecture

Three layers, each with a clear contract:

```
┌─────────────────────────────────────────────────┐
│  UI    Tauri shell + React frontend             │
│        Sidebar, job view, library, settings     │
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

- A direct Tauri-to-Python subprocess model can launch jobs but cannot
  stream live progress without parsing stdout. A persistent HTTP
  server with SSE is a clean fit and the natural home for `/summarize`
  and `/search` endpoints later.
- A Rust-rewrite of the ML layer abandons the existing Python codebase
  and its model integrations. Not worth it.

**Packaging:** Tauri bundles the FastAPI process as a sidecar binary
built with PyInstaller (or a uv-managed standalone runtime). On
launch, Tauri starts the sidecar on a random local port, passes the
URL to the frontend, and terminates the sidecar on quit. No separate
Python install required for end users.

## Components

### UI layer (Tauri + React)

Single window, two-pane: dark sidebar on the left, white main panel
on the right.

**Sidebar (constant across all views):**

- App title.
- `+ New` primary button.
- Nav links: Transcribe, Record, Watch folder, Library, Settings.
- "Recent" section showing the last ~10 transcripts.

**Main panel — four primary states:**

1. **New transcription (idle).** Drop zone, optional language /
   speakers / backend selectors. Drag-and-drop a file, or click to
   browse.
2. **In progress.** Header shows filename + duration. Below: a
   progress bar, the pipeline stage list (`Load → Diarize →
   Transcribe → Merge → Write`) with the active stage highlighted,
   and a live-streaming transcript box that appends lines as the ASR
   produces them.
3. **Complete.** Same header. Inline speaker relabel row
   (`SPEAKER_00 → [Alice]  SPEAKER_01 → [Bob]  [Apply]`). Below: the
   transcript rendered with timestamps and speaker labels. Action
   buttons: Copy, Open .txt, Open .json.
4. **Library.** Search box at the top. Below: a list of all known
   transcripts (one row per `.json` sidecar) with filename, duration,
   speaker count, date, and status badge. Click a row to open it
   in state 3.

**Secondary views:**

- **Record** (sidebar nav). Device picker (calls `GET /devices`),
  big red Record button, elapsed-time readout, Stop button. On stop,
  the recording flows into state 2 of the transcribe view.
- **Watch folder.** Folder picker, toggle to start/stop the watcher,
  log of recent file events. While running, new files appear as
  in-progress jobs in the sidebar.
- **Settings.** Form-style editor for the existing `config.toml`
  fields (`backend`, `asr_model`, `hf_token`, `model_cache_dir`,
  `watch.debounce_seconds`). Save calls `PATCH /config`.

### API layer (FastAPI)

A small set of endpoints wrapping the existing `Pipeline` and
`speechtotext` modules.

| Method | Path                                | Purpose                                     |
| ------ | ----------------------------------- | ------------------------------------------- |
| POST   | `/jobs/transcribe`                  | Start a job for an existing audio file      |
| POST   | `/jobs/record`                      | Start a recording job (returns `job_id`)    |
| POST   | `/jobs/{id}/stop`                   | Stop an in-flight recording                 |
| GET    | `/jobs/{id}`                        | Snapshot of job state                       |
| GET    | `/jobs/{id}/stream`                 | SSE stream of progress events               |
| GET    | `/transcripts`                      | List all `.json` sidecars (library)         |
| GET    | `/transcripts/{id}`                 | Full transcript JSON                        |
| PATCH  | `/transcripts/{id}/relabel`         | Apply a speaker map                         |
| GET    | `/devices`                          | Audio inputs (wraps `list_inputs()`)        |
| GET    | `/config`                           | Current config                              |
| PATCH  | `/config`                           | Update + persist config                     |
| POST   | `/watch/start`                      | Start the watch-folder daemon               |
| POST   | `/watch/stop`                       | Stop the watch-folder daemon                |
| GET    | `/watch/status`                     | Watcher state + recent events               |

Phase 2 placeholders (not built now, but the contract is reserved):

| Method | Path                                       | Purpose            |
| ------ | ------------------------------------------ | ------------------ |
| POST   | `/transcripts/{id}/summarize`              | Local summary      |
| POST   | `/search`                                  | RAG Q&A            |

**SSE event shape:**

```json
{ "type": "stage",    "stage": "transcribe", "percent": 62 }
{ "type": "line",     "speaker": "SPEAKER_00", "ts": 12.3, "text": "..." }
{ "type": "complete", "transcript_id": "meeting-2026-05-15", "paths": {"txt": "...", "json": "..."} }
{ "type": "error",    "message": "..." }
```

The shape mirrors the existing `progress.py` renderers, so progress
plumbing inside `Pipeline.run()` does not change.

### ML layer (unchanged)

The existing `speechtotext` package is consumed as-is. The FastAPI
endpoints import `Pipeline`, `FasterWhisperASR`, `PyannoteDiarizer`,
`record_to_wav`, `run_watch`, `list_inputs`, `write_transcript`,
`relabel`, and `load_config`. No changes to the ML layer are required
for v1.

## Data flow

**Transcribing a dropped file:**

1. User drops `meeting.mp3` on the drop zone.
2. Frontend `POST /jobs/transcribe` with `{path, language?, num_speakers?, backend?}`.
3. API generates a `job_id`, spawns a background thread running
   `Pipeline.run()` with an `on_progress` callback that pushes events
   onto a per-job queue.
4. Frontend opens `GET /jobs/{id}/stream` (SSE). API drains the queue
   and sends events.
5. On completion, the existing `write_transcript()` writes
   `meeting.txt` + `meeting.json` next to the audio file. API sends
   the `complete` event with sidecar paths.
6. Library panel re-scans configured output dirs; the new transcript
   appears in the recent list.

**Recording then transcribing:**

1. `POST /jobs/record` with `{device?, out?}`. API starts
   `record_to_wav()` in a thread.
2. `POST /jobs/{id}/stop`. API sets the stop event, waits for the WAV
   header to finalize.
3. API auto-chains into a transcribe job using the recording's path.
   Frontend follows the new `job_id`.

**Library:**

- `GET /transcripts` scans output directories (config setting; default
  is the watch folder + any directory that contains a `.json` file the
  user has previously opened). Each sidecar is parsed for metadata
  (duration, speakers, date) and cached in memory.
- No SQLite, no separate index file. The `.json` sidecars are the
  index.

**Relabeling:**

- `PATCH /transcripts/{id}/relabel` with `{SPEAKER_00: "Alice", ...}`
  calls the existing `relabel_module.relabel()` which rewrites both
  the `.json` and `.txt` files. Frontend re-fetches the transcript.

## Error handling

- Job failure inside `Pipeline.run()` → API catches, emits an SSE
  `error` event, marks job state failed. Frontend shows an inline
  error banner with the message + a Retry button. The job stays in
  the sidebar's recent list with a red badge until dismissed.
- Missing Hugging Face token at startup → API `GET /config` returns
  `hf_token_set: false`. Frontend shows a one-time onboarding banner
  on first launch pointing at the Settings panel.
- Sidecar parse failure in the library → the row renders with a
  warning badge; the transcript still opens but speaker/duration
  metadata reads "unknown".
- Watch-folder errors → the existing `.stt-error.txt` sidecar
  mechanism is preserved. The library surfaces failed entries with a
  red badge.

## Testing

- **API layer:** `pytest` with `httpx.AsyncClient` against the
  FastAPI app. No Tauri, no browser. Mock the `Pipeline` for fast
  tests; one integration test wires up the existing `whisper-tiny`
  fixture end-to-end.
- **Frontend:** Vitest + React Testing Library for component-level
  tests (drop zone behavior, progress rendering, relabel form
  validation). API calls go through a thin client module that is easy
  to mock.
- **Tauri shell:** smoke test only — verify the app launches and the
  sidecar process starts and stops cleanly. No E2E click-driving in
  v1.
- The existing `pytest -m "not integration"` fast suite stays fast.
  All new ML-heavy tests live under `-m integration`.

## Build sequence (v1 milestones)

1. FastAPI app module (`speechtotext.api`) exposing the endpoints
   above. Tests against an in-process client. The CLI still works
   unchanged.
2. PyInstaller / uv packaging of the FastAPI app as a standalone
   binary. CI builds for macOS, Windows, Linux.
3. Tauri project scaffold with React. Sidebar + idle state. Wired to
   start/stop the sidecar.
4. Transcribe flow end-to-end: drop file, see progress, see result.
5. Library view (read-only).
6. Relabel + settings + device picker.
7. Record view.
8. Watch folder view.
9. Phase 2 endpoints — out of scope for this design.

## Open questions

None at design time. Open questions surface during planning go in
the implementation plan, not here.
