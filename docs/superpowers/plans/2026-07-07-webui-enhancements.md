# WebUI Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship nine features across the shared web/desktop React UI and the FastAPI hub: transcription activity indicator, audio play/download, expanded web settings, rename-as-metadata, date+time display, per-line CRDT segment edits, in-transcript search, Lemonade-backed summarization with a pluggable provider, and delete-with-trash.

**Architecture:** The web UI and desktop app are one React codebase (`ui/src`); vite `--mode hub` swaps `App.web.tsx` + `platform/web.ts` and emits into `speechtotext/webui/`. All persistent edits flow through the existing CRDT PATCH mechanism (`PATCH /transcripts/{tid}`, `speechtotext/api/crdt.py`) so multi-device sync keeps working. Summarization is a backend concern: one `OpenAICompatProvider` covers Lemonade and OpenRouter; switching is config, not code. Trash is same-filesystem file moves into `<json_parent>/.trash/<tid>/`.

**Tech Stack:** FastAPI + pydantic v2 + SQLite FTS5 (backend), React 18 + zustand + vitest (frontend), httpx for provider calls, pytest for backend tests.

**Spec:** `docs/superpowers/specs/2026-07-07-webui-enhancements-design.md`

**Key reference points (read before starting):**
- CRDT merge: `speechtotext/api/crdt.py` (ops, `merge_op`, `replay_history`)
- CRDT endpoint + per-tid locking + hub forwarding: `speechtotext/api/routes_transcripts.py`
- Library index: `speechtotext/api/library_db.py` (additive `origin` migration at :256 is the pattern for new columns)
- Jobs: `speechtotext/api/jobs.py`, `speechtotext/api/runner.py`, `speechtotext/api/routes_jobs.py`
- Config: `speechtotext/config.py`, `speechtotext/api/routes_config.py`
- Routers are registered in `speechtotext/api/app.py` (~line 277)
- Frontend API client: `ui/src/api/client.ts`; types: `ui/src/api/types.ts`; stores: `ui/src/stores/`
- Test conventions: backend `tests/api/`, frontend colocated `*.test.tsx` run by `pnpm test` (vitest) from `ui/`

**Conventions for every task:**
- Backend tests: `pytest tests/api/<file> -v` from repo root. Frontend: `pnpm test -- <file>` and `pnpm tsc --noEmit` from `ui/`.
- Commit after each green task with the message given in the task.
- Python code follows the existing style: `from __future__ import annotations`, type hints, small pure helpers.
- The hub runs the same FastAPI app; "hub" and "sidecar" are the same server in these tasks.

---

### Task 1: CRDT ops `set_title` and `edit_segment`

**Files:**
- Modify: `speechtotext/api/crdt.py`
- Test: `tests/api/test_crdt_new_ops.py` (create)

The CRDT currently supports only `relabel` on `speakers.<id>` keys. Add:
- op `set_title`, key `title`, value = new display title (string).
- op `edit_segment`, key `segments.<i>.text` (i = integer index), value = new segment text (string).

`TranscriptState` grows two fields: `title: str | None` and `segment_texts: dict[str, str]` (segment index as string → current text, loaded from the doc so LWW has a `from_value` and out-of-range edits can be rejected).

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_crdt_new_ops.py`:

```python
from __future__ import annotations

import pytest

from speechtotext.api.crdt import (
    Clock,
    OpRequest,
    TranscriptState,
    merge_op,
    replay_history,
)


def _doc():
    return {
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hello"},
            {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "world"},
        ],
        "title": None,
        "_clocks": {},
        "_history": [],
    }


def test_from_json_loads_title_and_segment_texts():
    doc = _doc()
    doc["title"] = "Standup"
    state = TranscriptState.from_json(doc)
    assert state.title == "Standup"
    assert state.segment_texts == {"0": "hello", "1": "world"}


def test_set_title_applies():
    state = TranscriptState.from_json(_doc())
    req = OpRequest(op="set_title", key="title", value="Weekly sync",
                    device="dev-a", lamport_observed=0)
    new_state, lamport, op = merge_op(state, req, 0)
    assert new_state.title == "Weekly sync"
    assert op.from_value is None
    assert lamport == 1


def test_edit_segment_applies_and_records_from_value():
    state = TranscriptState.from_json(_doc())
    req = OpRequest(op="edit_segment", key="segments.1.text", value="world!",
                    device="dev-a", lamport_observed=0)
    new_state, _, op = merge_op(state, req, 0)
    assert new_state.segment_texts["1"] == "world!"
    assert op.from_value == "world"


def test_edit_segment_out_of_range_rejected():
    state = TranscriptState.from_json(_doc())
    req = OpRequest(op="edit_segment", key="segments.9.text", value="x",
                    device="dev-a", lamport_observed=0)
    with pytest.raises(ValueError, match="segment index"):
        merge_op(state, req, 0)


def test_edit_segment_bad_key_shapes_rejected():
    state = TranscriptState.from_json(_doc())
    for key in ("segments.text", "segments.1", "segments.x.text", "title"):
        req = OpRequest(op="edit_segment", key=key, value="x",
                        device="dev-a", lamport_observed=0)
        with pytest.raises(ValueError):
            merge_op(state, req, 0)


def test_set_title_requires_title_key():
    state = TranscriptState.from_json(_doc())
    req = OpRequest(op="set_title", key="speakers.SPEAKER_00", value="x",
                    device="dev-a", lamport_observed=0)
    with pytest.raises(ValueError):
        merge_op(state, req, 0)


def test_lww_older_title_op_loses():
    state = TranscriptState.from_json(_doc())
    r1 = OpRequest(op="set_title", key="title", value="First",
                   device="dev-a", lamport_observed=5)
    state, lamport, _ = merge_op(state, r1, 5)  # assigned lamport 6
    r2 = OpRequest(op="set_title", key="title", value="Second",
                   device="dev-b", lamport_observed=0)
    # hub counter already at `lamport`; new op gets lamport 7 and wins
    state, _, _ = merge_op(state, r2, lamport)
    assert state.title == "Second"
    # both ops recorded in history
    assert [op.value for op in state.history] == ["First", "Second"]


def test_replay_history_rebuilds_title_and_segments():
    state = TranscriptState.from_json(_doc())
    for req in (
        OpRequest(op="set_title", key="title", value="T", device="a", lamport_observed=0),
        OpRequest(op="edit_segment", key="segments.0.text", value="hi", device="a", lamport_observed=0),
        OpRequest(op="relabel", key="speakers.SPEAKER_00", value="Bob", device="a", lamport_observed=0),
    ):
        state, lamport, _ = merge_op(state, req, len(state.history))
    replayed = replay_history(state.history)
    assert replayed.title == "T"
    assert replayed.segment_texts.get("0") == "hi"
    assert replayed.speakers.get("SPEAKER_00") == "Bob"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_crdt_new_ops.py -v`
Expected: FAIL — `merge_op` raises `unsupported op: 'set_title'` and `TranscriptState` has no `title` attribute.

- [ ] **Step 3: Implement in `speechtotext/api/crdt.py`**

Changes (keep everything else intact):

```python
OP_RELABEL = "relabel"
OP_SET_TITLE = "set_title"
OP_EDIT_SEGMENT = "edit_segment"
SUPPORTED_OPS = frozenset({OP_RELABEL, OP_SET_TITLE, OP_EDIT_SEGMENT})
```

Extend `TranscriptState` (add the two fields and load them in `from_json`; note `replay_history` builds a state with no doc, so both need safe defaults):

```python
@dataclass
class TranscriptState:
    speakers: dict[str, str] = field(default_factory=dict)
    clocks: dict[str, Clock] = field(default_factory=dict)
    history: list[Op] = field(default_factory=list)
    title: str | None = None
    segment_texts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, doc: dict) -> "TranscriptState":
        ...  # existing speakers/clocks/history parsing unchanged
        title = doc.get("title")
        segment_texts = {
            str(i): str(seg.get("text", ""))
            for i, seg in enumerate(doc.get("segments") or [])
            if isinstance(seg, dict)
        }
        return cls(speakers=speakers, clocks=clocks, history=history,
                   title=str(title) if title is not None else None,
                   segment_texts=segment_texts)
```

Replace the key helpers with op-aware versions:

```python
_SEGMENT_KEY_RE = re.compile(r"^segments\.(\d+)\.text$")  # add `import re` at top


def _validate_key(op: str, key: str, state: TranscriptState) -> None:
    """Raise ValueError unless `key` is well-formed for `op`.

    edit_segment additionally requires the index to exist in the loaded
    doc (replay against an empty state skips that check — see merge_op).
    """
    if op == OP_RELABEL:
        parts = key.split(".", 1)
        if len(parts) != 2 or parts[0] != "speakers" or not parts[1]:
            raise ValueError(f"relabel expects 'speakers.<id>' key, got: {key!r}")
    elif op == OP_SET_TITLE:
        if key != "title":
            raise ValueError(f"set_title expects key 'title', got: {key!r}")
    elif op == OP_EDIT_SEGMENT:
        m = _SEGMENT_KEY_RE.match(key)
        if not m:
            raise ValueError(
                f"edit_segment expects 'segments.<i>.text' key, got: {key!r}"
            )
        if state.segment_texts and m.group(1) not in state.segment_texts:
            raise ValueError(f"segment index out of range: {m.group(1)}")


def _value_at_key(state: TranscriptState, key: str) -> Any:
    parts = key.split(".", 1)
    if len(parts) == 2 and parts[0] == "speakers":
        return state.speakers.get(parts[1])
    if key == "title":
        return state.title
    m = _SEGMENT_KEY_RE.match(key)
    if m:
        return state.segment_texts.get(m.group(1))
    return None


def _apply_value(state: TranscriptState, key: str, value: Any) -> None:
    """Mutate `state` (already a fresh copy in merge_op) at `key`."""
    parts = key.split(".", 1)
    if len(parts) == 2 and parts[0] == "speakers":
        state.speakers[parts[1]] = str(value) if value is not None else ""
        return
    if key == "title":
        state.title = str(value) if value is not None else None
        return
    m = _SEGMENT_KEY_RE.match(key)
    if m:
        state.segment_texts[m.group(1)] = str(value) if value is not None else ""
        return
    raise ValueError(f"unsupported key for set: {key!r}")
```

In `merge_op`, replace the hard-coded `speakers.` key validation block with `_validate_key(request.op, request.key, state)`, and build the new state as a mutable copy before applying:

```python
    new_state = TranscriptState(
        speakers=dict(state.speakers),
        clocks=dict(state.clocks),
        history=state.history + [op],
        title=state.title,
        segment_texts=dict(state.segment_texts),
    )
    if apply:
        _apply_value(new_state, request.key, request.value)
        new_state.clocks[request.key] = new_clock
    return new_state, new_lamport, op
```

(Delete the old `new_speakers`/`new_clocks`/`new_history` locals and `_set_value_at_key`.)

In `replay_history`, replace `_set_value_at_key(state.speakers, op.key, op.value)` with `_apply_value(state, op.key, op.value)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_crdt_new_ops.py -v`
Expected: all PASS.

Also run the existing CRDT + transcript suites to prove no regression:
`pytest tests/api -k "crdt or transcript or relabel" -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/crdt.py tests/api/test_crdt_new_ops.py
git commit -m "feat(crdt): set_title and edit_segment ops"
```

---

### Task 2: PATCH endpoint applies new ops, rewrites .txt, forwards to hub

**Files:**
- Modify: `speechtotext/api/routes_transcripts.py`
- Test: `tests/api/test_patch_title_segment.py` (create)

The endpoint must (a) merge new-op state back into the doc (`title`, `segments[i].text`), (b) rewrite the `.txt` sidecar whenever segments/speakers/title change so exports stay consistent, and (c) forward ops to the hub for hub-synced transcripts exactly like `_forward_relabel_to_hub` does (a local write to the synced dir would be clobbered by the next sync pull).

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_patch_title_segment.py`. Look at how existing tests in `tests/api/` build a `TestClient` with a temp library dir (grep for `TestClient` + `library_dirs` in `tests/api/` and reuse the same fixture pattern — most tests create the app via `speechtotext.api.app.create_app` or a fixture in `tests/api/conftest.py`; follow the local convention):

```python
from __future__ import annotations

import json
from pathlib import Path


def _write_transcript(dir: Path, tid: str = "meeting") -> Path:
    doc = {
        "version": 2,
        "audio_path": str(dir / f"{tid}.wav"),
        "duration_seconds": 2.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hello"},
            {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "world"},
        ],
        "models": {"asr": "faster-whisper:base.en"},
        "created_at": "2026-07-07T10:00:00+00:00",
        "_workspace_id": "ws-test",
        "_clocks": {},
        "_history": [],
    }
    p = dir / f"{tid}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    (dir / f"{tid}.txt").write_text("[00:00:00] Alice: hello\n[00:00:01] Alice: world\n")
    return p


def test_set_title_persists_and_lists(client, library_dir):
    p = _write_transcript(library_dir)
    r = client.patch("/transcripts/meeting", json={
        "op": "set_title", "key": "title", "value": "Weekly sync",
        "lamport_observed": 0,
    })
    assert r.status_code == 200
    doc = json.loads(p.read_text())
    assert doc["title"] == "Weekly sync"
    # title surfaces in the library listing
    items = client.get("/transcripts").json()
    assert any(i.get("title") == "Weekly sync" for i in items)


def test_edit_segment_rewrites_json_and_txt(client, library_dir):
    p = _write_transcript(library_dir)
    r = client.patch("/transcripts/meeting", json={
        "op": "edit_segment", "key": "segments.1.text", "value": "world, edited",
        "lamport_observed": 0,
    })
    assert r.status_code == 200
    doc = json.loads(p.read_text())
    assert doc["segments"][1]["text"] == "world, edited"
    txt = (library_dir / "meeting.txt").read_text()
    assert "world, edited" in txt
    assert "Alice" in txt  # speaker display names survive the rewrite


def test_edit_segment_out_of_range_400(client, library_dir):
    _write_transcript(library_dir)
    r = client.patch("/transcripts/meeting", json={
        "op": "edit_segment", "key": "segments.99.text", "value": "x",
        "lamport_observed": 0,
    })
    assert r.status_code == 400


def test_edited_segment_text_searchable(client, library_dir):
    _write_transcript(library_dir)
    client.patch("/transcripts/meeting", json={
        "op": "edit_segment", "key": "segments.0.text", "value": "xylophone rehearsal",
        "lamport_observed": 0,
    })
    items = client.get("/transcripts", params={"q": "xylophone"}).json()
    assert len(items) == 1
```

Adapt the `client` / `library_dir` fixtures to whatever `tests/api/conftest.py` provides (if it exposes an authorized `TestClient` factory, use it; the PATCH endpoint requires admin auth via `verify_admin_or_device`, and existing PATCH tests show how they authenticate).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_patch_title_segment.py -v`
Expected: FAIL — set_title returns 400 (`unsupported op`) before Task 1; after Task 1 the merge succeeds but `doc["title"]` is never written back, and txt rewrite is missing.

- [ ] **Step 3: Implement in `routes_transcripts.py`**

Add a txt-sidecar rewrite helper near `_atomic_write_json`:

```python
def _rewrite_txt_sidecar(json_path: Path, doc: dict) -> None:
    """Regenerate the human-readable .txt next to the JSON after an edit.

    Mirrors writer.format_txt but works on the raw doc dict so we don't
    round-trip through the Transcript dataclass (which requires fields a
    minimal/legacy doc may lack).
    """
    from speechtotext.writer import _format_timestamp

    speakers = doc.get("speakers") or {}
    lines = []
    for seg in doc.get("segments") or []:
        spk = seg.get("speaker", "")
        display = speakers.get(spk, spk)
        lines.append(
            f"[{_format_timestamp(float(seg.get('start', 0.0)))}] {display}: {seg.get('text', '')}"
        )
    txt = json_path.with_suffix(".txt")
    content = "\n".join(lines) + ("\n" if lines else "")
    tmp = txt.with_suffix(txt.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, txt)
```

Generalize hub forwarding. Rename `_forward_relabel_to_hub`'s core into a shared helper and use it from both paths:

```python
def _forward_op_to_hub(request: Request, tid: str, ops: list[dict], p: Path) -> dict:
    """Forward CRDT ops for a hub-synced transcript to the hub (see
    _forward_relabel_to_hub docstring for why local writes are wrong here).
    Returns the last op's hub response."""
    # identical body to the current _forward_relabel_to_hub, but iterating
    # over `ops` (each already shaped {op, key, value}) instead of building
    # relabel ops from a mapping; keep the lamport chaining and poke().
```

Concretely: move the existing function body, replace the `for speaker_id, new_name in mapping.items():` loop with `for op_body in ops:` and `hub.patch_json(f"/transcripts/{tid}", {**op_body, "lamport_observed": observed})`, capture the last response, `return last_response`. Then reimplement `_forward_relabel_to_hub` as:

```python
def _forward_relabel_to_hub(request, tid, mapping, p):
    ops = [
        {"op": "relabel", "key": f"speakers.{sid}", "value": name}
        for sid, name in mapping.items()
    ]
    _forward_op_to_hub(request, tid, ops, p)
    return {"ok": True, "forwarded": True}
```

In `patch_transcript_op`, after resolving `p` and before taking the lock, add the same synced-dir check `patch_relabel` has:

```python
    from speechtotext.client.paths import synced_dir
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined() and _is_under(p, synced_dir()):
        resp = _forward_op_to_hub(
            request, tid,
            [{"op": body.op, "key": body.key, "value": body.value}], p,
        )
        return PatchResult.model_validate(resp)
```

Inside the locked section, after `doc["speakers"] = dict(new_state.speakers)` add the new-field write-back:

```python
        if new_state.title is not None or "title" in doc:
            doc["title"] = new_state.title
        segments = doc.get("segments") or []
        for idx_str, text in new_state.segment_texts.items():
            i = int(idx_str)
            if 0 <= i < len(segments) and segments[i].get("text") != text:
                segments[i]["text"] = text
        ...
        _atomic_write_json(p, doc)
        _rewrite_txt_sidecar(p, doc)
```

(Rewriting the txt on every op — including relabels — is correct and fixes a latent gap: the CRDT relabel path never regenerated the txt.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/api/test_patch_title_segment.py tests/api -k "transcript or relabel or crdt" -v`
Expected: new tests PASS except `test_set_title_persists_and_lists`'s listing assertion (title in `/transcripts` list comes in Task 3 — if the fixture-level assertion fails only on that line, mark it `@pytest.mark.xfail(reason="title indexed in Task 3", strict=True)` and flip it in Task 3). All pre-existing tests PASS.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/routes_transcripts.py tests/api/test_patch_title_segment.py
git commit -m "feat(api): title + segment-edit ops persist, rewrite txt, forward to hub"
```

---

### Task 3: Library index carries `title`

**Files:**
- Modify: `speechtotext/api/library_db.py`
- Test: `tests/api/test_library_title.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
from pathlib import Path

from speechtotext.api.library_db import LibraryDB


def _doc(title=None):
    d = {
        "audio_path": "/tmp/a.wav",
        "duration_seconds": 1.0,
        "language": "en",
        "speakers": {},
        "segments": [{"start": 0, "end": 1, "speaker": "S", "text": "hi"}],
        "models": {},
        "created_at": "2026-07-07T10:00:00+00:00",
    }
    if title:
        d["title"] = title
    return d


def test_title_in_list_and_search(tmp_path: Path):
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(_doc(title="Board meeting")), encoding="utf-8")
    db = LibraryDB(tmp_path / "library.db")
    db.upsert_path(p)
    items = db.list()
    assert items[0]["title"] == "Board meeting"
    hits = db.search("board")
    assert len(hits) == 1 and hits[0]["id"] == "rec"


def test_title_absent_is_none(tmp_path: Path):
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(_doc()), encoding="utf-8")
    db = LibraryDB(tmp_path / "library.db")
    db.upsert_path(p)
    assert db.list()[0]["title"] is None


def test_title_migration_on_existing_db(tmp_path: Path):
    # open once (creates schema), close, reopen — the additive ALTER must
    # be idempotent, mirroring the `origin` column pattern
    db = LibraryDB(tmp_path / "library.db")
    db.close()
    db2 = LibraryDB(tmp_path / "library.db")
    db2.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/api/test_library_title.py -v`
Expected: FAIL — `KeyError: 'title'` (no column, not selected).

- [ ] **Step 3: Implement**

In `library_db.py`:
1. Add `title TEXT,` to the `transcripts` CREATE TABLE DDL (after `audio_basename`).
2. In `_migrate`, after the `origin` ALTER block, add the same idempotent pattern:
```python
        with self._lock, self._conn:
            try:
                self._conn.execute("ALTER TABLE transcripts ADD COLUMN title TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
```
3. In `upsert_path`: `title = doc.get("title")` (coerce `str(title)` if not None); add `title` to the INSERT column list, VALUES, and `ON CONFLICT ... SET title=excluded.title`; and make the FTS `filename` field cover the title so search matches it without an FTS schema change:
```python
        fts_filename = f"{audio_basename} {title}" if title else audio_basename
```
(pass `fts_filename` where `audio_basename` is currently inserted into `transcripts_fts.filename`).
4. Add `title` to the SELECT column lists in `list`, `search`, and `list_since`, and to `_row_to_item`:
```python
            "title": r["title"] if "title" in r.keys() else None,
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/api/test_library_title.py tests/api -k "library" -v` — all PASS.
Flip the Task-2 xfail if one was added: remove the marker, run `pytest tests/api/test_patch_title_segment.py -v` — PASS.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/library_db.py tests/api/test_library_title.py tests/api/test_patch_title_segment.py
git commit -m "feat(library): index and expose transcript title"
```

---

### Task 4: `GET /jobs` list endpoint

**Files:**
- Modify: `speechtotext/api/routes_jobs.py`
- Test: `tests/api/test_jobs_list.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations


def test_list_jobs_empty(client):
    assert client.get("/jobs").json() == []


def test_list_jobs_active_filter(client, app):
    reg = app.state.jobs
    j1 = reg.create(kind="transcribe", audio_path="/tmp/a.wav")
    j2 = reg.create(kind="transcribe", audio_path="/tmp/b.wav")
    from speechtotext.api.jobs import JobStatus
    reg.get(j2).status = JobStatus.complete

    all_jobs = client.get("/jobs").json()
    assert {j["id"] for j in all_jobs} == {j1, j2}

    active = client.get("/jobs", params={"active": "true"}).json()
    assert [j["id"] for j in active] == [j1]
    assert active[0]["kind"] == "transcribe"
    assert active[0]["status"] == "pending"
```

(Use the same `client`/`app` fixture pattern as the other `tests/api` job tests.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/api/test_jobs_list.py -v`
Expected: FAIL — 404/405 on GET /jobs.

- [ ] **Step 3: Implement**

In `routes_jobs.py`, extract the dict shape from `get_job` into a helper and add the list route **above** `get_job` (route order doesn't matter here since paths differ, but keep them adjacent):

```python
def _job_dict(rec) -> dict:
    return {
        "id": rec.id,
        "kind": rec.kind,
        "status": rec.status.value,
        "stage": rec.stage,
        "percent": rec.percent,
        "error": rec.error,
        "transcript_id": rec.transcript_id,
        "audio_path": rec.audio_path,
        "paths": rec.paths,
    }


@router.get("/jobs")
def list_jobs(request: Request, active: bool = False) -> list[dict]:
    from speechtotext.api.jobs import JobStatus
    recs = request.app.state.jobs.all()
    if active:
        recs = [r for r in recs if r.status in (JobStatus.pending, JobStatus.running)]
    return [_job_dict(r) for r in recs]
```

Refactor `get_job` to `return _job_dict(rec)`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/api/test_jobs_list.py tests/api -k "job" -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/routes_jobs.py tests/api/test_jobs_list.py
git commit -m "feat(api): GET /jobs list with active filter"
```

---

### Task 5: `GET /transcripts/{tid}/audio` with Range support

**Files:**
- Modify: `speechtotext/api/routes_transcripts.py`
- Test: `tests/api/test_audio_endpoint.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
from pathlib import Path


def _write(dir: Path, tid="rec", audio_bytes=b"RIFF" + bytes(100)):
    audio = dir / f"{tid}.wav"
    audio.write_bytes(audio_bytes)
    doc = {
        "audio_path": str(audio), "duration_seconds": 1.0, "language": "en",
        "speakers": {}, "segments": [], "models": {},
        "created_at": "2026-07-07T10:00:00+00:00",
    }
    (dir / f"{tid}.json").write_text(json.dumps(doc), encoding="utf-8")
    return audio


def test_full_audio(client, library_dir):
    audio = _write(library_dir)
    r = client.get("/transcripts/rec/audio")
    assert r.status_code == 200
    assert r.content == audio.read_bytes()
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-type"].startswith("audio/")


def test_range_request(client, library_dir):
    _write(library_dir)
    r = client.get("/transcripts/rec/audio", headers={"Range": "bytes=4-9"})
    assert r.status_code == 206
    assert r.content == bytes(6)  # bytes 4..9 of RIFF+zeros
    assert r.headers["content-range"] == "bytes 4-9/104"


def test_open_ended_range(client, library_dir):
    _write(library_dir)
    r = client.get("/transcripts/rec/audio", headers={"Range": "bytes=100-"})
    assert r.status_code == 206
    assert len(r.content) == 4


def test_audio_file_missing_404(client, library_dir):
    audio = _write(library_dir)
    audio.unlink()
    assert client.get("/transcripts/rec/audio").status_code == 404


def test_unknown_transcript_404(client):
    assert client.get("/transcripts/nope/audio").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/api/test_audio_endpoint.py -v` — FAIL (404 route not found → assertion mismatch on the 200 tests).

- [ ] **Step 3: Implement**

In `routes_transcripts.py` add (plus `import mimetypes` and `from fastapi import Response` / `from fastapi.responses import FileResponse` at the top):

```python
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")  # add `import re` if missing


@router.get("/transcripts/{tid}/audio")
def get_transcript_audio(tid: str, request: Request):
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to read transcript: {exc}")
    audio_raw = doc.get("audio_path")
    audio = Path(audio_raw) if audio_raw else None
    if audio is None or not audio.is_file():
        raise HTTPException(status_code=404, detail="audio file not found on server")

    media_type = mimetypes.guess_type(audio.name)[0] or "application/octet-stream"
    size = audio.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        m = _RANGE_RE.match(range_header.strip())
        if not m or (not m.group(1) and not m.group(2)):
            raise HTTPException(status_code=416, detail="malformed Range header")
        start = int(m.group(1)) if m.group(1) else None
        end = int(m.group(2)) if m.group(2) else None
        if start is None:          # suffix form: bytes=-N (last N bytes)
            start = max(0, size - (end or 0))
            end = size - 1
        elif end is None or end >= size:
            end = size - 1
        if start >= size or start > end:
            raise HTTPException(status_code=416, detail="range out of bounds")
        with audio.open("rb") as fh:
            fh.seek(start)
            chunk = fh.read(end - start + 1)
        return Response(
            content=chunk,
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
            },
        )
    return FileResponse(
        audio, media_type=media_type, headers={"Accept-Ranges": "bytes"}
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/api/test_audio_endpoint.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/routes_transcripts.py tests/api/test_audio_endpoint.py
git commit -m "feat(api): serve transcript audio with Range support"
```

---

### Task 6: Trash — delete, list, restore, empty

**Files:**
- Create: `speechtotext/api/trash.py`
- Create: `speechtotext/api/routes_trash.py`
- Modify: `speechtotext/api/routes_transcripts.py` (DELETE route)
- Modify: `speechtotext/api/app.py` (register router, ~line 277 block)
- Test: `tests/api/test_trash.py` (create)

Layout: deleting transcript `tid` whose JSON lives at `<dir>/<tid>.json` moves `<tid>.json`, `<tid>.txt` (if present), and the audio file into `<dir>/.trash/<tid>/`, plus a `manifest.json`:

```json
{
  "tid": "meeting",
  "title": "Weekly sync",
  "deleted_at": "2026-07-07T12:00:00+00:00",
  "files": {"json": "/abs/original/meeting.json", "txt": "...", "audio": "..."}
}
```

`.trash` is a subdirectory, so the library scanner (`d.glob("*.json")`, non-recursive) and the reconciler never see trashed files.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
from pathlib import Path

from speechtotext.api import trash


def _make(dir: Path, tid="rec", title=None):
    audio = dir / f"{tid}.wav"
    audio.write_bytes(b"AUDIO")
    doc = {
        "audio_path": str(audio), "duration_seconds": 1.0, "language": "en",
        "speakers": {}, "segments": [], "models": {},
        "created_at": "2026-07-07T10:00:00+00:00",
    }
    if title:
        doc["title"] = title
    (dir / f"{tid}.json").write_text(json.dumps(doc), encoding="utf-8")
    (dir / f"{tid}.txt").write_text("txt")
    return dir / f"{tid}.json"


def test_trash_moves_all_files(tmp_path: Path):
    p = _make(tmp_path, title="My rec")
    trash.trash_transcript(p)
    t = tmp_path / ".trash" / "rec"
    assert (t / "rec.json").is_file()
    assert (t / "rec.txt").is_file()
    assert (t / "rec.wav").is_file()
    assert not p.exists() and not (tmp_path / "rec.wav").exists()
    manifest = json.loads((t / "manifest.json").read_text())
    assert manifest["tid"] == "rec"
    assert manifest["title"] == "My rec"
    assert manifest["files"]["json"] == str(tmp_path / "rec.json")


def test_list_trash(tmp_path: Path):
    trash.trash_transcript(_make(tmp_path, "a"))
    trash.trash_transcript(_make(tmp_path, "b", title="B"))
    items = trash.list_trash([tmp_path])
    assert {i["tid"] for i in items} == {"a", "b"}
    b = next(i for i in items if i["tid"] == "b")
    assert b["title"] == "B" and b["deleted_at"]


def test_restore_round_trip(tmp_path: Path):
    p = _make(tmp_path)
    trash.trash_transcript(p)
    restored = trash.restore([tmp_path], "rec")
    assert p.is_file() and (tmp_path / "rec.wav").is_file()
    assert restored == p
    assert not (tmp_path / ".trash" / "rec").exists()


def test_restore_conflict_raises(tmp_path: Path):
    p = _make(tmp_path)
    trash.trash_transcript(p)
    _make(tmp_path)  # recreate a file at the original path
    import pytest
    with pytest.raises(FileExistsError):
        trash.restore([tmp_path], "rec")


def test_purge_one_and_all(tmp_path: Path):
    trash.trash_transcript(_make(tmp_path, "a"))
    trash.trash_transcript(_make(tmp_path, "b"))
    trash.purge([tmp_path], "a")
    assert {i["tid"] for i in trash.list_trash([tmp_path])} == {"b"}
    trash.purge([tmp_path])
    assert trash.list_trash([tmp_path]) == []


# --- route-level tests (client/library_dir fixtures as in other api tests) ---

def test_delete_endpoint_moves_to_trash_and_unlists(client, library_dir):
    _make(library_dir, "gone")
    client.get("/transcripts")  # prime index
    r = client.delete("/transcripts/gone")
    assert r.status_code == 200
    assert all(i["id"] != "gone" for i in client.get("/transcripts").json())
    trashed = client.get("/trash").json()
    assert trashed[0]["tid"] == "gone"


def test_restore_endpoint(client, library_dir):
    _make(library_dir, "back")
    client.get("/transcripts")
    client.delete("/transcripts/back")
    r = client.post("/trash/back/restore")
    assert r.status_code == 200
    assert any(i["id"] == "back" for i in client.get("/transcripts").json())
    assert client.get("/trash").json() == []


def test_empty_trash_endpoint(client, library_dir):
    _make(library_dir, "x")
    client.get("/transcripts")
    client.delete("/transcripts/x")
    assert client.delete("/trash").status_code == 200
    assert client.get("/trash").json() == []
    assert not (library_dir / ".trash" / "x").exists()


def test_restore_conflict_409(client, library_dir):
    _make(library_dir, "dup")
    client.get("/transcripts")
    client.delete("/transcripts/dup")
    _make(library_dir, "dup")
    assert client.post("/trash/dup/restore").status_code == 409
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/api/test_trash.py -v` — FAIL with `ImportError` (no `speechtotext.api.trash`).

- [ ] **Step 3: Implement `speechtotext/api/trash.py`**

```python
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
    for src, dst in moves:
        src.replace(dst)
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
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
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
```

Create `speechtotext/api/routes_trash.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from speechtotext.api import trash

router = APIRouter()


@router.get("/trash")
def list_trash(request: Request) -> list[dict]:
    return trash.list_trash(set(request.app.state.library_dirs))


@router.post("/trash/{tid}/restore")
def restore_item(tid: str, request: Request) -> dict:
    try:
        json_path = trash.restore(set(request.app.state.library_dirs), tid)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"not in trash: {tid}")
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    request.app.state.library_db.upsert_path(json_path)
    return {"ok": True, "restored": str(json_path)}


@router.delete("/trash/{tid}")
def purge_item(tid: str, request: Request) -> dict:
    n = trash.purge(set(request.app.state.library_dirs), tid)
    if n == 0:
        raise HTTPException(status_code=404, detail=f"not in trash: {tid}")
    return {"ok": True, "purged": n}


@router.delete("/trash")
def empty_trash(request: Request) -> dict:
    return {"ok": True, "purged": trash.purge(set(request.app.state.library_dirs))}
```

In `routes_transcripts.py` add the DELETE route (near `get_transcript`). Hub-synced local copies must be deleted on the hub, not locally (a local delete would resync right back):

```python
@router.delete("/transcripts/{tid}")
def delete_transcript(tid: str, request: Request) -> dict:
    from speechtotext.api import trash as trash_mod
    from speechtotext.client.paths import synced_dir

    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined() and _is_under(p, synced_dir()):
        raise HTTPException(
            status_code=409,
            detail="hub-synced transcript: delete it on the hub instead",
        )
    lock = _get_transcript_lock(request.app.state, tid)
    with lock:
        trash_mod.trash_transcript(p)
        db.delete_by_path(p)
    return {"ok": True, "trashed": True}
```

In `speechtotext/api/app.py`: import `router as trash_router` from `speechtotext.api.routes_trash` (match the import style of the neighbours) and add `app.include_router(trash_router)` in the block at ~line 277.

- [ ] **Step 4: Run tests**

Run: `pytest tests/api/test_trash.py tests/api -k "transcript" -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/trash.py speechtotext/api/routes_trash.py speechtotext/api/routes_transcripts.py speechtotext/api/app.py tests/api/test_trash.py
git commit -m "feat(api): delete-to-trash with list/restore/empty"
```

---

### Task 7: `[summarize]` config section

**Files:**
- Modify: `speechtotext/config.py`
- Modify: `speechtotext/api/routes_config.py`
- Test: `tests/api/test_config_summarize.py` (create); also extend expectations in `tests/test_config.py` if it asserts exact `Config` fields

Defaults: provider `lemonade`, base URL `http://127.0.0.1:13305/api/v1` (verified live on the homelab), model `Qwen3-30B-A3B-Instruct-2507-GGUF` (already downloaded there). The API key follows the `hf_token` pattern: stored in config.toml, exposed only as `api_key_set`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations


def test_get_config_has_summarize_defaults(client):
    cfg = client.get("/config").json()
    s = cfg["summarize"]
    assert s["provider"] == "lemonade"
    assert s["base_url"] == "http://127.0.0.1:13305/api/v1"
    assert s["model"] == "Qwen3-30B-A3B-Instruct-2507-GGUF"
    assert s["api_key_set"] is False


def test_patch_summarize_round_trips(client):
    r = client.patch("/config", json={"summarize": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct",
        "api_key": "sk-secret",
    }})
    assert r.status_code == 200
    s = r.json()["summarize"]
    assert s["provider"] == "openrouter"
    assert s["api_key_set"] is True
    assert "sk-secret" not in str(r.json())  # never echoed


def test_patch_summarize_partial(client):
    client.patch("/config", json={"summarize": {"model": "Qwen3-8B-GGUF"}})
    s = client.get("/config").json()["summarize"]
    assert s["model"] == "Qwen3-8B-GGUF"
    assert s["provider"] == "lemonade"  # untouched


def test_patch_summarize_bad_provider_422(client):
    r = client.patch("/config", json={"summarize": {"provider": "carrier-pigeon"}})
    assert r.status_code == 422
```

(These need the config-path isolation the existing `/config` tests use — grep `tests/api` for how they point `DEFAULT_CONFIG_PATH` at a tmp file, e.g. monkeypatch, and copy that.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/api/test_config_summarize.py -v` — FAIL (`KeyError: 'summarize'`).

- [ ] **Step 3: Implement**

`speechtotext/config.py` — add next to `WatchConfig`:

```python
SummarizeProvider = Literal["lemonade", "openrouter", "custom"]
_VALID_SUMMARIZE_PROVIDERS: frozenset[str] = frozenset({"lemonade", "openrouter", "custom"})

DEFAULT_SUMMARIZE_BASE_URL = "http://127.0.0.1:13305/api/v1"
DEFAULT_SUMMARIZE_MODEL = "Qwen3-30B-A3B-Instruct-2507-GGUF"


@dataclass
class SummarizeConfig:
    provider: SummarizeProvider = "lemonade"
    base_url: str = DEFAULT_SUMMARIZE_BASE_URL
    model: str = DEFAULT_SUMMARIZE_MODEL
    api_key: str | None = None
```

Add `summarize: SummarizeConfig = field(default_factory=SummarizeConfig)` to `Config`, and in `load_config`:

```python
    summarize_raw = raw.get("summarize", {}) or {}
    provider = summarize_raw.get("provider", "lemonade")
    if provider not in _VALID_SUMMARIZE_PROVIDERS:
        raise ValueError(
            f"invalid summarize provider {provider!r}; "
            f"expected one of {sorted(_VALID_SUMMARIZE_PROVIDERS)}"
        )
    summarize = SummarizeConfig(
        provider=provider,  # type: ignore[arg-type]
        base_url=str(summarize_raw.get("base_url", DEFAULT_SUMMARIZE_BASE_URL)),
        model=str(summarize_raw.get("model", DEFAULT_SUMMARIZE_MODEL)),
        api_key=summarize_raw.get("api_key"),
    )
```

and pass `summarize=summarize` in the returned `Config`.

`speechtotext/api/routes_config.py`:

```python
_SUMMARIZE_KEYS = ("provider", "base_url", "model", "api_key")


class SummarizePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["lemonade", "openrouter", "custom"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=512)

    @field_validator("base_url", "model", "api_key")
    @classmethod
    def _no_null_bytes(cls, v: str | None) -> str | None:
        if v is not None and "\x00" in v:
            raise ValueError("null byte in value")
        return v
```

Add `summarize: SummarizePatch | None = None` to `ConfigPatch`. In `_public` add:

```python
        "summarize": {
            "provider": cfg.summarize.provider,
            "base_url": cfg.summarize.base_url,
            "model": cfg.summarize.model,
            "api_key_set": bool(cfg.summarize.api_key),
        },
```

In `_dump_toml`, after the watch section, mirror the watch pattern:

```python
    summarize = d.get("summarize")
    if isinstance(summarize, dict):
        lines.append("")
        lines.append("[summarize]")
        for k in _SUMMARIZE_KEYS:
            if k in summarize:
                lines.append(f"{k} = {_toml_value(summarize[k])}")
```

In `patch_config`, mirror the `watch` merge block for `summarize` (read existing `[summarize]` table, overlay patch keys, write back).

- [ ] **Step 4: Run tests**

Run: `pytest tests/api/test_config_summarize.py tests/test_config.py tests/api -k "config" -v` — all PASS (update `tests/test_config.py` only if it asserts the exact `Config` field set).

- [ ] **Step 5: Commit**

```bash
git add speechtotext/config.py speechtotext/api/routes_config.py tests/api/test_config_summarize.py
git commit -m "feat(config): [summarize] section (provider/base_url/model/api_key)"
```

---

### Task 8: LLM provider module (`speechtotext/summarize/`)

**Files:**
- Create: `speechtotext/summarize/__init__.py`
- Create: `speechtotext/summarize/provider.py`
- Create: `speechtotext/summarize/prompt.py`
- Test: `tests/summarize/test_provider.py`, `tests/summarize/test_prompt.py` (create dir with empty `__init__.py`)

One provider implementation covers Lemonade, OpenRouter, and any OpenAI-compatible endpoint — the "pluggable" part is a config record, not a class hierarchy. `httpx` is already a dependency.

- [ ] **Step 1: Write the failing tests**

`tests/summarize/test_provider.py` — use httpx's `MockTransport` so no network is involved:

```python
from __future__ import annotations

import json

import httpx
import pytest

from speechtotext.config import SummarizeConfig
from speechtotext.summarize.provider import (
    OpenAICompatProvider,
    ProviderError,
    provider_from_config,
)


def _transport(handler):
    return httpx.MockTransport(handler)


def test_chat_posts_openai_shape_and_returns_content():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "A summary."}}]
        })

    p = OpenAICompatProvider(
        base_url="http://127.0.0.1:13305/api/v1",
        api_key="k",
        model="Qwen3-8B-GGUF",
        transport=_transport(handler),
    )
    out = p.chat([{"role": "user", "content": "hi"}])
    assert out == "A summary."
    assert seen["url"] == "http://127.0.0.1:13305/api/v1/chat/completions"
    assert seen["body"]["model"] == "Qwen3-8B-GGUF"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert seen["auth"] == "Bearer k"


def test_chat_no_api_key_sends_no_auth_header():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "authorization" not in req.headers
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}]
        })

    p = OpenAICompatProvider(base_url="http://x/v1", model="m",
                             transport=_transport(handler))
    assert p.chat([{"role": "user", "content": "q"}]) == "ok"


def test_chat_http_error_raises_provider_error():
    def handler(req):
        return httpx.Response(500, text="boom")

    p = OpenAICompatProvider(base_url="http://x/v1", model="m",
                             transport=_transport(handler))
    with pytest.raises(ProviderError, match="500"):
        p.chat([{"role": "user", "content": "q"}])


def test_chat_malformed_response_raises_provider_error():
    def handler(req):
        return httpx.Response(200, json={"unexpected": True})

    p = OpenAICompatProvider(base_url="http://x/v1", model="m",
                             transport=_transport(handler))
    with pytest.raises(ProviderError, match="malformed"):
        p.chat([{"role": "user", "content": "q"}])


def test_list_models():
    def handler(req):
        assert str(req.url).endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})

    p = OpenAICompatProvider(base_url="http://x/v1", model="m",
                             transport=_transport(handler))
    assert p.list_models() == ["m1", "m2"]


def test_provider_from_config():
    cfg = SummarizeConfig(provider="lemonade", base_url="http://h:13305/api/v1/",
                          model="M", api_key=None)
    p = provider_from_config(cfg)
    assert p.base_url == "http://h:13305/api/v1"  # trailing slash stripped
    assert p.model == "M"
```

`tests/summarize/test_prompt.py`:

```python
from __future__ import annotations

from speechtotext.summarize.prompt import build_summary_messages


def _doc():
    return {
        "title": "Standup",
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"},
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "Morning."},
            {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01", "text": "Hi Alice."},
        ],
        "duration_seconds": 120.0,
    }


def test_messages_carry_speaker_labelled_lines():
    messages = build_summary_messages(_doc())
    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert "Alice: Morning." in user
    assert "Bob: Hi Alice." in user
    assert "Standup" in user


def test_unlabelled_speaker_falls_back_to_id():
    doc = _doc()
    del doc["speakers"]["SPEAKER_01"]
    user = build_summary_messages(doc)[1]["content"]
    assert "SPEAKER_01: Hi Alice." in user
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/summarize -v` — FAIL with `ModuleNotFoundError: speechtotext.summarize`.

- [ ] **Step 3: Implement**

`speechtotext/summarize/__init__.py`:

```python
from speechtotext.summarize.provider import (  # noqa: F401
    LlmProvider,
    OpenAICompatProvider,
    ProviderError,
    provider_from_config,
)
from speechtotext.summarize.prompt import build_summary_messages  # noqa: F401
```

`speechtotext/summarize/provider.py`:

```python
"""LLM provider abstraction for transcript summarization.

One implementation covers Lemonade, OpenRouter, and any other server
that speaks the OpenAI chat-completions API — switching providers is a
config change (base_url/model/api_key), never a code change. The
Protocol exists so a genuinely different wire protocol can slot in
later without touching call sites.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from speechtotext.config import SummarizeConfig


class ProviderError(RuntimeError):
    """Provider unreachable, rejected the request, or answered garbage."""


class LlmProvider(Protocol):
    def chat(self, messages: list[dict]) -> str: ...
    def list_models(self) -> list[str]: ...


class OpenAICompatProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers=self._headers, timeout=self._timeout, transport=self._transport
        )

    def chat(self, messages: list[dict]) -> str:
        try:
            with self._client() as client:
                r = client.post(
                    f"{self.base_url}/chat/completions",
                    json={"model": self.model, "messages": messages},
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"provider returned {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"cannot reach provider: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"malformed provider response: {data!r:.500}") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("malformed provider response: empty content")
        return content

    def list_models(self) -> list[str]:
        try:
            with self._client() as client:
                r = client.get(f"{self.base_url}/models")
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"cannot list models: {exc}") from exc
        return [
            str(m["id"])
            for m in (data.get("data") or [])
            if isinstance(m, dict) and m.get("id")
        ]


def provider_from_config(cfg: SummarizeConfig) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url=cfg.base_url, model=cfg.model, api_key=cfg.api_key
    )
```

`speechtotext/summarize/prompt.py`:

```python
"""Build the summarization prompt from a transcript doc dict."""

from __future__ import annotations

_SYSTEM = (
    "You are a precise assistant that summarizes meeting and voice-note "
    "transcripts. Write in the transcript's language. Output markdown with: "
    "a 2-3 sentence overview, key points as bullets, and (only when present) "
    "decisions and action items as separate bullet lists. Do not invent "
    "content that is not in the transcript."
)


def build_summary_messages(doc: dict) -> list[dict]:
    speakers = doc.get("speakers") or {}
    lines: list[str] = []
    for seg in doc.get("segments") or []:
        spk = seg.get("speaker", "")
        display = speakers.get(spk, spk)
        lines.append(f"{display}: {seg.get('text', '')}")
    title = doc.get("title") or ""
    head = f"Transcript{f' — {title}' if title else ''}\n\n"
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": head + "\n".join(lines)},
    ]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/summarize -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/summarize tests/summarize
git commit -m "feat(summarize): OpenAI-compatible provider + prompt builder"
```

---

### Task 9: Summarize job + routes

**Files:**
- Modify: `speechtotext/api/runner.py`
- Create: `speechtotext/api/routes_summarize.py`
- Modify: `speechtotext/api/app.py` (register router)
- Test: `tests/api/test_summarize_routes.py` (create)

`POST /transcripts/{tid}/summarize` runs as a job so the existing SSE stream / job polling shows it (and the Task-13 activity chip picks it up for free). The result is written into the transcript JSON as `summary` + `summary_meta` under the per-transcript lock.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch


def _write_transcript(dir: Path, tid="talk"):
    doc = {
        "audio_path": str(dir / f"{tid}.wav"), "duration_seconds": 5.0,
        "language": "en", "speakers": {"S0": "Ann"},
        "segments": [{"start": 0, "end": 5, "speaker": "S0", "text": "we agreed to ship"}],
        "models": {}, "created_at": "2026-07-07T10:00:00+00:00",
    }
    (dir / f"{tid}.json").write_text(json.dumps(doc), encoding="utf-8")


def _wait_job(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = client.get(f"/jobs/{job_id}").json()
        if rec["status"] in ("complete", "failed"):
            return rec
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_summarize_writes_summary(client, library_dir):
    _write_transcript(library_dir)
    client.get("/transcripts")  # prime index
    with patch("speechtotext.api.runner._summarize_provider") as prov:
        prov.return_value.chat.return_value = "## Summary\nShip it."
        prov.return_value.model = "test-model"
        r = client.post("/transcripts/talk/summarize")
        assert r.status_code == 202
        rec = _wait_job(client, r.json()["job_id"])
    assert rec["status"] == "complete"
    assert rec["kind"] == "summarize"
    doc = json.loads((library_dir / "talk.json").read_text())
    assert doc["summary"] == "## Summary\nShip it."
    assert doc["summary_meta"]["model"]
    assert doc["summary_meta"]["created_at"]


def test_summarize_provider_failure_fails_job(client, library_dir):
    _write_transcript(library_dir, "bad")
    client.get("/transcripts")
    from speechtotext.summarize.provider import ProviderError
    with patch("speechtotext.api.runner._summarize_provider") as prov:
        prov.return_value.chat.side_effect = ProviderError("cannot reach provider")
        r = client.post("/transcripts/bad/summarize")
        rec = _wait_job(client, r.json()["job_id"])
    assert rec["status"] == "failed"
    assert "cannot reach provider" in rec["error"]


def test_summarize_unknown_transcript_404(client):
    assert client.post("/transcripts/nope/summarize").status_code == 404


def test_summarize_models_proxy(client):
    with patch("speechtotext.api.routes_summarize.provider_from_config") as pfc:
        pfc.return_value.list_models.return_value = ["m1", "m2"]
        r = client.get("/summarize/models")
    assert r.status_code == 200
    assert r.json() == {"models": ["m1", "m2"]}


def test_summarize_models_unreachable_502(client):
    from speechtotext.summarize.provider import ProviderError
    with patch("speechtotext.api.routes_summarize.provider_from_config") as pfc:
        pfc.return_value.list_models.side_effect = ProviderError("down")
        assert client.get("/summarize/models").status_code == 502
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/api/test_summarize_routes.py -v` — FAIL (405/404: routes missing).

- [ ] **Step 3: Implement**

In `runner.py`, add (imports at top: `import json`, `from speechtotext.summarize.prompt import build_summary_messages`, `from speechtotext.summarize.provider import ProviderError, provider_from_config`; plus `from datetime import datetime, timezone`):

```python
def _summarize_provider(cfg):
    """Indirection point so tests can patch the provider construction."""
    return provider_from_config(cfg.summarize)


def run_summarize_job(
    registry: JobRegistry,
    job_id: str,
    json_path: Path,
    write_lock: threading.Lock,
    on_written=None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Summarize a transcript with the configured LLM provider.

    `write_lock` is the per-transcript lock from routes_transcripts so a
    concurrent CRDT PATCH can't interleave with our read-modify-write.
    `on_written(json_path)` reindexes the library row after the write.
    """
    try:
        loop = asyncio.get_running_loop()
        _own_loop = False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        _own_loop = True

    emit = _make_emit(loop, registry, job_id)

    def _work() -> None:
        try:
            emit(StageEvent(stage="summarize", percent=0.0))
            cfg = load_config(config_path=config_path)
            provider = _summarize_provider(cfg)
            doc = json.loads(json_path.read_text(encoding="utf-8"))
            summary = provider.chat(build_summary_messages(doc))
            emit(StageEvent(stage="summarize", percent=0.9))
            with write_lock:
                # Re-read under the lock: a CRDT PATCH may have landed
                # while the provider was thinking.
                doc = json.loads(json_path.read_text(encoding="utf-8"))
                doc["summary"] = summary
                doc["summary_meta"] = {
                    "provider": cfg.summarize.provider,
                    "model": provider.model,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                content = json.dumps(doc, indent=2, ensure_ascii=False)
                tmp = json_path.with_suffix(json_path.suffix + ".tmp")
                tmp.write_text(content, encoding="utf-8")
                os.replace(tmp, json_path)
            if on_written:
                on_written(json_path)
            emit(CompleteEvent(
                transcript_id=json_path.stem,
                paths={"json": str(json_path)},
            ))
        except ProviderError as exc:
            emit(ErrorEvent(message=str(exc)))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            if _own_loop:
                loop.call_soon_threadsafe(loop.stop)

    threading.Thread(target=_work, daemon=True).start()
    if _own_loop:
        threading.Thread(target=lambda: (loop.run_forever(), loop.close()), daemon=True).start()
```

Create `speechtotext/api/routes_summarize.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from speechtotext.api.library import find_sidecar
from speechtotext.api.routes_transcripts import _get_transcript_lock
from speechtotext.config import DEFAULT_CONFIG_PATH, load_config
from speechtotext.summarize.provider import ProviderError, provider_from_config

router = APIRouter()


@router.post("/transcripts/{tid}/summarize", status_code=202)
def post_summarize(tid: str, request: Request) -> dict:
    from speechtotext.api import runner  # lazy, matches routes_jobs pattern

    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    registry = request.app.state.jobs
    job_id = registry.create(kind="summarize", audio_path=None)
    lock = _get_transcript_lock(request.app.state, tid)
    runner.run_summarize_job(
        registry, job_id, p, lock, on_written=db.upsert_path
    )
    return {"job_id": job_id}


@router.get("/summarize/models")
def summarize_models() -> dict:
    cfg = load_config(config_path=DEFAULT_CONFIG_PATH)
    try:
        models = provider_from_config(cfg.summarize).list_models()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"models": models}
```

Register in `app.py` next to the other routers: `app.include_router(summarize_router)`.

Also extend `ui`-facing doc shape: `GET /transcripts/{tid}` already returns the whole JSON, so `summary`/`summary_meta` flow through with no backend change.

- [ ] **Step 4: Run tests**

Run: `pytest tests/api/test_summarize_routes.py tests/summarize tests/api -k "job or config" -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/runner.py speechtotext/api/routes_summarize.py speechtotext/api/app.py tests/api/test_summarize_routes.py
git commit -m "feat(api): summarize job + /summarize/models proxy"
```

---

### Task 10: Frontend types, blob helper, store ops, date+time in Library

**Files:**
- Modify: `ui/src/api/types.ts`
- Modify: `ui/src/api/client.ts`
- Modify: `ui/src/stores/transcripts.ts`
- Modify: `ui/src/screens/LibraryScreen.tsx`
- Test: `ui/src/api/client.test.ts` (extend), `ui/src/stores/transcripts.test.ts` (create), `ui/src/screens/LibraryScreen.test.tsx` (extend)

All frontend commands run from `ui/`.

- [ ] **Step 1: Write the failing tests**

Extend `ui/src/api/client.test.ts` (follow its existing fetch-mocking pattern) with:

```ts
it('apiBlob fetches with bearer auth and returns a blob', async () => {
  // mock fetch to return new Response(new Blob([new Uint8Array([1,2,3])]))
  const blob = await apiBlob('/transcripts/x/audio');
  expect(blob.size).toBe(3);
  // assert Authorization header was set, mirroring the api() tests
});

it('apiBlob throws on non-ok', async () => {
  // mock 404 → expect rejects with message containing '404'
});
```

Create `ui/src/stores/transcripts.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useTranscripts } from './transcripts';

vi.mock('../api/client', () => ({ api: vi.fn() }));
import { api } from '../api/client';

describe('patchOp', () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    useTranscripts.setState({ byId: {} });
  });

  it('sends the op with lamport_observed from cached clocks and reloads', async () => {
    useTranscripts.setState({
      byId: {
        t1: {
          _clocks: { title: { device: 'a', lamport: 7, ts: '' } },
        } as any,
      },
    });
    vi.mocked(api).mockResolvedValue({} as any);
    await useTranscripts.getState().patchOp('t1', 'set_title', 'title', 'New');
    const [path, init] = vi.mocked(api).mock.calls[0];
    expect(path).toBe('/transcripts/t1');
    expect(init!.method).toBe('PATCH');
    expect(JSON.parse(init!.body as string)).toEqual({
      op: 'set_title', key: 'title', value: 'New', lamport_observed: 7,
    });
    // second call is the reload GET
    expect(vi.mocked(api).mock.calls[1][0]).toBe('/transcripts/t1');
  });

  it('defaults lamport_observed to 0 when doc not cached', async () => {
    vi.mocked(api).mockResolvedValue({} as any);
    await useTranscripts.getState().patchOp('t2', 'set_title', 'title', 'X');
    expect(JSON.parse(vi.mocked(api).mock.calls[0][1]!.body as string).lamport_observed).toBe(0);
  });
});
```

Extend `ui/src/screens/LibraryScreen.test.tsx`: a row whose item has `created_at: '2026-07-07T14:32:00+00:00'` renders both a date and a time (assert via `toLocaleString` output of the same Date to stay timezone-agnostic), and an item with `title: 'Renamed'` shows `Renamed` instead of the filename.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test -- client transcripts LibraryScreen`
Expected: FAIL — `apiBlob` not exported, `patchOp` missing, date renders date-only, title ignored.

- [ ] **Step 3: Implement**

`ui/src/api/types.ts`:
- `TranscriptListItem`: add `title?: string | null;`
- `TranscriptDoc`: add
```ts
  title?: string | null;
  summary?: string;
  summary_meta?: { provider: string; model: string; created_at: string };
  _clocks?: Record<string, { device: string; lamport: number; ts: string }>;
```
- `ConfigDto`: add
```ts
  summarize: { provider: 'lemonade' | 'openrouter' | 'custom'; base_url: string; model: string; api_key_set: boolean };
```
- Add:
```ts
export interface TrashItem {
  tid: string;
  title: string | null;
  deleted_at: string | null;
  size_bytes: number;
}
```

`ui/src/api/client.ts` — add below `api()`:

```ts
// Binary variant of api(): same auth + error semantics, returns a Blob.
// Used for audio playback/download — <audio src> can't send bearer headers,
// so we fetch the bytes ourselves and mount an object URL.
export async function apiBlob(path: string): Promise<Blob> {
  const info = await sidecarInfo();
  const r = await fetch(info.url + path, {
    headers: { Authorization: `Bearer ${info.token}` },
  });
  if (!r.ok) {
    if (r.status === 401) onUnauthorized?.();
    throw new Error(`${r.status} ${path}: ${await r.text()}`);
  }
  return r.blob();
}
```

`ui/src/stores/transcripts.ts` — extend the store:

```ts
interface State {
  byId: Record<string, TranscriptDoc>;
  load: (id: string) => Promise<TranscriptDoc>;
  relabel: (id: string, mapping: Record<string, string>) => Promise<void>;
  patchOp: (id: string, op: string, key: string, value: unknown) => Promise<void>;
  rename: (id: string, title: string) => Promise<void>;
  editSegment: (id: string, index: number, text: string) => Promise<void>;
}
```

```ts
  patchOp: async (id, op, key, value) => {
    const doc = useTranscripts.getState().byId[id];
    let observed = 0;
    for (const c of Object.values(doc?._clocks ?? {})) {
      if (c && typeof c.lamport === 'number') observed = Math.max(observed, c.lamport);
    }
    await api(`/transcripts/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ op, key, value, lamport_observed: observed }),
    });
    await useTranscripts.getState().load(id);
  },
  rename: async (id, title) => {
    await useTranscripts.getState().patchOp(id, 'set_title', 'title', title);
  },
  editSegment: async (id, index, text) => {
    await useTranscripts.getState().patchOp(id, 'edit_segment', `segments.${index}.text`, text);
  },
```

`ui/src/screens/LibraryScreen.tsx`:

```ts
function fmtWhen(iso?: string) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}
```

Replace `const date = i.created_at?.slice(0, 10) || '—';` with `const when = fmtWhen(i.created_at);`, render `{when}` in `.when`, and change the name line to prefer the title:

```ts
const name = i.title || (i.audio_path || i.id).split('/').pop() || i.id;
```

- [ ] **Step 4: Run tests**

Run: `pnpm test` and `pnpm tsc --noEmit` — all PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/api/types.ts ui/src/api/client.ts ui/src/stores/transcripts.ts ui/src/stores/transcripts.test.ts ui/src/screens/LibraryScreen.tsx ui/src/screens/LibraryScreen.test.tsx ui/src/api/client.test.ts
git commit -m "feat(ui): title/summary types, apiBlob, patchOp store, date+time in library"
```

---

### Task 11: Rename + delete UI (Library rows and CompleteScreen header)

**Files:**
- Modify: `ui/src/screens/LibraryScreen.tsx`
- Modify: `ui/src/screens/CompleteScreen.tsx`
- Modify: `ui/src/App.tsx`, `ui/src/App.web.tsx` (pass `tid` + new callbacks)
- Modify: `ui/src/stores/library.ts` (delete action; look at the store: it exposes `items/all/refresh/search` — add `remove`)
- Test: `ui/src/screens/LibraryScreen.test.tsx`, `ui/src/screens/CompleteScreen.test.tsx` (extend)

UI shape:
- Library row: hover actions — pencil (rename inline: input replaces the name, Enter saves / Escape cancels) and trash-can (confirm dialog "Move '<name>' to trash?" via `window.confirm`, matching the existing unpair confirm pattern).
- CompleteScreen: `<h1>` becomes click-to-edit (pencil affordance next to it); delete button in the actions row; both go through props so the screen stays store-free for existing callers.

- [ ] **Step 1: Write the failing tests**

Extend `LibraryScreen.test.tsx` (follow its existing render/mocking conventions):

```ts
it('renames a row inline', async () => {
  // render with one item {id: 'a', title: null, audio_path: '/x/rec.wav'}
  // click the row's "Rename" button (aria-label="Rename rec")
  // type 'Better name' + Enter
  // expect useTranscripts.rename mock called with ('a', 'Better name')
  // expect library refresh called afterwards
});

it('delete asks for confirmation then calls remove', async () => {
  // mock window.confirm -> true; click aria-label="Delete rec"
  // expect confirm message to contain 'Move' and 'rec' and 'trash'
  // expect useLibrary.remove mock called with 'a'
});

it('delete aborted when confirm declined', async () => {
  // window.confirm -> false; remove not called
});
```

Extend `CompleteScreen.test.tsx`:

```ts
it('title edit calls onRename', async () => {
  // render with onRename mock, click aria-label="Rename transcript",
  // clear input, type 'New title', press Enter
  // expect onRename('New title')
});

it('shows doc.title over filename when set', () => {
  // doc.title = 'Custom'; expect heading 'Custom'
});

it('delete button confirms then calls onDelete', async () => {
  // window.confirm -> true; click aria-label="Delete transcript"; expect onDelete()
});
```

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test -- LibraryScreen CompleteScreen` — FAIL (buttons don't exist).

- [ ] **Step 3: Implement**

`ui/src/stores/library.ts` — add a `remove` action next to `refresh`:

```ts
  remove: async (id: string) => {
    await api(`/transcripts/${id}`, { method: 'DELETE' });
    await useLibrary.getState().refresh();
  },
```

(match the store's existing shape — if actions live in the `create()` object, add it there and to its `State` interface.)

`LibraryScreen.tsx` — add per-row state and actions:

```ts
const rename = useTranscripts(s => s.rename);
const remove = useLibrary(s => s.remove);
const [editing, setEditing] = useState<{ id: string; draft: string } | null>(null);
```

In the row render, stop propagation so row-click doesn't navigate while editing:

```tsx
{editing?.id === i.id ? (
  <input
    className="rename-input"
    autoFocus
    value={editing.draft}
    onClick={e => e.stopPropagation()}
    onChange={e => setEditing({ id: i.id, draft: e.target.value })}
    onKeyDown={async e => {
      if (e.key === 'Enter' && editing.draft.trim()) {
        await rename(i.id, editing.draft.trim());
        setEditing(null);
        refresh();
      } else if (e.key === 'Escape') setEditing(null);
    }}
  />
) : (
  <span className="name">{name}…</span>  // existing name + hub badge
)}
<button
  className="icon-btn row-action"
  aria-label={`Rename ${name}`}
  title="Rename"
  onClick={e => { e.stopPropagation(); setEditing({ id: i.id, draft: i.title || name }); }}
><Icon name="pencil" size={13} /></button>
<button
  className="icon-btn row-action"
  aria-label={`Delete ${name}`}
  title="Move to trash"
  onClick={async e => {
    e.stopPropagation();
    if (window.confirm(`Move '${name}' to trash?\n\nYou can restore it from Settings → Trash.`)) {
      await remove(i.id).catch(err => window.alert(`Delete failed: ${err}`));
    }
  }}
><Icon name="trash" size={13} /></button>
```

Check `ui/src/primitives/Icon.tsx` for available icon names; if `pencil`/`trash` don't exist, add them there following the existing SVG-path pattern (small stroke icons).

`CompleteScreen.tsx` — extend props:

```ts
interface Props {
  doc: TranscriptDoc;
  txtPath?: string;
  jsonPath?: string;
  onRelabel: (mapping: Record<string, string>) => Promise<void> | void;
  onRename?: (title: string) => Promise<void> | void;
  onDelete?: () => Promise<void> | void;
}
```

Title resolution becomes:

```ts
const fileTitle = doc.audio_path?.split('/').pop()?.replace(/\.[^.]+$/, '') || 'Transcript';
const title = doc.title || fileTitle;
```

Replace the static `<h1>{title}</h1>` with an editable variant (local state `titleEdit: string | null`):

```tsx
{titleEdit !== null ? (
  <input
    className="title-input" autoFocus value={titleEdit}
    onChange={e => setTitleEdit(e.target.value)}
    onKeyDown={async e => {
      if (e.key === 'Enter' && titleEdit.trim()) {
        await onRename?.(titleEdit.trim());
        setTitleEdit(null);
      } else if (e.key === 'Escape') setTitleEdit(null);
    }}
    onBlur={() => setTitleEdit(null)}
  />
) : (
  <h1>
    {title}
    {onRename && (
      <button className="icon-btn" aria-label="Rename transcript" title="Rename"
              onClick={() => setTitleEdit(title)}>
        <Icon name="pencil" size={14} />
      </button>
    )}
  </h1>
)}
```

Delete button in `.actions` (after the JSON button):

```tsx
{onDelete && (
  <button className="icon-btn" aria-label="Delete transcript" title="Move to trash"
          onClick={async () => {
            if (window.confirm(`Move '${title}' to trash?\n\nYou can restore it from Settings → Trash.`)) {
              await onDelete();
            }
          }}>
    <Icon name="trash" size={15} />
  </button>
)}
```

Wire up both shells. `App.web.tsx` (CompleteScreen usage, ~line 69):

```tsx
<CompleteScreen
  key={tid}
  doc={currentDoc}
  txtPath={currentDoc.paths?.txt}
  jsonPath={currentDoc.paths?.json}
  onRelabel={async (m) => { await relabel(tid, m); }}
  onRename={async (t) => { await renameTranscript(tid, t); }}
  onDelete={async () => {
    await removeTranscript(tid);
    setRoute('library');
  }}
/>
```

with `const renameTranscript = useTranscripts(s => s.rename);` and `const removeTranscript = useLibrary(s => s.remove);`. Do the same in `App.tsx` where it renders CompleteScreen (it has `tid` in scope — check the surrounding code and mirror the web wiring; after delete, route to `'library'`).

- [ ] **Step 4: Run tests**

Run: `pnpm test` and `pnpm tsc --noEmit` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src
git commit -m "feat(ui): rename and delete-to-trash from library and transcript view"
```

---

### Task 12: Per-line segment editing in CompleteScreen

**Files:**
- Modify: `ui/src/screens/CompleteScreen.tsx`
- Test: `ui/src/screens/CompleteScreen.test.tsx` (extend)

- [ ] **Step 1: Write the failing tests**

```ts
it('edits a segment line and calls onEditSegment with index and text', async () => {
  // render with onEditSegment mock
  // click aria-label="Edit line 2" (second segment)
  // textarea/input appears pre-filled with the segment text
  // change to 'corrected text', press Enter
  // expect onEditSegment(1, 'corrected text')
});

it('escape cancels the edit without calling onEditSegment', async () => {});

it('no edit buttons when onEditSegment not provided', () => {});
```

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test -- CompleteScreen` — FAIL.

- [ ] **Step 3: Implement**

Add to Props: `onEditSegment?: (index: number, text: string) => Promise<void> | void;`
Local state: `const [segEdit, setSegEdit] = useState<{ i: number; draft: string } | null>(null);`

In the transcript turn render (the `<p>{seg.text}</p>` block):

```tsx
{segEdit?.i === i ? (
  <textarea
    className="seg-edit" autoFocus rows={2} value={segEdit.draft}
    onChange={e => setSegEdit({ i, draft: e.target.value })}
    onKeyDown={async e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (segEdit.draft.trim() && segEdit.draft !== seg.text) {
          await onEditSegment?.(i, segEdit.draft.trim());
        }
        setSegEdit(null);
      } else if (e.key === 'Escape') setSegEdit(null);
    }}
  />
) : (
  <p>
    {seg.text}
    {onEditSegment && (
      <button className="icon-btn seg-edit-btn" aria-label={`Edit line ${i + 1}`}
              title="Edit line" onClick={() => setSegEdit({ i, draft: seg.text })}>
        <Icon name="pencil" size={12} />
      </button>
    )}
  </p>
)}
```

Wire `onEditSegment={async (i, t) => { await editSegment(tid, i, t); }}` in both `App.web.tsx` and `App.tsx` (`const editSegment = useTranscripts(s => s.editSegment);`). Add minimal CSS for `.seg-edit-btn` (hidden until `.turn:hover`) and `.seg-edit` in the stylesheet the screens already use (`ui/src/styles/global.css` — grep for `.turn` to find the right block).

- [ ] **Step 4: Run tests**

Run: `pnpm test` and `pnpm tsc --noEmit` — PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src
git commit -m "feat(ui): per-line transcript editing"
```

---

### Task 13: In-transcript search

**Files:**
- Modify: `ui/src/screens/CompleteScreen.tsx`
- Test: `ui/src/screens/CompleteScreen.test.tsx` (extend)

Client-side only: a search box above the transcript; case-insensitive substring match across segment texts; `<mark>` highlights; match counter ("3 / 14"); next/prev buttons + Enter/Shift+Enter; current match scrolled into view.

- [ ] **Step 1: Write the failing tests**

```ts
it('highlights matches and shows the count', async () => {
  // segments: ['hello world', 'the world turns', 'goodbye']
  // type 'world' into aria-label="Search in transcript"
  // expect two <mark> elements and text '1 / 2'
});

it('next/prev cycle through matches and wrap', async () => {
  // click aria-label="Next match" twice -> back to '1 / 2'
});

it('no matches shows 0 / 0', async () => {});
```

(jsdom lacks `scrollIntoView`; stub it in the test file: `Element.prototype.scrollIntoView = vi.fn()`.)

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test -- CompleteScreen` — FAIL.

- [ ] **Step 3: Implement**

State + derived matches in CompleteScreen:

```ts
const [findQ, setFindQ] = useState('');
const [findIdx, setFindIdx] = useState(0);

// list of segment indexes containing the query (a segment with multiple
// hits counts once — per-line navigation is the useful granularity here)
const matches = useMemo(() => {
  const q = findQ.trim().toLowerCase();
  if (!q) return [];
  return doc.segments.reduce<number[]>((acc, s, i) => {
    if (s.text.toLowerCase().includes(q)) acc.push(i);
    return acc;
  }, []);
}, [doc.segments, findQ]);

useEffect(() => { setFindIdx(0); }, [findQ]);
const currentMatchSeg = matches.length ? matches[findIdx % matches.length] : null;

const segRefs = useRef<Record<number, HTMLDivElement | null>>({});
useEffect(() => {
  if (currentMatchSeg !== null) {
    segRefs.current[currentMatchSeg]?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
}, [currentMatchSeg]);

const step = (dir: 1 | -1) => {
  if (!matches.length) return;
  setFindIdx(i => (i + dir + matches.length) % matches.length);
};
```

Highlight helper (top of file, beside `fmtTimestamp`):

```tsx
function highlight(text: string, q: string): React.ReactNode {
  if (!q) return text;
  const lower = text.toLowerCase();
  const ql = q.toLowerCase();
  const parts: React.ReactNode[] = [];
  let pos = 0;
  for (let hit = lower.indexOf(ql); hit !== -1; hit = lower.indexOf(ql, pos)) {
    if (hit > pos) parts.push(text.slice(pos, hit));
    parts.push(<mark key={hit}>{text.slice(hit, hit + q.length)}</mark>);
    pos = hit + q.length;
  }
  parts.push(text.slice(pos));
  return parts;
}
```

Search bar between `.relabel` and `.transcript`:

```tsx
<div className="doc-find">
  <Icon name="search" size={13} />
  <input
    aria-label="Search in transcript"
    placeholder="Find in transcript…"
    value={findQ}
    onChange={e => setFindQ(e.target.value)}
    onKeyDown={e => {
      if (e.key === 'Enter') step(e.shiftKey ? -1 : 1);
    }}
  />
  {findQ.trim() && (
    <>
      <span className="find-count">{matches.length ? `${(findIdx % matches.length) + 1} / ${matches.length}` : '0 / 0'}</span>
      <button className="icon-btn" aria-label="Previous match" onClick={() => step(-1)}>↑</button>
      <button className="icon-btn" aria-label="Next match" onClick={() => step(1)}>↓</button>
    </>
  )}
</div>
```

In the turn render: attach `ref={el => { segRefs.current[i] = el; }}` to the `.turn` div, render `<p>{highlight(seg.text, findQ.trim())}…</p>` instead of raw text (compose with Task 12: highlight applies in the non-editing branch), and add class `find-current` when `i === currentMatchSeg` (style it in global.css with a subtle outline).

- [ ] **Step 4: Run tests**

Run: `pnpm test` and `pnpm tsc --noEmit` — PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src
git commit -m "feat(ui): in-transcript search with match navigation"
```

---

### Task 14: Audio player + download in CompleteScreen

**Files:**
- Create: `ui/src/screens/AudioPanel.tsx`
- Modify: `ui/src/screens/CompleteScreen.tsx`
- Test: `ui/src/screens/AudioPanel.test.tsx` (create)

The audio is fetched as an authenticated blob (`apiBlob`, Task 10) and mounted as an object URL — `<audio>` can't send bearer headers. Clicking a segment timestamp seeks the player.

- [ ] **Step 1: Write the failing tests**

`ui/src/screens/AudioPanel.test.tsx`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AudioPanel } from './AudioPanel';

vi.mock('../api/client', () => ({ apiBlob: vi.fn() }));
import { apiBlob } from '../api/client';

beforeEach(() => {
  vi.mocked(apiBlob).mockReset();
  // jsdom has no createObjectURL
  URL.createObjectURL = vi.fn(() => 'blob:mock');
  URL.revokeObjectURL = vi.fn();
});

it('loads audio blob and renders a player + download link', async () => {
  vi.mocked(apiBlob).mockResolvedValue(new Blob([new Uint8Array(4)], { type: 'audio/wav' }));
  render(<AudioPanel tid="t1" filename="rec.wav" />);
  await waitFor(() => expect(screen.getByLabelText('Transcript audio')).toBeInTheDocument());
  expect(apiBlob).toHaveBeenCalledWith('/transcripts/t1/audio');
  const dl = screen.getByLabelText('Download audio') as HTMLAnchorElement;
  expect(dl.getAttribute('download')).toBe('rec.wav');
  expect(dl.getAttribute('href')).toBe('blob:mock');
});

it('shows unavailable state on fetch failure', async () => {
  vi.mocked(apiBlob).mockRejectedValue(new Error('404 audio'));
  render(<AudioPanel tid="t1" filename="rec.wav" />);
  await waitFor(() => expect(screen.getByText(/audio unavailable/i)).toBeInTheDocument());
});
```

Extend `CompleteScreen.test.tsx`: with `withAudio` prop set, clicking a segment timestamp calls the panel's seek (assert via the exposed callback — see implementation: CompleteScreen holds a `seekRef` and passes `onReady`).

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test -- AudioPanel CompleteScreen` — FAIL (module missing).

- [ ] **Step 3: Implement `ui/src/screens/AudioPanel.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react';
import { apiBlob } from '../api/client';
import { Icon } from '../primitives/Icon';

interface Props {
  tid: string;
  filename: string;
  /** Receives a seek(seconds) function once the player is ready. */
  onReady?: (seek: (secs: number) => void) => void;
}

export function AudioPanel({ tid, filename, onReady }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    apiBlob(`/transcripts/${tid}/audio`)
      .then(blob => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [tid]);

  useEffect(() => {
    if (url && onReady) {
      onReady((secs: number) => {
        const el = audioRef.current;
        if (el) {
          el.currentTime = secs;
          el.play().catch(() => {});
        }
      });
    }
  }, [url, onReady]);

  if (failed) {
    return <div className="audio-panel audio-unavailable">audio unavailable on server</div>;
  }
  if (!url) {
    return <div className="audio-panel">loading audio…</div>;
  }
  return (
    <div className="audio-panel">
      <audio ref={audioRef} aria-label="Transcript audio" controls src={url} preload="metadata" />
      <a className="icon-btn" aria-label="Download audio" title="Download audio"
         href={url} download={filename}>
        <Icon name="download" size={15} />
      </a>
    </div>
  );
}
```

(Add a `download` icon to `Icon.tsx` if missing.)

In `CompleteScreen.tsx`: add props `tid?: string;` (panel only renders when provided — old callers unchanged). Below the `.doc-head`:

```tsx
const seekRef = useRef<((secs: number) => void) | null>(null);
...
{tid && (
  <AudioPanel
    tid={tid}
    filename={doc.audio_path?.split('/').pop() || `${title}.audio`}
    onReady={fn => { seekRef.current = fn; }}
  />
)}
```

Make the timestamp cell clickable:

```tsx
<div
  className="ts ts-seek"
  role="button"
  title="Play from here"
  onClick={() => seekRef.current?.(seg.start)}
>{fmtTimestamp(seg.start)}</div>
```

Pass `tid={tid}` from `App.web.tsx` and `App.tsx`.

- [ ] **Step 4: Run tests**

Run: `pnpm test` and `pnpm tsc --noEmit` — PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src
git commit -m "feat(ui): audio playback + download with segment seek"
```

---

### Task 15: Activity chip in the web shell

**Files:**
- Create: `ui/src/chrome/ActivityChip.tsx`
- Modify: `ui/src/App.web.tsx`
- Test: `ui/src/chrome/ActivityChip.test.tsx` (create)

Polls `GET /jobs?active=true` every 3 s while the tab is visible (spec allows polling as the transport; the per-job SSE stream stays the ProgressScreen's tool). Shows a spinner + "Transcribing <name> — NN%" (or the stage name for non-transcribe kinds, e.g. "Summarizing"); hidden when idle.

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ActivityChip } from './ActivityChip';

vi.mock('../api/client', () => ({ api: vi.fn() }));
import { api } from '../api/client';

beforeEach(() => { vi.useFakeTimers(); vi.mocked(api).mockReset(); });
afterEach(() => { vi.useRealTimers(); });

const job = (over = {}) => ({
  id: 'j1', kind: 'transcribe', status: 'running', stage: 'asr',
  percent: 0.42, error: null, transcript_id: null,
  audio_path: '/x/standup.wav', paths: {}, ...over,
});

it('renders nothing when no active jobs', async () => {
  vi.mocked(api).mockResolvedValue([]);
  render(<ActivityChip />);
  await act(() => vi.advanceTimersByTimeAsync(10));
  expect(screen.queryByRole('status')).toBeNull();
});

it('shows job name and percent while active', async () => {
  vi.mocked(api).mockResolvedValue([job()]);
  render(<ActivityChip />);
  await act(() => vi.advanceTimersByTimeAsync(10));
  const chip = screen.getByRole('status');
  expect(chip.textContent).toContain('standup');
  expect(chip.textContent).toContain('42%');
  expect(vi.mocked(api)).toHaveBeenCalledWith('/jobs?active=true');
});

it('polls on an interval and clears when jobs finish', async () => {
  vi.mocked(api).mockResolvedValueOnce([job()]).mockResolvedValue([]);
  render(<ActivityChip />);
  await act(() => vi.advanceTimersByTimeAsync(10));
  expect(screen.getByRole('status')).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(3100));
  expect(screen.queryByRole('status')).toBeNull();
});

it('labels summarize jobs', async () => {
  vi.mocked(api).mockResolvedValue([job({ kind: 'summarize', audio_path: null, percent: 0 })]);
  render(<ActivityChip />);
  await act(() => vi.advanceTimersByTimeAsync(10));
  expect(screen.getByRole('status').textContent).toMatch(/Summarizing/);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test -- ActivityChip` — FAIL (module missing).

- [ ] **Step 3: Implement `ui/src/chrome/ActivityChip.tsx`**

```tsx
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { JobRecord } from '../api/types';

const POLL_MS = 3000;

const KIND_LABEL: Record<string, string> = {
  transcribe: 'Transcribing',
  hub_upload: 'Transcribing',
  record: 'Recording',
  summarize: 'Summarizing',
};

function jobLabel(j: JobRecord): string {
  const verb = KIND_LABEL[j.kind] ?? 'Working';
  const name = j.audio_path?.split('/').pop()?.replace(/\.[^.]+$/, '');
  const pct = j.percent > 0 ? ` — ${Math.round(j.percent * 100)}%` : '';
  return name ? `${verb} ${name}${pct}` : `${verb}${pct}`;
}

export function ActivityChip() {
  const [jobs, setJobs] = useState<JobRecord[]>([]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      // Skip network work while the tab is hidden; re-poll on return.
      if (document.visibilityState !== 'hidden') {
        try {
          setJobs(await api<JobRecord[]>('/jobs?active=true'));
        } catch {
          /* transient failures keep the last state; next tick retries */
        }
      }
      timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, []);

  if (jobs.length === 0) return null;
  const first = jobs[0];
  return (
    <div className="activity-chip" role="status">
      <span className="activity-spinner" aria-hidden="true" />
      <span>{jobLabel(first)}</span>
      {jobs.length > 1 && <span className="activity-more">+{jobs.length - 1}</span>}
    </div>
  );
}
```

Mount it in `App.web.tsx` inside the nav (after the Settings button):

```tsx
<nav className="web-sidebar">
  <button ...>Library</button>
  <button ...>Settings</button>
  <ActivityChip />
</nav>
```

Add CSS in `global.css` near the `.web-sidebar` rules: `.activity-chip` (small pill, `--bg-elev` background, high-contrast text) and an `@keyframes` spin for `.activity-spinner` (12px circle with a transparent quadrant border). Every web-only element must have explicit CSS — bare unstyled elements was a shipped bug last phase (see DEVLOG 2026-07-06).

- [ ] **Step 4: Run tests**

Run: `pnpm test` and `pnpm tsc --noEmit` — PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src
git commit -m "feat(webui): transcription activity chip"
```

---

### Task 16: Shared settings form + web settings expansion (config, summarize, trash)

**Files:**
- Create: `ui/src/screens/settings/SettingsForm.tsx` (extracted from SettingsScreen)
- Create: `ui/src/screens/settings/SummarizeSettings.tsx`
- Create: `ui/src/screens/settings/TrashSection.tsx`
- Modify: `ui/src/screens/SettingsScreen.tsx` (use SettingsForm + mount SummarizeSettings and TrashSection)
- Modify: `ui/src/screens/web/WebSettingsScreen.tsx` (mount all three above pairing)
- Test: `ui/src/screens/settings/SettingsForm.test.tsx`, `SummarizeSettings.test.tsx`, `TrashSection.test.tsx` (create)

Extraction constraint: `SettingsScreen.tsx` imports `@tauri-apps/api/core` — none of that may move into the shared components, or the hub bundle gains tauri code (the build gate `grep -rl @tauri-apps` on the hub dist must stay empty). The `Field`/`InfoButton` helpers at the bottom of SettingsScreen move into `SettingsForm.tsx` and are re-exported for SettingsScreen's hub sections.

- [ ] **Step 1: Write the failing tests**

`SettingsForm.test.tsx` — port the config-form assertions that exist in `SettingsScreen.test.tsx` (if any) plus:

```ts
it('renders config fields from the store and saves a patch', async () => {
  // mock useConfig store with a cfg fixture (include summarize + watch)
  // change backend select to 'cpu', click Save
  // expect patch called with {backend: 'cpu'}
});

it('renders watch extensions as comma list', () => {});
```

`SummarizeSettings.test.tsx`:

```ts
it('loads models from /summarize/models into a datalist/select', async () => {
  // api mock: GET /summarize/models -> {models: ['m1','m2']}
  // expect both options present
});

it('falls back to free-text model input when models fetch fails', async () => {});

it('saves provider/base_url/model/api_key via config patch', async () => {
  // fill fields, save, expect patch({summarize: {...}})
});

it('provider preset buttons fill base_url', async () => {
  // choosing 'openrouter' sets base_url input to https://openrouter.ai/api/v1
});
```

`TrashSection.test.tsx`:

```ts
it('lists trash items with title and date', async () => {
  // api GET /trash -> [{tid:'a', title:'Old', deleted_at:'2026-07-07T10:00:00Z', size_bytes: 1024}]
});

it('restore calls POST /trash/{tid}/restore and refreshes', async () => {});

it('empty trash confirms with cannot-be-undone wording then DELETE /trash', async () => {
  // window.confirm mock; assert message contains 'cannot be undone'
});

it('restore conflict (409) surfaces an error message', async () => {});
```

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test -- settings` — FAIL (modules missing).

- [ ] **Step 3: Implement**

`SettingsForm.tsx`: move from `SettingsScreen.tsx` — the `INFO` map, `ModelStatus`/`formatSize`/`statusLabel`, the `Draft` type, the config-field JSX (backend, ASR model, HF token, cache dir, out dir, watch trio, Save button) and the `Field`/`InfoButton` components (export `Field` and `InfoButton`). The component keeps using `useConfig` + `api('/models/whisper')` exactly as before:

```tsx
export function SettingsForm() {
  const cfg = useConfig(s => s.cfg);
  const load = useConfig(s => s.load);
  const patch = useConfig(s => s.patch);
  // draft/dirty/saving state, models fetch, set(), save() — moved verbatim
  if (!cfg) return <p style={{ color: 'var(--ink-muted)' }}>Loading…</p>;
  return <>{/* fields + save button, verbatim from SettingsScreen */}</>;
}
```

`SettingsScreen.tsx` shrinks to: `<div className="settings"><SettingsForm /><SummarizeSettings /><TrashSection />{hub sections…}</div>` — all tauri/hub/BLE/pairing code stays here untouched. Import `Field` from the new module.

`SummarizeSettings.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useConfig } from '../../stores/config';
import { Field } from './SettingsForm';

const PRESETS: Record<string, string> = {
  lemonade: 'http://127.0.0.1:13305/api/v1',
  openrouter: 'https://openrouter.ai/api/v1',
};

export function SummarizeSettings() {
  const cfg = useConfig(s => s.cfg);
  const patch = useConfig(s => s.patch);
  const [draft, setDraft] = useState<{ provider?: string; base_url?: string; model?: string; api_key?: string }>({});
  const [models, setModels] = useState<string[] | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ models: string[] }>('/summarize/models')
      .then(r => setModels(r.models))
      .catch(() => setModels(null)); // provider down → free-text model input
  }, [cfg?.summarize.base_url]);

  if (!cfg) return null;
  const s = cfg.summarize;
  const val = <K extends keyof typeof draft>(k: K) => draft[k] ?? (s as any)[k] ?? '';
  const dirty = Object.keys(draft).length > 0;

  const setProvider = (p: string) => {
    setDraft(d => ({ ...d, provider: p, ...(PRESETS[p] ? { base_url: PRESETS[p] } : {}) }));
  };

  const save = async () => {
    setSaving(true);
    try { await patch({ summarize: draft } as any); setDraft({}); } catch {}
    setSaving(false);
  };

  return (
    <section className="summarize-settings" style={{ marginTop: '2rem', borderTop: '1px solid var(--rule)', paddingTop: '1.25rem' }}>
      <h2 style={{ margin: '0 0 0.5rem' }}>Summarization</h2>
      <p style={{ color: 'var(--ink-muted)', marginTop: 0 }}>
        LLM used for the Summarize button. Any OpenAI-compatible server works —
        Lemonade on this machine, OpenRouter, or a custom endpoint.
      </p>
      <Field label="Provider">
        <select value={val('provider')} onChange={e => setProvider(e.target.value)}>
          {['lemonade', 'openrouter', 'custom'].map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </Field>
      <Field label="Base URL">
        <input value={val('base_url')} onChange={e => setDraft(d => ({ ...d, base_url: e.target.value }))} />
      </Field>
      <Field label="Model">
        {models && models.length > 0 ? (
          <select value={val('model')} onChange={e => setDraft(d => ({ ...d, model: e.target.value }))}>
            {!models.includes(val('model')) && <option value={val('model')}>{val('model')}</option>}
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        ) : (
          <input value={val('model')} onChange={e => setDraft(d => ({ ...d, model: e.target.value }))} />
        )}
      </Field>
      <Field label="API key">
        <input type="password" placeholder={s.api_key_set ? '••••••••' : 'none (Lemonade default)'}
               value={draft.api_key ?? ''} onChange={e => setDraft(d => ({ ...d, api_key: e.target.value }))} />
      </Field>
      <div className="settings-actions">
        <button className="btn-apply" disabled={!dirty || saving} onClick={save}>
          {dirty ? (saving ? 'Saving…' : 'Save') : 'Saved'}
        </button>
      </div>
    </section>
  );
}
```

`TrashSection.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { TrashItem } from '../../api/types';

function fmtSize(b: number) {
  if (b >= 1e9) return `${(b / 1e9).toFixed(1)} GB`;
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(b / 1e3))} KB`;
}

export function TrashSection() {
  const [items, setItems] = useState<TrashItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api<TrashItem[]>('/trash').then(setItems).catch(() => setItems([]));
  useEffect(() => { refresh(); }, []);

  const restore = async (t: TrashItem) => {
    setError(null);
    try {
      await api(`/trash/${encodeURIComponent(t.tid)}/restore`, { method: 'POST' });
      await refresh();
    } catch (e) {
      setError(`Restore failed: ${e}`);
    }
  };

  const empty = async () => {
    if (!window.confirm(
      `Permanently delete ${items.length} item(s) from the trash?\n\nThis cannot be undone.`,
    )) return;
    setError(null);
    try {
      await api('/trash', { method: 'DELETE' });
      await refresh();
    } catch (e) {
      setError(`Empty trash failed: ${e}`);
    }
  };

  return (
    <section className="trash-section" style={{ marginTop: '2rem', borderTop: '1px solid var(--rule)', paddingTop: '1.25rem' }}>
      <h2 style={{ margin: '0 0 0.5rem' }}>Trash ({items.length})</h2>
      {error && <p role="alert" style={{ color: 'var(--ink-error, crimson)' }}>{error}</p>}
      {items.length === 0 ? (
        <p style={{ color: 'var(--ink-muted)' }}>Trash is empty.</p>
      ) : (
        <>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {items.map(t => (
              <li key={t.tid} style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', padding: '0.5rem 0', borderBottom: '1px solid var(--rule, #e5e0d3)' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong>{t.title || t.tid}</strong>
                  <div style={{ fontSize: '0.85em', color: 'var(--ink-muted)' }}>
                    deleted {t.deleted_at ? new Date(t.deleted_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—'} · {fmtSize(t.size_bytes)}
                  </div>
                </div>
                <button type="button" onClick={() => restore(t)}>Restore</button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={empty}>Empty trash</button>
        </>
      )}
    </section>
  );
}
```

`WebSettingsScreen.tsx` becomes:

```tsx
return (
  <div className="web-settings">
    <SettingsForm />
    <SummarizeSettings />
    <TrashSection />
    <section>{/* existing Pair a device */}</section>
    <section>{/* existing Paired devices */}</section>
  </div>
);
```

Check `global.css` has `.web-settings` styles that keep the imported form legible on web (the settings form CSS is currently under `.settings` — either reuse the class on the wrapper: `className="web-settings settings"`, or extend the CSS selectors; the wrapper-class route is less churn).

- [ ] **Step 4: Run tests**

Run: `pnpm test` and `pnpm tsc --noEmit` — PASS, including the pre-existing SettingsScreen tests (the extraction must not change behavior).

- [ ] **Step 5: Commit**

```bash
git add ui/src
git commit -m "feat(ui): shared settings form, summarize + trash settings on web and desktop"
```

---

### Task 17: Summarize button + summary panel in CompleteScreen

**Files:**
- Modify: `ui/src/screens/CompleteScreen.tsx`
- Modify: `ui/src/stores/transcripts.ts` (summarize action)
- Test: `ui/src/screens/CompleteScreen.test.tsx`, `ui/src/stores/transcripts.test.ts` (extend)

- [ ] **Step 1: Write the failing tests**

`transcripts.test.ts`:

```ts
it('summarize posts, polls the job to completion, then reloads', async () => {
  vi.mocked(api)
    .mockResolvedValueOnce({ job_id: 'j9' })                     // POST summarize
    .mockResolvedValueOnce({ id: 'j9', status: 'running' } as any)  // poll 1
    .mockResolvedValueOnce({ id: 'j9', status: 'complete' } as any) // poll 2
    .mockResolvedValueOnce({ segments: [] } as any);             // reload doc
  await useTranscripts.getState().summarize('t1', { pollMs: 1 });
  expect(vi.mocked(api).mock.calls[0][0]).toBe('/transcripts/t1/summarize');
  expect(vi.mocked(api).mock.calls[0][1]!.method).toBe('POST');
});

it('summarize rejects when the job fails', async () => {
  vi.mocked(api)
    .mockResolvedValueOnce({ job_id: 'j9' })
    .mockResolvedValueOnce({ id: 'j9', status: 'failed', error: 'cannot reach provider' } as any);
  await expect(useTranscripts.getState().summarize('t1', { pollMs: 1 }))
    .rejects.toThrow('cannot reach provider');
});
```

`CompleteScreen.test.tsx`:

```ts
it('renders stored summary and its meta', () => {
  // doc.summary = '## Key points'; doc.summary_meta = {model: 'Qwen3…', …}
  // expect summary section visible with the text and model name
});

it('summarize button triggers onSummarize and shows busy state', async () => {
  // onSummarize returns a pending promise -> button shows 'Summarizing…' and is disabled
});

it('summarize error is shown inline', async () => {
  // onSummarize rejects -> role="alert" with the message appears
});
```

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test -- CompleteScreen transcripts` — FAIL.

- [ ] **Step 3: Implement**

Store action in `transcripts.ts`:

```ts
  summarize: async (id, opts?: { pollMs?: number }) => {
    const pollMs = opts?.pollMs ?? 1500;
    const { job_id } = await api<{ job_id: string }>(`/transcripts/${id}/summarize`, { method: 'POST' });
    for (;;) {
      const rec = await api<JobRecord>(`/jobs/${job_id}`);
      if (rec.status === 'complete') break;
      if (rec.status === 'failed') throw new Error(rec.error ?? 'summarize failed');
      await new Promise(r => setTimeout(r, pollMs));
    }
    await useTranscripts.getState().load(id);
  },
```

(add `summarize: (id: string, opts?: { pollMs?: number }) => Promise<void>;` to the State interface and `import type { JobRecord } from '../api/types';`).

CompleteScreen: new prop `onSummarize?: () => Promise<void>;`, local `busy`/`error` state, button in `.actions`:

```tsx
{onSummarize && (
  <button className="icon-btn" aria-label="Summarize transcript"
          title={doc.summary ? 'Regenerate summary' : 'Summarize'}
          disabled={summarizing}
          onClick={async () => {
            setSummarizing(true); setSummaryError(null);
            try { await onSummarize(); }
            catch (e) { setSummaryError(String(e)); }
            finally { setSummarizing(false); }
          }}>
    {summarizing ? <span className="activity-spinner" aria-hidden="true" /> : <Icon name="sparkle" size={15} />}
  </button>
)}
```

Summary panel above the search bar / transcript:

```tsx
{summaryError && <p role="alert" style={{ color: 'var(--ink-error, crimson)' }}>{summaryError}</p>}
{doc.summary && (
  <div className="summary-panel">
    <div className="summary-head">
      <span className="lbl">Summary</span>
      {doc.summary_meta && (
        <span className="summary-meta">{doc.summary_meta.model} · {new Date(doc.summary_meta.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</span>
      )}
    </div>
    <div className="summary-body">{doc.summary}</div>
  </div>
)}
```

Render the markdown as plain text inside `white-space: pre-wrap` styling (no markdown renderer dependency — YAGNI; the headings/bullets read fine as text). Add `.summary-panel` CSS (elevated card, `--bg-elev`, readable ink) in `global.css`. Add a `sparkle` icon to `Icon.tsx` if absent.

Wire `onSummarize={async () => { await summarize(tid); }}` in `App.web.tsx` and `App.tsx`.

- [ ] **Step 4: Run tests**

Run: `pnpm test` and `pnpm tsc --noEmit` — PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src
git commit -m "feat(ui): summarize button + summary panel"
```

---

### Task 18: Hub bundle rebuild + full-suite validation

**Files:**
- Modify: `speechtotext/webui/*` (generated)

- [ ] **Step 1: Full backend suite**

Run: `pytest -m "not integration"` from repo root.
Expected: all PASS (was ~493 before this plan; now more).

- [ ] **Step 2: Full frontend suite + types + both builds**

From `ui/`:

```bash
pnpm test
pnpm tsc --noEmit
pnpm build
pnpm build:hub
```

Expected: all green. Then verify the hub bundle is still tauri-free:

```bash
grep -rl @tauri-apps ../speechtotext/webui | wc -l   # must print 0
```

- [ ] **Step 3: Manual smoke checklist (batched device-test session — do NOT block on this)**

Record in the final report for the user's manual pass:
1. Web: activity chip appears during a watch-folder transcription.
2. Web: play + download audio; segment click seeks.
3. Web: rename from library + transcript view; title survives reload and FTS-search by new title works.
4. Web: edit a line; txt download reflects it.
5. Web: in-transcript search next/prev.
6. Web: settings — change ASR model, watch extensions; summarize models dropdown lists Lemonade models (lemond must be running).
7. Web: summarize a transcript (Lemonade), regenerate.
8. Web: delete → trash → restore → delete → empty trash.
9. Desktop (`pnpm tauri dev`): rename, per-line edit, audio panel, summarize (needs provider config pointing somewhere reachable), trash section.

- [ ] **Step 4: Commit the rebuilt bundle**

```bash
git add speechtotext/webui
git commit -m "build(webui): rebuild hub bundle with v0.13 features"
```

(If `speechtotext/webui` is gitignored — check `.gitignore`; the DEVLOG says it ships via package-data and is gitignored in the tree — skip this commit; the bundle is packaged at release time by `publish-release.sh`.)

---

## Self-review checklist (run after writing, before execution)

- Spec coverage: 1→Task 4+15, 2→Task 5+14, 3→Task 7+16, 4→Task 1-3+10-11, 5→Task 10, 6→Task 1-2+12, 7→Task 13, 8→Task 7-9+16-17, 9→Task 6+11+16. Error handling and testing sections are embedded per task. ✓
- Out of scope confirmed: no Android tasks, no chunking, no trash auto-expiry. ✓
- Type consistency spot-checks: `patchOp(id, op, key, value)` (Tasks 10/11/12), `TrashItem` (Tasks 10/16), `apiBlob` (Tasks 10/14), `_job_dict` (Task 4), `run_summarize_job(registry, job_id, json_path, write_lock, on_written, config_path)` (Task 9), `summarize` config shape (Tasks 7/16). ✓
