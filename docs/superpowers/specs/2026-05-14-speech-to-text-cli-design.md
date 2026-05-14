# Speech-to-Text CLI — Design

**Date:** 2026-05-14
**Status:** Approved (brainstorm complete, ready for implementation plan)
**Scope:** MVP — transcription + speaker diarization + CLI. Summaries + RAG are a separate phase 2 spec.

---

## 1. Purpose & Constraints

Build a local, privacy-preserving CLI tool that:

- Transcribes audio in **Dutch and English** (auto-detected per recording).
- Labels individual speakers (anonymous `Speaker 1`, `Speaker 2`, ... with post-hoc rename).
- Runs on **macOS arm64** (dev box) and **Linux x86_64** (eventual homelab deploy).
- Backend swappable: **CPU**, **NVIDIA CUDA**, **Apple MPS**. Final homelab hardware is TBD.
- All processing local. No cloud calls, no telemetry.
- Stores transcripts as plain files (`.txt` + `.json` sidecar) next to the source audio.
- Designed so a UI (web/desktop) can be added later without rewriting the core.

Out of scope for this spec (deferred to phase 2):

- Automatic summarization
- RAG-based Q&A across transcripts
- Voice enrollment / named speaker recognition
- Real-time streaming transcripts
- Code-switching (mixed Dutch/English within one recording)

---

## 2. Stack

| Layer | Choice | Reason |
|---|---|---|
| ASR | `faster-whisper` with Whisper `large-v3` | Cross-platform (CPU/CUDA/MPS-via-CPU), proven Dutch + English quality, CTranslate2 backend |
| Diarization | `pyannote.audio` 4.0 | Best open-source diarizer in 2026, native PyTorch device support |
| VAD (optional) | `silero-vad` | Pre-pass to drop silence; bypass if Whisper's built-in VAD suffices |
| Audio I/O | `ffmpeg` (subprocess) + `sounddevice` (mic) | Universal codec support; cross-platform mic capture |
| Watch daemon | `watchdog` | Cross-platform fs events |
| CLI framework | `Typer` | Subcommands, typed flags, autocomplete |
| Config | TOML at `~/.config/speechtotext/config.toml` | Standard XDG location |
| Packaging | `pyproject.toml`, `pip install -e .` for dev | Standard Python tooling |

**Decoupled** (not bundled via WhisperX) so the ASR backend can be swapped to Qwen3-ASR or NVIDIA Canary later if the homelab gains a CUDA GPU. See `dgx-spark-asr-stack.md` for the future CUDA-locked option list.

---

## 3. Architecture

```
              ┌─────────────────────────┐
              │   CLI (Typer)           │
              └──────────┬──────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼─────┐    ┌─────▼────┐    ┌─────▼─────┐
   │transcribe│    │  record  │    │   watch   │
   │  <file>  │    │  (mic)   │    │  <dir>    │
   └────┬─────┘    └─────┬────┘    └─────┬─────┘
        │ file path      │ writes wav     │ enqueues new files
        └────────────────┴────────────────┘
                         │
                  ┌──────▼──────┐
                  │  Pipeline   │  (orchestrator + progress callback)
                  └──────┬──────┘
                         │
            ┌────────────┼────────────┐
            │            │            │
       ┌────▼──┐    ┌────▼────┐  ┌────▼────┐
       │  VAD  │    │   ASR   │  │ Diariz. │
       │silero │    │faster-  │  │pyannote │
       │ (opt) │    │whisper  │  │  4.0    │
       └────┬──┘    └────┬────┘  └────┬────┘
            └────────────┼────────────┘
                  ┌──────▼──────┐
                  │   Merger    │ (align segments + speaker turns)
                  └──────┬──────┘
                         │
                  ┌──────▼──────┐
                  │   Writer    │ → <audio>.txt + <audio>.json
                  └─────────────┘
```

`Pipeline.run(audio, on_progress=callback) → Transcript` is the single library-mode entry point. CLI is a thin shell around it. Any future UI consumes the same callable.

---

## 4. Module Layout

```
speechtotext/
├── cli.py              # Typer entrypoint, dispatches subcommands
├── config.py           # Loads ~/.config/speechtotext/config.toml
├── pipeline.py         # Orchestrator + ProgressEvent emission
├── models.py           # Dataclasses: Segment, SpeakerTurn, LabeledSegment, Transcript, ProgressEvent
├── ingest/
│   ├── file.py         # Validate + ffmpeg-normalize to 16kHz mono wav
│   ├── mic.py          # sounddevice recorder, Ctrl-C stops
│   └── watch.py        # watchdog observer, debounce, enqueue jobs
├── asr/
│   ├── base.py         # ASRBackend Protocol
│   └── faster_whisper.py
├── diarize/
│   ├── base.py         # DiarizerBackend Protocol
│   └── pyannote.py
├── vad/
│   ├── base.py
│   └── silero.py
├── merger.py
├── writer.py
└── relabel.py
```

---

## 5. Interfaces

```python
# asr/base.py
class ASRBackend(Protocol):
    def transcribe(self, wav_path: Path, language: str | None) -> list[Segment]: ...

# diarize/base.py
class DiarizerBackend(Protocol):
    def diarize(self, wav_path: Path, num_speakers: int | None) -> list[SpeakerTurn]: ...

# pipeline.py
class Pipeline:
    def __init__(self, config: Config): ...
    def run(
        self,
        audio: Path,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> Transcript: ...
```

Dataclasses (`models.py`):

```python
@dataclass
class Segment:
    start: float        # seconds
    end: float
    text: str
    language: str | None

@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker_id: str     # "SPEAKER_00", ...

@dataclass
class LabeledSegment:
    start: float
    end: float
    text: str
    speaker_id: str     # may be "UNKNOWN"

@dataclass
class Transcript:
    audio_path: Path
    duration_seconds: float
    language: str
    speakers: dict[str, str]            # speaker_id → display name
    segments: list[LabeledSegment]
    models: dict[str, str]              # which ASR/diarizer/backend ran
    created_at: datetime

@dataclass
class ProgressEvent:
    stage: Literal["ingest", "vad", "asr", "diarize", "merge", "write"]
    pct: float                          # 0.0..1.0 within the stage
    message: str
```

---

## 6. Sidecar JSON Schema (v1, frozen)

Phase 2 (RAG) will read these directly — schema is committed for compat.

```json
{
  "version": 1,
  "audio_path": "/abs/path/to/recording.mp3",
  "duration_seconds": 1842.3,
  "language": "nl",
  "speakers": {
    "SPEAKER_00": "Speaker 1",
    "SPEAKER_01": "Speaker 2"
  },
  "segments": [
    {"start": 0.32, "end": 4.10, "speaker": "SPEAKER_00", "text": "..."}
  ],
  "models": {
    "asr": "faster-whisper:large-v3",
    "diarizer": "pyannote:4.0",
    "backend": "mps"
  },
  "created_at": "2026-05-14T20:11:32Z"
}
```

`.txt` format:

```
[00:00:00] Speaker 1: ...
[00:00:04] Speaker 2: ...
```

---

## 7. CLI Surface

```
stt transcribe <audio>
    --lang nl|en|auto                 # default: auto
    --speakers N                      # hint for diarizer; default: auto-detect
    --model tiny|base|small|medium|large-v3
    --backend cpu|cuda|mps
    --out <dir>                       # default: alongside audio
    --overwrite                       # default: skip if .json exists

stt record [--device <name>] [--out <path>]
    # records 16kHz mono wav, Ctrl-C stops, then transcribes

stt watch <dir> [--recursive] [--exts mp3,wav,m4a,mp4]
    # daemon: new file → debounce 2s → transcribe → continue
    # writes .stt-processing marker, removes on success

stt relabel <transcript.json> SPEAKER_00=Alice SPEAKER_01=Bob
    # rewrites speaker map + regenerates .txt

stt config [show|edit|path]

stt doctor
    # checks: ffmpeg, HF token, model cache, backend availability
```

Config TOML:

```toml
backend = "mps"
asr_model = "large-v3"
hf_token = "hf_..."
model_cache_dir = "~/.cache/speechtotext/models"
default_out_dir = ""

[watch]
recursive = false
debounce_seconds = 2
extensions = ["mp3", "wav", "m4a", "mp4", "flac"]
```

---

## 8. Data Flow

```
1. ingest    : audio_in → ffmpeg → /tmp/<uuid>.wav   (16kHz, mono, pcm_s16le)
2. asr       : wav → faster-whisper → [Segment]
3. diarize   : wav → pyannote 4.0   → [SpeakerTurn]
4. merge     : segments + turns     → [LabeledSegment]
                 Rule: each Segment gets the speaker_id whose SpeakerTurn has
                 max temporal overlap with [segment.start, segment.end].
                 If max overlap < 50ms → "UNKNOWN".
5. write     : LabeledSegments → <audio>.txt.tmp + <audio>.json.tmp
                 → os.replace() both atomically
6. cleanup   : remove /tmp/<uuid>.wav
```

ASR and diarization run sequentially in MVP. Parallel run (diarizer on CPU + ASR on GPU) is a future optimization, not MVP.

---

## 9. Backend Resolution

Order (highest → lowest):

1. `--backend` CLI flag
2. `STT_BACKEND` env var
3. `config.toml` `backend` key
4. Auto-detect: `cuda` if `torch.cuda.is_available()` → `mps` if Mac arm64 → `cpu`

Backend mapping in `faster_whisper.py`:

| Backend | device | compute_type |
|---|---|---|
| `cpu` | `cpu` | `int8` |
| `cuda` | `cuda` | `float16` |
| `mps` | `cpu` | `int8` (faster-whisper has no native MPS yet — runs on CPU; Apple Silicon CPU is fast enough; revisit when CTranslate2 ships MPS) |

Pyannote 4.0 supports `torch.device("mps" | "cuda" | "cpu")` natively → straightforward wrapper.

---

## 10. Error Handling

| Failure | Handling |
|---|---|
| `ffmpeg` missing | `doctor` flags; `transcribe` fails fast with install hint |
| HF token missing/invalid | `doctor` flags; `transcribe` errors before model download |
| Model download failure (no internet) | Clear error; suggest `--offline` if cache exists |
| Audio file corrupt / unsupported codec | ffmpeg conversion fails → report stderr, exit 2 |
| OOM during ASR or diarization | Suggest smaller model or `--backend cpu`, exit 3 |
| GPU requested but unavailable | At init: log warning, fall back via resolution order, continue |
| Mid-pipeline crash | Partial outputs deleted; `/tmp` wav cleaned |
| `watch`: file still being written | Debounce 2s after last fs event; skip if size still changing |
| `watch`: already processed | Skip if `.json` newer than audio (unless `--overwrite`) |
| `watch`: per-file pipeline crash | Log; write `<audio>.stt-error.txt` marker; continue queue |
| `relabel`: invalid speaker_id | Error, list valid IDs from json |
| `relabel`: .txt out of sync | Regenerate `.txt` from `.json` (json is source of truth) |

**Atomicity:** `<name>.txt.tmp` + `<name>.json.tmp` then `os.replace()` both at end. Crash mid-write leaves no half-files.

**Idempotency:** `transcribe foo.mp3` is a no-op when `.json` exists and is newer than the audio, unless `--overwrite`.

**Resource discipline (`watch` mode):** models loaded once and kept resident. RSS sampled; restart self if RSS exceeds 2× post-warmup baseline (defends against torch leaks).

**Logging:** human-readable progress to stderr by default. `--quiet` for cron. `--json-logs` emits one JSON object per `ProgressEvent` for UI consumption. No telemetry. Local only.

---

## 11. Testing

| Layer | What | How |
|---|---|---|
| Unit | `merger.merge`, `relabel`, JSON (de)serialize, config parsing, backend resolution | pytest, no models loaded |
| Component | Each backend wrapper | pytest + fixture wavs |
| Integration | End-to-end pipeline on fixture audio → assert sidecar matches golden file (with tolerance) | pytest, CPU only |
| Smoke | `stt doctor` per platform | CI matrix + manual |

**Fixture audio (in `tests/fixtures/`):**

- `nl_2speakers_10s.wav` — Dutch, 2 speakers
- `en_2speakers_10s.wav` — English, 2 speakers
- `en_silence_then_speech.wav` — VAD/segmentation
- Total ≤500 KB (16 kHz mono, low bitrate)

**Golden-file tolerance:**

- Text: exact match (Whisper deterministic with `temperature=0`).
- Timestamps: ±0.2 s.
- Speaker IDs: assert *partition* matches (which segments share a speaker), not the raw labels (diarizer may permute).

**CI matrix:**

- macOS arm64 (CPU mode)
- Ubuntu x86_64 (CPU mode)
- CUDA correctness: manual smoke on the homelab, not CI.

**Out of scope for MVP tests:**

- GPU correctness (manual)
- Long-audio (>1 h) perf (manual)
- Accent/noise robustness (QA, not unit tests)

---

## 12. Future-UI Hooks

`Pipeline.run(audio, on_progress=callback)` is the integration seam. Three UI strategies all work without changing the core:

1. **Library import** — `from speechtotext.pipeline import Pipeline`. FastAPI/Flask/Streamlit wraps it directly.
2. **Shell out + parse `--json-logs`** — Tauri/Electron/any non-Python UI.
3. **Read sidecar `.json` files** — pure viewers don't need to re-run the pipeline.

Sidecar schema is `version: 1` and frozen for this reason.

---

## 13. Phase 2 Hooks (informational, not part of this spec)

The frozen sidecar schema is the integration point for:

- **Summarization** — read `.json` segments, feed to a local LLM (Ollama / vLLM), write `<audio>.summary.md`.
- **RAG Q&A** — embed segments, store in a local vector DB (LanceDB / Chroma), query across transcripts.

Both are deferred to a separate spec. This MVP must not commit schema decisions that lock them out — frozen v1 schema is the contract.

---

## 14. Open Questions for Implementation Phase

- Whisper `temperature=0` determinism vs occasional repetition — may need `beam_size` tuning per language.
- Pyannote 4.0 license / HF gating — confirm token flow in `doctor`.
- `mps` backend for pyannote 4.0 on Apple Silicon — verify works in practice or fall back to CPU on Mac.
- Watchdog inotify limits on Linux for large directories — document `fs.inotify.max_user_watches` tuning if needed.
