"""Trash bin for deleted transcripts.

Deleting moves the transcript JSON, its .txt sidecar, and the audio file
into `<json_parent>/.trash/<tid>/` — a same-filesystem rename, so cheap
and atomic per file. `.trash` is a subdirectory, so the library scanner
(non-recursive *.json glob) never indexes trashed files. A manifest.json
records the original paths for restore. No auto-expiry; the user empties
the trash explicitly from settings.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

TRASH_DIRNAME = ".trash"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _execute_moves(moves: list[tuple[Path, Path]]) -> None:
    """Apply (src -> dst) renames atomically-ish: on any failure, roll back
    the moves already done so the operation is all-or-nothing. Same-filesystem
    renames make each step near-atomic; this bounds the blast radius if one
    step still fails (e.g. permissions)."""
    done: list[tuple[Path, Path]] = []
    try:
        for src, dst in moves:
            src.replace(dst)
            done.append((src, dst))
    except OSError:
        for src, dst in reversed(done):
            try:
                dst.replace(src)
            except OSError:
                pass  # best-effort rollback; original error is what matters
        raise


def trash_transcript(json_path: Path) -> Path:
    """Move a transcript's files into the trash. Returns the trash dir."""
    tid = json_path.stem
    doc: dict = {}
    try:
        doc = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass  # still trash the file; manifest just lacks title/audio

    dest = json_path.parent / TRASH_DIRNAME / tid
    dest.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}
    moves: list[tuple[Path, Path]] = [(json_path, dest / json_path.name)]
    files["json"] = str(json_path)
    txt = json_path.with_suffix(".txt")
    if txt.is_file():
        moves.append((txt, dest / txt.name))
        files["txt"] = str(txt)
    audio_raw = doc.get("audio_path")
    if audio_raw:
        audio = Path(audio_raw)
        if audio.is_file():
            moves.append((audio, dest / audio.name))
            files["audio"] = str(audio)

    manifest = {
        "tid": tid,
        "title": doc.get("title"),
        "deleted_at": _now_iso(),
        "files": files,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _execute_moves(moves)
    return dest


def _iter_trash_dirs(library_dirs: Iterable[Path]):
    for d in library_dirs:
        troot = Path(d) / TRASH_DIRNAME
        if not troot.is_dir():
            continue
        for item in sorted(troot.iterdir()):
            if item.is_dir() and (item / "manifest.json").is_file():
                yield item


def list_trash(library_dirs: Iterable[Path]) -> list[dict]:
    items: list[dict] = []
    for item in _iter_trash_dirs(library_dirs):
        try:
            manifest = json.loads((item / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        size = sum(f.stat().st_size for f in item.iterdir() if f.is_file())
        items.append({
            "tid": manifest.get("tid", item.name),
            "title": manifest.get("title"),
            "deleted_at": manifest.get("deleted_at"),
            "size_bytes": size,
        })
    items.sort(key=lambda i: i.get("deleted_at") or "", reverse=True)
    return items


def _find_trash_dir(library_dirs: Iterable[Path], tid: str) -> Path | None:
    for item in _iter_trash_dirs(library_dirs):
        if item.name == tid:
            return item
    return None


def restore(library_dirs: Iterable[Path], tid: str) -> Path:
    """Move a trashed transcript's files back to their original paths.

    Returns the restored JSON path. Raises KeyError if not in trash,
    FileExistsError if any original path is now occupied.
    """
    item = _find_trash_dir(library_dirs, tid)
    if item is None:
        raise KeyError(f"not in trash: {tid}")
    manifest = json.loads((item / "manifest.json").read_text(encoding="utf-8"))
    files: dict[str, str] = manifest.get("files") or {}

    moves: list[tuple[Path, Path]] = []
    for orig in files.values():
        dst = Path(orig)
        src = item / dst.name
        if not src.is_file():
            continue  # tolerate partially-populated trash entries
        if dst.exists():
            raise FileExistsError(f"restore target exists: {dst}")
        moves.append((src, dst))
    for _, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
    _execute_moves(moves)
    shutil.rmtree(item)
    return Path(files["json"])


def purge(library_dirs: Iterable[Path], tid: str | None = None) -> int:
    """Permanently delete one trashed item (tid given) or all. Returns count."""
    count = 0
    for item in list(_iter_trash_dirs(library_dirs)):
        if tid is not None and item.name != tid:
            continue
        shutil.rmtree(item)
        count += 1
    return count
