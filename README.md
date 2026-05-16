# stt — local speech-to-text with speaker labels

Privacy-preserving CLI. Dutch + English. Runs on macOS arm64 and Linux x86_64.
Swappable CPU / CUDA / MPS backend.

## Install (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
brew install ffmpeg          # macOS
# apt install ffmpeg         # Linux
```

Pyannote requires a Hugging Face access token (free). Set it once:

```bash
mkdir -p ~/.config/speechtotext
cat > ~/.config/speechtotext/config.toml <<'EOF'
backend = "auto"
asr_model = "large-v3"
hf_token = "hf_..."
EOF
```

## Usage

```bash
stt doctor                          # check setup
stt transcribe meeting.mp3          # → meeting.txt + meeting.json
stt transcribe call.wav --lang nl
stt record --out memo.wav           # mic; Ctrl-C to stop, auto-transcribes
stt watch ~/Recordings              # daemon: new files → transcribed
stt relabel meeting.json SPEAKER_00=Alice SPEAKER_01=Bob
```

### Recording meetings (system audio)

`stt record` captures the default mic input — not what the other meeting
participants say through your speakers. To capture both sides:

- **macOS:** install BlackHole (https://existential.audio/blackhole/), create
  an Aggregate Device in Audio MIDI Setup combining your mic + BlackHole,
  then:
  ```bash
  stt devices                                    # find the aggregate's name
  stt record --device "Aggregate (Mic+BlackHole)"
  ```
- **Linux (PulseAudio):** every output has a `.monitor` source. List with
  `stt devices` (look for `hint: loopback`).
- **Simplest:** use the meeting tool's built-in recorder, then
  `stt transcribe meeting.mp4`.

Use `stt devices --json` for scripting.

## Output format

`<audio>.txt`:
```
[00:00:00] Alice: hallo
[00:00:04] Bob: hoi
```

`<audio>.json` follows the frozen schema documented in
`docs/superpowers/specs/2026-05-14-speech-to-text-cli-design.md`.

## Tests

```bash
pytest -m "not integration"          # fast suite, no models
python tests/fixtures/generate_fixtures.py
pytest -m integration                # downloads whisper-tiny
```

## Phase 2

Summarization and RAG Q&A across transcripts read the same `.json` sidecars.
See spec for the schema contract.

## Desktop app — LocalScribe

A cross-platform desktop UI lives in `ui/`. It wraps the CLI through a
bundled FastAPI sidecar, with full feature parity plus a transcript
library.

Local dev:

    # 1. Build the sidecar
    pip install -e ".[api,packaging]"
    pyinstaller packaging/localscribe-sidecar.spec --clean
    mkdir -p ui/src-tauri/binaries
    cp dist/localscribe-sidecar ui/src-tauri/binaries/localscribe-sidecar-$(rustc -vV | sed -n 's/host: //p')

    # 2. Run the app in dev mode
    cd ui && pnpm install && pnpm tauri dev

Release builds are produced by `.github/workflows/build-app.yml` for
macOS, Windows, and Linux.

Design references live in `docs/design_handoff_localscribe/`. Run
`open docs/design_handoff_localscribe/LocalScribe-standalone.html` to
see the high-fi prototype.

The HTTP API surface (used by the Tauri shell and available
standalone via `stt serve`) is specified in
`docs/superpowers/specs/2026-05-15-stt-desktop-ui-design.md`.
