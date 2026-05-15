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
