# LocalScribe — session handoff & roadmap

Snapshot for the next Claude session (or any human picking this up cold).
Last updated: v0.6.0 (2026-05-17).

---

## TL;DR

LocalScribe is a privacy-first on-device transcription app:

- **UI**: Tauri 2 (Rust shell + React/TypeScript webview) — [ui/](../ui)
- **Backend "sidecar"**: a FastAPI Python process bundled with PyInstaller,
  spawned by Tauri — [speechtotext/](../speechtotext)
- **ASR**: faster-whisper, `base.en` bundled in-app (~140 MB), other models
  downloaded on demand to `~/.cache/huggingface/hub`
- **Diarization**: pyannote/speaker-diarization-3.1 — requires user-supplied
  HF token, first-run download (~30 MB), bypasses torchcodec by pre-loading
  WAV with soundfile
- **Library**: SQLite + FTS5 at platform app-data dir;
  `.json` transcript files on disk remain canonical and portable.

Recent CI runs have been "queued" for hours on the GitHub Actions side, but
artifacts still publish to releases. The auto-updater picks them up.

---

## Architecture overview

```
┌──────────────────────────────────────────────────────────────────┐
│  Tauri shell (Rust, ui/src-tauri/src/)                           │
│    - spawns sidecar via tauri-plugin-shell                       │
│    - passes env vars: PATH (+Homebrew), LOCALSCRIBE_BUNDLED_MODELS│
│    - reads handshake JSON {"localscribe":{"port":N}} from stdout │
│    - exposes sidecar_url() invoke to frontend                    │
└──────────────────────────────────────────────────────────────────┘
                          │ spawns
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  Sidecar (Python, speechtotext/api/__main__.py → server.py)      │
│    - uvicorn on a random port, prints handshake on stdout        │
│    - FastAPI app with CORS for localhost:* and tauri://*         │
│    - JobRegistry (in-memory, per-process) drives SSE streaming   │
│    - LibraryDB (SQLite + FTS5) indexes transcript .json files    │
│    - startup hook: warm_microphone_in_background() to trigger    │
│      mic permission dialog early                                 │
│    - startup hook: background sync_dirs() to populate the DB     │
└──────────────────────────────────────────────────────────────────┘
                          │ HTTP / SSE (127.0.0.1:N)
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  React UI (ui/src/)                                              │
│    - Zustand stores: jobs, library, transcripts, recording,     │
│      config, theme                                               │
│    - api/client.ts: discovers + caches sidecar URL via invoke   │
│    - api/sse.ts: subscribes to /jobs/{id}/stream                 │
│    - jobs store also polls /jobs/{id} every 1.5s as SSE fallback│
└──────────────────────────────────────────────────────────────────┘
```

---

## Repository landmarks

### Python backend (`speechtotext/`)

| File | What it does |
|---|---|
| [api/__main__.py](../speechtotext/api/__main__.py) | Entrypoint: `python -m speechtotext.api` → `server.run()` |
| [api/server.py](../speechtotext/api/server.py) | uvicorn launcher + handshake stdout |
| [api/app.py](../speechtotext/api/app.py) | FastAPI app factory, CORS, startup hooks, route mounting |
| [api/jobs.py](../speechtotext/api/jobs.py) | `JobRegistry`: in-memory job state + async SSE queues |
| [api/events.py](../speechtotext/api/events.py) | SSE event dataclasses (StageEvent, LineEvent, CompleteEvent, ErrorEvent) |
| [api/runner.py](../speechtotext/api/runner.py) | Threaded job runners for transcribe + record; cancel events |
| [api/library_db.py](../speechtotext/api/library_db.py) | SQLite + FTS5 library index, RAG schema stubs |
| [api/library.py](../speechtotext/api/library.py) | Legacy disk scan (still used as fallback in routes) |
| [api/watcher.py](../speechtotext/api/watcher.py) | Folder-watch controller (watchdog) |
| [api/warmup.py](../speechtotext/api/warmup.py) | Background mic permission primer |
| [api/routes_*.py](../speechtotext/api/) | One module per resource: jobs, transcripts, models, devices, config, watch |
| [pipeline.py](../speechtotext/pipeline.py) | ingest → asr → diarize → merge → write; accepts `cancel_event` + per-stage `ProgressEvent` |
| [asr/faster_whisper.py](../speechtotext/asr/faster_whisper.py) | FasterWhisperASR; resolves `LOCALSCRIBE_BUNDLED_MODELS` → local model path |
| [diarize/pyannote.py](../speechtotext/diarize/pyannote.py) | PyannoteDiarizer; pre-loads WAV with soundfile to bypass torchcodec |
| [ingest/file.py](../speechtotext/ingest/file.py) | `normalize_to_wav` via ffmpeg with PATH-fallback list |
| [ingest/mic.py](../speechtotext/ingest/mic.py) | sounddevice/soundfile recording loop with SIGINT/SIGTERM handlers |
| [config.py](../speechtotext/config.py) | TOML config at `~/.config/speechtotext/config.toml`; defaults |
| [writer.py](../speechtotext/writer.py) | Atomic .txt + .json writer (json is canonical) |
| [relabel.py](../speechtotext/relabel.py) | Speaker rename — rewrites both files in-place |

### Rust shell (`ui/src-tauri/`)

| File | What it does |
|---|---|
| [src/lib.rs](../ui/src-tauri/src/lib.rs) | Tauri app builder, plugin registration, sidecar spawn, window-close cleanup |
| [src/sidecar.rs](../ui/src-tauri/src/sidecar.rs) | Spawns sidecar, sets PATH/models env, parses handshake, exposes `sidecar_url` cmd |
| [tauri.conf.json](../ui/src-tauri/tauri.conf.json) | Bundle config; ships `resources/models/**/*` and `binaries/localscribe-sidecar` |
| [capabilities/default.json](../ui/src-tauri/capabilities/default.json) | Plugin ACL (shell, opener, updater, dialog, process) — has `opener:allow-open-path` for transcript files |

### Frontend (`ui/src/`)

| File | What it does |
|---|---|
| [App.tsx](../ui/src/App.tsx) | Top-level router; `setRoute` redirects to progress when a job is active |
| [api/client.ts](../ui/src/api/client.ts) | Discovers sidecar URL, retries on TypeErrors, probes `/health` |
| [api/sse.ts](../ui/src/api/sse.ts) | Fetch + decode `text/event-stream` for `/jobs/{id}/stream` |
| [api/types.ts](../ui/src/api/types.ts) | Shared DTOs |
| [stores/jobs.ts](../ui/src/stores/jobs.ts) | SSE subscription + 1.5s polling fallback; `startedAt` for timer persistence |
| [stores/library.ts](../ui/src/stores/library.ts) | `items` (current view) + `all` (full list) split for search vs sidebar |
| [stores/transcripts.ts](../ui/src/stores/transcripts.ts) | Loads `/transcripts/{id}`; relabel triggers reindex server-side |
| [chrome/Sidebar.tsx](../ui/src/chrome/Sidebar.tsx) | Nav + active-job dot + version from `getVersion()` |
| [screens/*.tsx](../ui/src/screens/) | Idle, Progress, Complete, Record, Library, Watch, Settings |

### Packaging

| File | What it does |
|---|---|
| [packaging/localscribe-sidecar.spec](../packaging/localscribe-sidecar.spec) | PyInstaller spec; bundles pyannote.audio.models submodules, faster_whisper assets, torchcodec dylibs |
| [scripts/download_bundled_models.py](../scripts/download_bundled_models.py) | Idempotent HF snapshot fetcher; populates `ui/src-tauri/resources/models/` for bundling |
| [.github/workflows/build-sidecar.yml](../.github/workflows/build-sidecar.yml) | Per-platform sidecar build (artifact only) |
| [.github/workflows/build-app.yml](../.github/workflows/build-app.yml) | Full installer build via tauri-action; runs the model-download script before bundling |

---

## Validation commands

Always run all three before pushing:

```bash
# Backend tests (113 currently)
.venv/bin/python -m pytest -q

# Frontend tests + typecheck
cd ui && pnpm exec tsc --noEmit && pnpm test --run

# Rust check (sidecar.rs changes)
cd ui/src-tauri && cargo check
```

Sidecar binary rebuild (Python changes):

```bash
.venv/bin/pyinstaller packaging/localscribe-sidecar.spec --clean
# Use a fresh-inode move to dodge macOS launch-failure caching:
cp dist/localscribe-sidecar /tmp/sc-fresh-$$
mv /tmp/sc-fresh-$$ ui/src-tauri/binaries/localscribe-sidecar-aarch64-apple-darwin
```

End-to-end smoke test (skips Tauri, hits sidecar directly):

```bash
ui/src-tauri/binaries/localscribe-sidecar-aarch64-apple-darwin > /tmp/sc.log 2>&1 &
# wait ~30-45s for handshake to appear in /tmp/sc.log, grab the port
curl -sS -X POST "http://127.0.0.1:$PORT/jobs/transcribe" \
  -H 'Content-Type: application/json' \
  -d '{"path":"/tmp/test-audio.aiff"}'
# poll GET /jobs/{id} until status=complete
```

---

## Push protocol (from CLAUDE.md global)

User says "git push" → ALWAYS:

1. Bump version in four files (must match):
   - [pyproject.toml](../pyproject.toml)
   - [ui/package.json](../ui/package.json)
   - [ui/src-tauri/Cargo.toml](../ui/src-tauri/Cargo.toml)
   - [ui/src-tauri/tauri.conf.json](../ui/src-tauri/tauri.conf.json)
2. Run all validations.
3. Stage + commit with a `Co-Authored-By: Claude` trailer.
4. `git tag -a vX.Y.Z -m "vX.Y.Z"`.
5. `git push origin main --follow-tags`.

SemVer guide: patch for bugfixes, minor for user-visible features, major
when migrations are required.

Use HEREDOC for commit messages — single-quoted apostrophes break the
shell. Safer pattern (used throughout this session):

```bash
# Write the message to a file first
cat > /tmp/commit-msg.txt <<'EOF'
type(scope): subject

body...
EOF
git commit -F /tmp/commit-msg.txt
```

---

## Decisions already made (don't re-litigate without reason)

| Decision | Value | Rationale |
|---|---|---|
| Library backend | SQLite + FTS5 | JSON-scan didn't scale; vectors slot in alongside FTS |
| DB location | Platform app-data dir | macOS convention; invisible in Finder; not version-controlled |
| `.json` files canonical | Yes | Portability, external tools, easy export, DB rebuildable |
| Default ASR model | `base.en` (bundled, ~140 MB) | Best size/quality for OOTB; large-v3 opt-in |
| Bundled ASR strategy | HF snapshot in `ui/src-tauri/resources/models/`, env var to sidecar | Survives Tauri's dev-vs-prod resource path quirks via multi-candidate lookup |
| Diarization audio loader | soundfile (not torchcodec) | torchcodec's `.dylib` lookup via `importlib.find_spec` fails in PyInstaller bundle; soundfile already a dep |
| Chunk unit (future RAG) | Fixed-token windows (~300 tokens) | Predictable retrieval; speaker boundaries less important for semantic |
| Embedding timing (future) | Eagerly on transcribe completion | Search is instant; one-time cost per transcript |
| Summarization model | Deferred | Bundle size + privacy trade-off needs a real decision later |
| Progress UI | SSE + 1.5s polling fallback | Tiny clips can finish before SSE attaches; polling guarantees terminal state |
| Mic permission | Warmed on sidecar startup | Avoids losing first seconds of first recording |
| Cancel transcribe | Soft cancel via cancel_event in pipeline + ASR loop | Hard thread kill is unsafe; soft cancel takes effect at next segment / stage boundary |

---

## RAG roadmap (next chunks of work)

The schema is ready (`chunks`, `embeddings` tables exist). To turn it on:

### Phase 1 — Chunker

- New module `speechtotext/rag/chunker.py`.
- Takes a `Transcript` (or its segments), produces `Chunk` rows of ~300 tokens
  each (use `tiktoken` or `sentencepiece` for accurate counts; fall back to
  word count × 1.3 if no tokenizer).
- Preserve `start_time`/`end_time` from constituent segments (min start, max end).
- Wire into runner: after `write_transcript`, also call
  `library_db.upsert_chunks(transcript_id, chunks)`.

### Phase 2 — Embedder

- New job kind `embed` in [runner.py](../speechtotext/api/runner.py).
- Backend choice: `sentence-transformers/all-MiniLM-L6-v2` (80 MB) or
  `BAAI/bge-small-en-v1.5` (130 MB). Bundle the chosen one the same way
  as base.en (see [scripts/download_bundled_models.py](../scripts/download_bundled_models.py)).
- Add `LOCALSCRIBE_BUNDLED_EMBED_MODEL` env (mirrors ASR pattern).
- Trigger after transcribe completion (re-use the `on_complete_dir` hook).
- Status surfaced via new `/models/embed` endpoint mirroring `/models/whisper`.

### Phase 3 — Vector search

- Add `sqlite-vec` dependency (or `sqlite-vss`). Install at sidecar startup
  via `conn.enable_load_extension(True); conn.load_extension(...)`.
- Add a `vec_chunks` virtual table mirroring the `embeddings` rows.
- Extend `LibraryDB.search()` to compute query embedding, run vector
  cosine search, hybrid-merge with FTS5 BM25 results (RRF — reciprocal
  rank fusion — is dirt simple and works well).
- Frontend: same search box; results now include semantic matches.
  Snippet renderer already handles `<mark>`-style highlights.

### Phase 4 — Summarization (deferred)

- Decision blocked: local LLM (bundle 4-6 GB) vs cloud API (privacy regression).
- When unblocked: new `summarize` job kind; pipe to chosen LLM with a
  fixed prompt template; store result in a new `summaries` table.
- UI: add a "Summary" panel above the transcript on the Complete screen.

---

## Gotchas the next session will hit

1. **Sidecar binary is gitignored.** After Python changes, rebuild with
   pyinstaller and copy into `ui/src-tauri/binaries/`. Use a fresh inode
   (cp to /tmp then mv) — macOS caches launch-failure state by inode and
   will hang spawned binaries that have the same inode as a previously
   stuck process.

2. **macOS UE zombies.** PyInstaller-bundled processes can get stuck in
   "U" (uninterruptible) "E" (exiting) state during low-disk or quarantine
   scan conditions. They cannot be killed; only a reboot clears them. Kill
   the parent `pgrep -fl localscribe` chain proactively when iterating.

3. **PyInstaller `_MEI*` temp dirs leak.** Each sidecar launch extracts
   ~600 MB to `/var/folders/.../T/_MEI*`. Stuck processes don't clean up.
   Periodically `rm -rf /var/folders/.../T/_MEI*` after killing orphans.

4. **Dev-mode resource_dir.** `app.path().resource_dir()` in `pnpm tauri
   dev` returns `target/debug/`, NOT the source `resources/` dir. The
   `locate_bundled_models()` helper in [sidecar.rs](../ui/src-tauri/src/sidecar.rs)
   walks multiple candidates and falls back to `CARGO_MANIFEST_DIR`.

5. **ffmpeg PATH.** GUI-launched macOS apps get a stripped PATH without
   Homebrew. Rust shell prepends `/opt/homebrew/bin` etc.; Python's
   `_resolve_ffmpeg()` also has an absolute-path fallback list.

6. **SSE race for tiny clips.** Backend's per-job event queue is created
   on subscriber connect. Events emitted before connect are lost. Frontend
   polls `/jobs/{id}` every 1.5s as a guarantee.

7. **CI delays.** GitHub Actions runners for `build-app.yml` are
   frequently backlogged ("queued" status for hours). Don't take that as
   a build failure — wait or check via `gh release view vX.Y.Z`.

8. **Auto-updater latency.** After tagging, the in-app updater can take
   30+ seconds on next launch to notice the new release. Quitting and
   relaunching shortcuts it.

9. **Pyannote requires HF token AND license acceptance.** First-run
   download fails silently (well, with a 401) if either is missing.
   Settings shows a banner.

10. **Multiple library directories.** `app.state.library_dirs: set[Path]`
    is dynamic — every transcribe completion adds the output dir.
    `LibraryDB.sync_dirs` only deletes rows whose path is under one of
    the *currently registered* dirs, so transcripts in unregistered dirs
    don't get evicted.

---

## Open questions (none blocking)

- Should `default_out_dir` from config also auto-register on startup?
  Currently yes via `_cfg.default_out_dir` in [app.py](../speechtotext/api/app.py).
- Should we add a Settings field for additional library dirs? (Currently
  only the output dirs of completed jobs get added.)
- Should FTS5 ranking weights be tunable per user? (Currently hardcoded
  content=4, filename=6, speakers=3, meta=2.)
- Pyannote model bundle: technically possible (~500 MB) but license-gated.
  Worth revisiting once pyannote 4.x ships with clearer redistribution
  terms.

---

## Version history (compressed)

| Version | What |
|---|---|
| 0.6.0 | SQLite + FTS5 library, ranked search with snippets, RAG schema stubs |
| 0.5.8 | Library search empty-state fix, broader field matching |
| 0.5.7 | Drop misleading 0% from active stage chip |
| 0.5.6 | Wire Copy/Open .txt/Open .json buttons (was no-op) |
| 0.5.5 | Model download status in Settings; mic permission warmup |
| 0.5.4 | Polling fallback for SSE so progress UI never stalls |
| 0.5.3 | Bypass torchcodec via soundfile pre-load |
| 0.5.2 | ffmpeg PATH fix for GUI-launched apps |
| 0.5.1 | Sidecar PyInstaller spec: pyannote submodules + torchcodec dylibs |
| 0.5.0 | Bundle base.en model; load stage; persistent elapsed timer |
| 0.4.0 | Cancellable transcribe; granular progress; working IdleScreen options; (i) popovers |
| 0.3.x | Pre-Claude-session baseline: Tauri shell, basic ASR + diarize, CI |
