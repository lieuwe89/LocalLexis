from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Callable

import typer
from rich.console import Console
from rich.table import Table

from speechtotext import relabel as relabel_module
from speechtotext.devices import list_inputs
from speechtotext.asr.faster_whisper import FasterWhisperASR
from speechtotext.backend import resolve_backend
from speechtotext.config import DEFAULT_CONFIG_PATH, load_config
from speechtotext.diarize.pyannote import PyannoteDiarizer
from speechtotext.ingest.file import IngestError
from speechtotext.ingest.mic import record_to_wav
from speechtotext.ingest.watch import run_watch, should_process
from speechtotext.pipeline import Pipeline
from speechtotext.progress import console_renderer, json_renderer
from speechtotext.writer import write_transcript

app = typer.Typer(no_args_is_help=True, help="Local speech-to-text with speaker labels.")


def _progress(quiet: bool, json_logs: bool) -> Callable:
    if json_logs:
        return json_renderer()
    return console_renderer(quiet=quiet)


def _build_pipeline(cli_backend: str | None, config_path: Path) -> tuple[Pipeline, str]:
    cfg = load_config(config_path=config_path)
    backend = resolve_backend(cli_flag=cli_backend, config=cfg)
    asr = FasterWhisperASR(
        model_size=cfg.asr_model, backend=backend, download_root=cfg.model_cache_dir
    )
    if not cfg.hf_token:
        raise typer.BadParameter(
            "Hugging Face token required for pyannote diarization. "
            "Set hf_token in config or HF_TOKEN env var."
        )
    diarizer = PyannoteDiarizer(hf_token=cfg.hf_token, backend=backend)
    pipeline = Pipeline(
        config=cfg, asr=asr, diarizer=diarizer, resolved_backend=backend
    )
    return pipeline, backend


@app.command()
def transcribe(
    audio: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    lang: Annotated[str, typer.Option("--lang")] = "auto",
    speakers: Annotated[int | None, typer.Option("--speakers")] = None,
    backend: Annotated[str | None, typer.Option("--backend")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    json_logs: Annotated[bool, typer.Option("--json-logs")] = False,
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    if not should_process(audio, overwrite=overwrite):
        typer.echo(f"skipping {audio.name} (sidecar exists; use --overwrite to force)")
        raise typer.Exit(code=0)

    pipeline, resolved = _build_pipeline(backend, config_path)
    on_progress = _progress(quiet=quiet, json_logs=json_logs)
    transcript = pipeline.run(
        audio,
        language=None if lang == "auto" else lang,
        num_speakers=speakers,
        on_progress=on_progress,
    )
    write_transcript(transcript)
    typer.echo(f"wrote {audio.with_suffix('.txt').name}, {audio.with_suffix('.json').name}")


@app.command()
def record(
    out: Annotated[Path, typer.Option("--out")] = Path("recording.wav"),
    device: Annotated[str | None, typer.Option("--device")] = None,
    transcribe_after: Annotated[bool, typer.Option("--transcribe/--no-transcribe")] = True,
    backend: Annotated[str | None, typer.Option("--backend")] = None,
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    stop = threading.Event()
    typer.echo("recording — press Ctrl+C to stop")
    try:
        record_to_wav(out, device=device, stop_event=stop)
    except KeyboardInterrupt:
        stop.set()
    typer.echo(f"wrote {out}")
    if transcribe_after:
        transcribe(audio=out, lang="auto", speakers=None, backend=backend,
                   overwrite=False, quiet=False, json_logs=False, config_path=config_path)


@app.command()
def watch(
    directory: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    recursive: Annotated[bool, typer.Option("--recursive")] = False,
    exts: Annotated[str, typer.Option("--exts")] = "mp3,wav,m4a,mp4,flac",
    backend: Annotated[str | None, typer.Option("--backend")] = None,
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    cfg = load_config(config_path=config_path)
    pipeline, resolved = _build_pipeline(backend, config_path)
    extensions = [e.strip() for e in exts.split(",") if e.strip()]

    def _on_ready(path: Path) -> None:
        if not should_process(path, overwrite=False):
            return
        marker = path.with_suffix(path.suffix + ".stt-processing")
        marker.touch()
        try:
            transcript = pipeline.run(path, on_progress=console_renderer())
            write_transcript(transcript)
        except Exception as exc:
            err = path.with_suffix(path.suffix + ".stt-error.txt")
            err.write_text(f"{type(exc).__name__}: {exc}\n")
            typer.echo(f"error on {path.name}: {exc}", err=True)
        finally:
            marker.unlink(missing_ok=True)

    typer.echo(f"watching {directory} — Ctrl+C to stop")
    run_watch(
        directory=directory,
        extensions=extensions,
        debounce_seconds=cfg.watch.debounce_seconds,
        recursive=recursive,
        on_ready=_on_ready,
    )


@app.command()
def relabel(
    json_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    pairs: Annotated[list[str], typer.Argument()],
) -> None:
    mapping: dict[str, str] = {}
    for p in pairs:
        if "=" not in p:
            raise typer.BadParameter(f"expected SPEAKER_NN=Name, got {p!r}")
        sid, name = p.split("=", 1)
        mapping[sid.strip()] = name.strip()
    relabel_module.relabel(json_path, mapping)
    typer.echo(f"relabeled {len(mapping)} speakers in {json_path.name}")


@app.command()
def config(
    action: Annotated[str, typer.Argument()] = "show",
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    if action == "path":
        typer.echo(str(config_path))
    elif action == "show":
        cfg = load_config(config_path=config_path)
        typer.echo(repr(cfg))
    elif action == "edit":
        editor = subprocess.run(
            [shutil.which("editor") or "nano", str(config_path)]
        )
        raise typer.Exit(code=editor.returncode)
    else:
        raise typer.BadParameter(f"unknown action {action!r}")


@app.command()
def doctor(
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    ok = True
    ff = shutil.which("ffmpeg")
    typer.echo(f"ffmpeg: {ff or 'MISSING'}")
    if not ff:
        ok = False

    cfg = load_config(config_path=config_path)
    typer.echo(f"backend (config): {cfg.backend}")
    typer.echo(f"hf_token: {'set' if cfg.hf_token else 'MISSING'}")
    if not cfg.hf_token:
        ok = False
    typer.echo(f"model_cache_dir: {cfg.model_cache_dir}")

    try:
        import torch  # noqa
        typer.echo(f"torch: OK ({torch.__version__})")
        typer.echo(f"  cuda: {torch.cuda.is_available()}")
        typer.echo(f"  mps:  {bool(getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available())}")
    except Exception as exc:
        typer.echo(f"torch: MISSING ({exc})")
        ok = False

    raise typer.Exit(code=0 if ok else 1)


@app.command()
def devices(
    json_output: Annotated[bool, typer.Option("--json")] = False,
    include_all: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    inputs = list_inputs(include_all=include_all)
    if not inputs:
        typer.echo("no audio inputs detected; run `stt doctor`", err=True)
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(json.dumps([asdict(d) for d in inputs], indent=2))
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("idx", justify="right")
    table.add_column("name")
    table.add_column("ch", justify="right")
    table.add_column("default", justify="center")
    table.add_column("hint")
    for d in inputs:
        table.add_row(
            str(d.index),
            d.name,
            str(d.channels),
            "*" if d.default else "",
            d.hint,
        )
    Console().print(table)
