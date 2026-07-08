# WebUI Enhancements — Design

Date: 2026-07-07
Status: approved (pending user review of this document)
Scope: web UI (hub-served) + desktop (Tauri). Android parity is an explicit follow-up, out of scope here.

## Context

The web UI and desktop app share one React codebase under `ui/src`. Vite `hub` mode swaps
`App.web.tsx` for `App.tsx` and `platform/web.ts` for `platform/tauri.ts`, and emits built assets
to `speechtotext/webui/`, which the FastAPI hub serves at `/app/`. Features implemented in shared
screens (`LibraryScreen`, `CompleteScreen`) and shared components therefore land on both platforms.

Transcript JSON (schema v2, `speechtotext/writer.py`) is canonical and carries CRDT metadata
(`_workspace_id`, `_clocks`, `_history`); the SQLite/FTS index is rebuildable. Multi-device edits
must flow through the existing CRDT PATCH mechanism (`PATCH /transcripts/{tid}` with
`{op, key, value, lamport_observed}`).

Lemonade (LLM server) runs on the homelab host as `lemond.service`, listening on
`127.0.0.1:13305`, OpenAI-compatible API under `/api/v1`, no API key configured. Models already
downloaded include `Qwen3-30B-A3B-Instruct-2507-GGUF` (default choice), `Qwen3-8B-GGUF`,
`Gemma-4-12B-it-QAT-Q4_0`, `Ornith-1.0-35B/9B`.

## Features

### 1. Transcription activity indicator (web)

- New hub endpoint: `GET /jobs?active=true` — lists pending/running jobs (id, kind, stage,
  percent, source name).
- Web shell header gets a persistent activity chip: spinner + "Transcribing <name> — NN%" while
  any job is active, fed by the existing per-job SSE stream with 3–5 s polling fallback (poll only
  while the tab is visible). Idle → chip hidden.
- Covers watch-folder jobs and device/upload ingests, since it reads the hub job registry.

### 2. Audio access (play + download)

- New hub endpoint: `GET /transcripts/{tid}/audio` — authenticated, resolves `audio_path` from the
  transcript doc, streams the file with HTTP Range support and correct content-type. 404 if the
  audio file is missing.
- `CompleteScreen` (shared): audio player + download button. The file is fetched with the
  authenticated `api()` client as a blob and mounted as an object URL, so `<audio>` needs no auth
  changes and seeking works. Clicking a segment seeks the player to `segment.start`.
- Download uses the same blob with the recording title as filename.

### 3. Settings expansion (web) + shared settings form

- Extract the desktop settings form fields into a shared component (used by `SettingsScreen` and
  `WebSettingsScreen`): backend (`auto/cpu/cuda/mps`), ASR model dropdown (from
  `GET /models/whisper`), watch folder options (recursive, debounce seconds, extensions).
- Web mounts it against the hub's existing `GET /config` / `PATCH /config`; desktop behavior
  unchanged. Pairing sections stay platform-specific.
- New **Summarization** settings section on both platforms (see feature 8): provider
  (`lemonade | openrouter | custom`), base URL, model, API key (write-only display). When the
  provider endpoint is reachable, the model field becomes a dropdown populated from its
  `/models` listing; otherwise free text.
- New **Trash** section (see feature 9).

### 4. Rename recordings

- New `title` field in transcript JSON, set via the existing CRDT PATCH op
  (`op: "set", key: "title"`), so renames sync like speaker relabels. Files on disk are untouched.
- `library_db` indexes `title`; FTS search matches it; `TranscriptListItem` carries it.
- UI (shared): inline rename in `LibraryScreen` (pencil icon) and editable title in
  `CompleteScreen` header. Falls back to the audio filename stem when unset.

### 5. Date + time display

- `LibraryScreen` renders `created_at` as localized date **and** time (e.g. "7 Jul 2026, 14:32")
  instead of the current date-only slice.

### 6. Per-line transcript edits

- Edit affordance per segment in `CompleteScreen`: click pencil → inline input → save on
  Enter/blur, Escape cancels.
- New CRDT op `edit_segment` with `{index, text}`; hub applies last-writer-wins per segment index,
  updates `segments[i].text`, rewrites the `.txt` sidecar, reindexes FTS, and appends to
  `_history`.

### 7. In-transcript search

- Search box in `CompleteScreen`: client-side, highlights matches across segment text, shows match
  count, next/prev buttons (and Enter/Shift+Enter) jump between matches with scroll-into-view.
  No backend changes.

### 8. Summarization (Lemonade, provider-pluggable)

**Architecture: backend provider abstraction.**

- New module `speechtotext/summarize/`:
  - `LlmProvider` protocol: `chat(messages, model, **opts) -> str` + `list_models() -> list[str]`.
  - `OpenAICompatProvider(base_url, api_key, model)` — the only implementation needed now; it
    covers Lemonade, OpenRouter, and any OpenAI-compatible endpoint. Switching providers is a
    config change, not a code change.
  - `summarize_transcript(doc, provider) -> str`: builds the prompt from speaker-labelled segment
    text; single-shot (Lemonade models have 262k context). Guard: if the prompt exceeds the
    provider's context budget, fail with a clear error (chunking is a future enhancement, YAGNI).
- Config (`config.toml`):
  ```toml
  [summarize]
  provider = "lemonade"            # lemonade | openrouter | custom
  base_url = "http://127.0.0.1:13305/api/v1"
  model = "Qwen3-30B-A3B-Instruct-2507-GGUF"
  api_key = ""                     # plaintext in config.toml, like hf_token; exposed only as api_key_set
  ```
  Exposed through `GET/PATCH /config` (api_key write-only, reported as `api_key_set`).
- Endpoints:
  - `POST /transcripts/{tid}/summarize` — enqueues a `summarize` job (reuses the job registry +
    SSE stream, so the activity chip shows it too). On completion, writes `summary` (markdown
    string) and `summary_meta` (`{model, provider, created_at}`) into the transcript JSON via a
    CRDT-safe write.
  - `GET /summarize/models` — proxies the configured provider's model list for the settings
    dropdown.
- UI (shared, `CompleteScreen`): "Summarize" button → progress state → summary panel rendered
  above the transcript, with regenerate option. Stored summary displays on subsequent loads.
- Deployment note: Lemonade binds loopback, so only the hub can reach it. Hub-connected clients
  (web, paired desktop) get summarization via the hub. A *standalone* desktop must configure its
  own provider (e.g. OpenRouter) in settings.

### 9. Delete with trash bin

- `DELETE /transcripts/{tid}` — moves the transcript JSON, `.txt` sidecar, and audio file to
  `<library>/.trash/<tid>/`, writing a manifest (`original paths, deleted_at, title`) alongside.
  Same-filesystem rename, so cheap and atomic per file. Transcript disappears from library/FTS.
- `GET /trash` — list trashed items (title, deleted_at, sizes).
- `POST /trash/{tid}/restore` — moves files back to their original paths (409 if a path is now
  occupied). JSON is restored together with the audio, so watch folders do not re-transcribe.
- `DELETE /trash` — empty trash permanently. `DELETE /trash/{tid}` — purge a single item.
- UI (shared): delete button in `LibraryScreen` and `CompleteScreen` with confirm dialog
  ("Move '<title>' to trash?"). Settings gains a Trash section: item list with per-item Restore,
  and Empty trash behind a "cannot be undone" confirm.
- No auto-expiry; manual empty only.

## Error handling

- Audio endpoint: 404 when `audio_path` is missing/moved; player area shows "audio unavailable".
- Summarize: provider unreachable / model missing → job fails with the provider error surfaced in
  the UI; config PATCH validates base_url shape.
- Segment edit / rename: CRDT last-writer-wins on conflict, consistent with relabeling.
- Restore conflicts: 409 with message; item stays in trash.

## Testing

- Python (`pytest -m "not integration"`): new routes (jobs list, audio streaming + range, delete/
  trash/restore, summarize job), CRDT ops (`title`, `edit_segment`), `OpenAICompatProvider`
  against a mocked HTTP server, txt-sidecar rewrite, FTS reindex after edit/rename/delete.
- Frontend (`pnpm test`, `pnpm tsc --noEmit`): shared settings form, rename flow, segment edit,
  in-transcript search, activity chip, trash section, summary panel.
- Build: `pnpm build` and `pnpm build:hub` (regenerates `speechtotext/webui` assets).
- Manual/device checks batched at the end per working agreement.

## Out of scope

- Android parity (rename, edits, time display, summary view) — separate follow-up effort.
- Summarization chunking for transcripts exceeding provider context.
- Auto-expiring trash.
- Browsing hub audio files that have no transcript.
