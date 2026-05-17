# LocalScribe

> Local-first speech-to-text with speaker labels. Cross-platform desktop app + CLI.
> Nothing leaves your machine — models, audio, and transcripts all live in your filesystem.

LocalScribe transcribes audio into a typeset, speaker-labeled manuscript. It
runs on your computer using [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
for ASR and [pyannote.audio](https://github.com/pyannote/pyannote-audio) for
speaker diarization. There is no cloud, no API call, no telemetry. Audio you
record stays on your disk; transcripts are plain `.txt` and `.json` files next
to the source audio.

The project ships as two things:

- **`stt`** — a Python CLI for transcribing, recording, watching folders,
  relabeling speakers, and editing config from a terminal.
- **LocalScribe** — a Tauri desktop app (macOS / Windows / Linux) that wraps
  the CLI in a manuscript-themed UI: drop a file, watch it transcribe live,
  relabel speakers inline, browse the library.

Both are in this repo. Both call the same underlying Python pipeline. The
desktop app talks to a bundled FastAPI sidecar over `localhost`; the CLI calls
the pipeline directly.

## Features

- **On-device.** No network calls. The privacy posture is a product
  invariant — the app surfaces an "On-device" chip and a sidebar live dot to
  remind you.
- **Speaker diarization.** Pyannote 4.0 labels who-said-what. Relabel
  `SPEAKER_00 → Alice` inline; the labels rewrite into the `.json` and `.txt`
  files.
- **Dutch + English** out of the box (Whisper auto-detects others too).
- **Drop, record, watch.** Drag an audio file in, record from a mic, or
  point at a folder and have new files auto-transcribed.
- **Swappable backend.** Auto-pick CPU / CUDA / MPS — the
  `speechtotext.backend.resolve_backend` module figures out what your
  machine has.
- **Searchable library.** SQLite + FTS5 index keeps every transcript
  searchable by content, filename, and speaker. The `.json` files on disk
  remain canonical — the index is rebuildable from them at any time.

## Status

v0.6.0. The CLI (`stt`) is stable. The desktop app covers the full core
workflow — drop file → transcribe → relabel → library / record from mic /
watch folder / settings editor. The transcript library is backed by SQLite +
FTS5 with ranked full-text search. Phase 2 (local RAG search via embeddings)
has its schema in place; the chunker and embedder are next.

## Install

### Desktop app

Pre-built binaries are produced by
[`.github/workflows/build-app.yml`](.github/workflows/build-app.yml) for
macOS, Windows, and Linux on every push to `main`. Once a release is cut,
download the platform bundle from the
[Releases](https://github.com/lieuwe89/LocalScribe/releases) page and run it.

> The `base.en` Whisper model (~140 MB) is bundled — transcription works
> immediately. Pyannote speaker diarization requires a one-time download
> (~30 MB) on first use; you'll need a free Hugging Face token for that.

Paste your [Hugging Face](https://huggingface.co/settings/tokens) token into
Settings on first launch to enable speaker diarization.

### CLI

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# system deps
brew install ffmpeg          # macOS
# apt install ffmpeg         # Linux
# choco install ffmpeg       # Windows
```

Drop a Hugging Face token into `~/.config/speechtotext/config.toml`:

```toml
backend = "auto"
asr_model = "large-v3"
hf_token = "hf_..."
```

## CLI usage

```bash
stt doctor                                # sanity-check setup
stt transcribe meeting.mp3                # → meeting.txt + meeting.json
stt transcribe call.wav --lang nl
stt record --out memo.wav                 # Ctrl-C to stop; auto-transcribes
stt watch ~/Recordings                    # daemon: new files → transcribed
stt relabel meeting.json SPEAKER_00=Alice SPEAKER_01=Bob
stt devices                               # list audio inputs
stt serve                                 # run the LocalScribe HTTP API
```

### Recording meetings (system audio)

`stt record` captures the default microphone, **not** what other participants
say through your speakers. To capture both sides:

- **macOS** — install [BlackHole](https://existential.audio/blackhole/),
  create an Aggregate Device in Audio MIDI Setup combining your mic +
  BlackHole, then:
  ```bash
  stt devices                                       # find the aggregate
  stt record --device "Aggregate (Mic+BlackHole)"
  ```
- **Linux (PulseAudio)** — every output has a `.monitor` source. List with
  `stt devices` (look for `hint: loopback`).
- **Simplest path** — use the meeting tool's built-in recorder, then
  `stt transcribe meeting.mp4`.

## Output format

`<audio>.txt`:

```
[00:00:00] Alice: hallo
[00:00:04] Bob: hoi
```

`<audio>.json` is the canonical store. Schema is frozen and documented in
[the CLI design spec](docs/superpowers/specs/2026-05-14-speech-to-text-cli-design.md).

## Architecture

Three layers, each with a clear contract:

```
┌─────────────────────────────────────────────────┐
│  UI    Tauri shell + React frontend             │
│        Sidebar, screens, transcript library     │
└──────────────────────┬──────────────────────────┘
                       │ REST + Server-Sent Events
                       │ over localhost:<random>
┌──────────────────────┴──────────────────────────┐
│  API   FastAPI server (bundled sidecar)         │
│        Job orchestration, transcript index      │
└──────────────────────┬──────────────────────────┘
                       │ Python imports
┌──────────────────────┴──────────────────────────┐
│  ML    speechtotext package (the CLI runtime)   │
│        Pipeline, ASR, diarize, ingest, writer   │
└─────────────────────────────────────────────────┘
```

The Tauri shell spawns the FastAPI sidecar (a PyInstaller-bundled binary)
at launch, parses a JSON handshake from its stdout to discover the port,
and kills it on quit. The frontend talks to it over REST + SSE. The ML
layer is the same code that runs when you invoke `stt` from a terminal.

Detailed design lives in
[docs/superpowers/specs/2026-05-15-stt-desktop-ui-design.md](docs/superpowers/specs/2026-05-15-stt-desktop-ui-design.md).
The visual handoff (mockups, JSX prototypes, design tokens) lives in
[docs/design_handoff_localscribe/](docs/design_handoff_localscribe/) — open
[`LocalScribe-standalone.html`](docs/design_handoff_localscribe/LocalScribe-standalone.html)
in a browser to see the high-fi prototype.

## Build from source

The desktop app is a Tauri 2 project under [`ui/`](ui/). You'll need:

- Python 3.11+
- Node 20+ with `pnpm`
- Rust 1.75+ (`rustup` works fine)
- `ffmpeg` on `PATH`

```bash
# 1. Build the sidecar binary
pip install -e ".[api,packaging]"
pyinstaller packaging/localscribe-sidecar.spec --clean
mkdir -p ui/src-tauri/binaries
cp dist/localscribe-sidecar ui/src-tauri/binaries/localscribe-sidecar-$(rustc -vV | sed -n 's/host: //p')

# 2. Run in dev mode
cd ui
pnpm install
pnpm tauri dev
```

Release builds: `pnpm tauri build` from `ui/`. Outputs land in
`ui/src-tauri/target/release/bundle/`.

## Project layout

```
SpeechToText/
├── speechtotext/                 # Python package
│   ├── api/                      # FastAPI sidecar
│   ├── asr/, diarize/, ingest/   # ML adapters
│   ├── cli.py                    # `stt` command
│   ├── pipeline.py               # orchestrator
│   └── writer.py, relabel.py
├── ui/                           # Tauri + Vite + React frontend
│   ├── src/                      # screens, stores, primitives, chrome
│   └── src-tauri/                # Rust shell + sidecar lifecycle
├── packaging/                    # PyInstaller spec
├── tests/                        # pytest suite (108 fast tests + integration)
├── docs/
│   ├── design_handoff_localscribe/  # visual handoff (HTML prototype, JSX, CSS)
│   └── superpowers/specs/plans/     # design specs and implementation plans
└── .github/workflows/            # CI for sidecar + full app
```

## Development

```bash
# Backend
pytest -m "not integration"        # fast Python suite (~113 tests)
pytest -m integration              # end-to-end with whisper-tiny (slow)

# Frontend
cd ui
pnpm test                          # vitest
pnpm tsc --noEmit                  # type-check

# Tauri smoke test (requires the sidecar binary in place)
cargo test --manifest-path ui/src-tauri/Cargo.toml --release
```

## Roadmap

- [ ] RAG Phase 1: chunker — split transcripts into ~300-token windows, store in DB.
- [ ] RAG Phase 2: embedder — `all-MiniLM-L6-v2` or `bge-small-en-v1.5`, triggered after transcribe.
- [ ] RAG Phase 3: vector search — `sqlite-vec` + hybrid BM25/cosine via RRF.
- [ ] RAG Phase 4: summarization — local LLM vs cloud API decision still open.
- [ ] Live streaming transcription from the mic (per-chunk ASR).
- [ ] Plain-chrome window mode.

## License

Not yet licensed. Until a `LICENSE` file lands, treat this as "all rights
reserved" — the source is published for transparency but redistribution
isn't granted. A permissive license (likely MIT or Apache-2.0) is intended
for a future release.

## Acknowledgements

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2-
  based Whisper inference.
- [pyannote.audio](https://github.com/pyannote/pyannote-audio) — speaker
  diarization toolkit.
- [Tauri](https://tauri.app/) — Rust-powered cross-platform desktop shell.
- Newsreader, Geist, Geist Mono — Google Fonts, the manuscript metaphor's
  type stack.
