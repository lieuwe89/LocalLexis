# Hub Server Deploy & Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the LocalLexis homelab to the headless `locallexis-hub` server with the Phase 2 web UI, and add a git-tag-tracking auto-updater that rolls to new `v*` releases and self-heals on failure.

**Architecture:** Repo-prep lands the server's missing lazy-`sounddevice` fix on `main` and pins CPU torch wheels, so a tag checkout is safe on the audio-less box. A local release script publishes the gitignored web-UI bundle as a GitHub Release asset. A bash updater (`scripts/hub-update.sh`) checks out the newest tag, fetches its web-UI asset, reinstalls, restarts, health-checks, and rolls back on any failure. Systemd units run the hub headless (`0.0.0.0` + token) and the updater on a daily timer. Live migration on `homelab` is the final, human-gated step.

**Tech Stack:** Python 3.12 (server venv), pytest, bash, systemd, GitHub CLI (`gh`), Tailscale (`serve` fronts TLS), FastAPI hub.

**Spec:** `docs/superpowers/specs/2026-07-06-hub-server-deploy-autoupdate-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `speechtotext/devices.py` (modify) | Lazy-import `sounddevice` so headless import never runs PortAudio init |
| `tests/test_devices.py` (modify) | Repoint patches to `sounddevice.*`; add a headless-import test |
| `requirements-server-cpu.txt` (create) | Pip constraint file pinning CPU torch/torchaudio/torchcodec |
| `tests/test_requirements_server_cpu.py` (create) | Lock the pinned versions |
| `scripts/publish-release.sh` (create) | Build web-UI bundle, package `webui-<tag>.tar.gz`, upload to GH release |
| `tests/deploy/test_publish_release.py` (create) | Assert tarball layout without npm/gh |
| `scripts/hub-update.sh` (create) | Idempotent updater with `--dry-run`/`--force`, health check, rollback |
| `tests/deploy/conftest.py` (create) | `fake_server` fixture: tmp git repo + stub `gh`/`systemctl`/`sudo`/`curl`/`pip` on PATH |
| `tests/deploy/test_hub_update.py` (create) | No-op, happy path, missing-asset rollback, health-fail rollback, dry-run |
| `deploy/systemd/locallexis-hub.service` (create) | Migrated serve unit → `locallexis-hub serve`, `0.0.0.0`+token |
| `deploy/systemd/hub-update.service` (create) | Oneshot invoking `hub-update.sh` |
| `deploy/systemd/hub-update.timer` (create) | Daily trigger |
| `tests/deploy/test_systemd_units.py` (create) | Parse + assert unit contents |
| `docs/deploy/homelab-runbook.md` (create) | Copy-paste live migration + rollback-proof steps |

Tests live under `tests/deploy/` (new package). `deploy/` at repo root holds unit files as source of truth. Shell scripts read all host-specific config from env vars (with the homelab values as defaults) so tests can redirect them at a fixture.

---

## Part A — Repo prep

### Task 1: Lazy `sounddevice` import in `devices.py`

Reproduces the server-local commit `b79dc7a` on `main`. Importing `sounddevice` at module load runs PortAudio's `_initialize()`, which hard-fails on a headless host with no audio server, even though only mic/record features need it. Move the import into the two functions that use it. **Consequence:** the existing tests patch `speechtotext.devices.sd.*`, which stops existing once `sd` is a function-local name — those patches move to `sounddevice.*`.

**Files:**
- Modify: `speechtotext/devices.py:7`, `:54-58`, `:61-63`
- Test: `tests/test_devices.py` (modify existing patches + add one test)

- [ ] **Step 1: Update existing tests to patch the real module, and add a headless-import test**

In `tests/test_devices.py`, replace every occurrence of `"speechtotext.devices.sd.query_devices"` with `"sounddevice.query_devices"` and every `"speechtotext.devices.sd.default"` with `"sounddevice.default"` (7 call sites: the `with` blocks in `test_lists_only_input_devices_by_default`, `test_include_all_returns_everything`, `test_default_flag_set_on_default_device`, `test_default_when_sd_default_is_scalar`, `test_cli_table_output`, `test_cli_json_output`, `test_cli_exit_1_when_no_inputs`).

Then append this new test that proves the import is lazy (module imports even when `sounddevice` is unavailable, but `list_inputs()` surfaces the import error only when called):

```python
def test_devices_module_imports_without_sounddevice(monkeypatch):
    """Headless hosts have no audio server; importing the module (as `stt serve`
    does transitively) must not import sounddevice. Only list_inputs()/_default
    touch it, lazily."""
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "sounddevice" or name.startswith("sounddevice."):
            raise ImportError("PortAudio unavailable (headless)")
        return real_import(name, *args, **kwargs)

    # Drop any cached copy so re-import re-executes module top-level.
    sys.modules.pop("speechtotext.devices", None)
    sys.modules.pop("sounddevice", None)
    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    devices = importlib.import_module("speechtotext.devices")
    # Non-audio helpers work with no sounddevice present:
    assert devices.classify("MacBook Pro Microphone") == "mic"
    # The audio path imports lazily, so the failure appears only on call:
    with pytest.raises(ImportError):
        devices.list_inputs()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_devices.py -q`
Expected: the repointed patches now fail (`speechtotext.devices` still eagerly imports `sd`, so `sounddevice.query_devices` patching mismatches the call site through `sd`), and `test_devices_module_imports_without_sounddevice` fails (module still imports `sd` at top → ImportError at import time).

- [ ] **Step 3: Make the import lazy in `speechtotext/devices.py`**

Replace line 7 (`import sounddevice as sd`) with a comment, and add a local import to the two functions:

```python
# NOTE: `sounddevice` is imported lazily inside the functions that need it.
# Importing it at module load runs PortAudio's _initialize(), which hard-fails
# on headless hosts with no audio server (e.g. `stt serve`/`stt watch` on a
# server) even though only the mic/record features use it. Mirrors the lazy
# import already used in speechtotext/api/warmup.py.
```

In `_default_input_index()`, make the first line:

```python
def _default_input_index() -> int | None:
    import sounddevice as sd

    dev = sd.default.device
    if isinstance(dev, (tuple, list)):
        return dev[0] if dev else None
    return dev
```

In `list_inputs()`, make the first line:

```python
def list_inputs(include_all: bool = False) -> list[AudioDevice]:
    import sounddevice as sd

    raw = sd.query_devices()
    default_idx = _default_input_index()
    ...
```

(Leave the bodies otherwise unchanged. Both functions now bind `sd` to the real `sounddevice` module object, so `patch("sounddevice.query_devices")` / `patch("sounddevice.default")` in the tests intercept the calls.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_devices.py -q`
Expected: all pass, including `test_devices_module_imports_without_sounddevice`.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/devices.py tests/test_devices.py
git commit -m "fix(devices): lazy-import sounddevice so headless server use works"
```

---

### Task 2: `requirements-server-cpu.txt` constraint file

Pins the CPU torch stack so `pip install` on the CUDA-less box resolves CPU wheels (matching the server's current `torch 2.11.0+cpu`). Consumed by the updater with `--extra-index-url https://download.pytorch.org/whl/cpu`.

**Files:**
- Create: `requirements-server-cpu.txt`
- Test: `tests/test_requirements_server_cpu.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_requirements_server_cpu.py
from pathlib import Path

REQ = Path(__file__).resolve().parent.parent / "requirements-server-cpu.txt"


def test_pins_cpu_torch_stack():
    assert REQ.is_file(), "requirements-server-cpu.txt must exist at repo root"
    lines = [
        ln.strip()
        for ln in REQ.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert "torch==2.11.0+cpu" in lines
    assert "torchaudio==2.11.0+cpu" in lines
    assert "torchcodec==0.14.0" in lines
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_requirements_server_cpu.py -q`
Expected: FAIL (file does not exist).

- [ ] **Step 3: Create the constraint file**

```
# requirements-server-cpu.txt
# Constraint file for the headless CPU homelab (no CUDA). Use with:
#   pip install -e ".[api]" -c requirements-server-cpu.txt \
#       --extra-index-url https://download.pytorch.org/whl/cpu
# Encodes the "CUDA wheels on a CPU box" gotcha as versioned config.
torch==2.11.0+cpu
torchaudio==2.11.0+cpu
torchcodec==0.14.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_requirements_server_cpu.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add requirements-server-cpu.txt tests/test_requirements_server_cpu.py
git commit -m "build(server): pin CPU torch/torchaudio/torchcodec for headless hub"
```

---

## Part B — Release tooling

### Task 3: `scripts/publish-release.sh`

Builds the web-UI bundle and packages it as `webui-<tag>.tar.gz`, then uploads it to the GitHub release for `<tag>`. Split into a `package` step (testable, no network) and an `upload` step (guarded behind `--no-upload` for tests). The archive layout is the contract with the updater: `tar -xzf webui-<tag>.tar.gz -C <repo>/speechtotext` yields `<repo>/speechtotext/webui/index.html`.

**Files:**
- Create: `scripts/publish-release.sh`
- Test: `tests/deploy/test_publish_release.py`, `tests/deploy/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/deploy/test_publish_release.py
import subprocess
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "publish-release.sh"


def test_package_produces_correct_layout(tmp_path):
    # Fake a built bundle at <fake_repo>/speechtotext/webui/
    fake_repo = tmp_path / "repo"
    webui = fake_repo / "speechtotext" / "webui" / "assets"
    webui.mkdir(parents=True)
    (fake_repo / "speechtotext" / "webui" / "index.html").write_text("<!doctype html>")
    (webui / "index-abc.js").write_text("console.log(1)")

    out = tmp_path / "out"
    out.mkdir()
    # `package` mode: no npm build, no gh upload — just tar an existing bundle.
    res = subprocess.run(
        [str(SCRIPT), "package", "--tag", "v9.9.9",
         "--repo-dir", str(fake_repo), "--out-dir", str(out), "--skip-build"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    archive = out / "webui-v9.9.9.tar.gz"
    assert archive.is_file()
    with tarfile.open(archive) as tf:
        names = tf.getnames()
    # Extracting -C speechtotext must land webui/index.html
    assert "webui/index.html" in names
    assert any(n.startswith("webui/assets/") for n in names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/deploy/test_publish_release.py -q`
Expected: FAIL (script does not exist).

- [ ] **Step 3: Write `scripts/publish-release.sh`**

```bash
#!/usr/bin/env bash
# Build + publish the hub web-UI bundle as a GitHub Release asset.
#
#   scripts/publish-release.sh package --tag vX.Y.Z [--repo-dir DIR] \
#       [--out-dir DIR] [--skip-build]
#   scripts/publish-release.sh publish --tag vX.Y.Z [--repo-dir DIR] [--notes STR]
#
# `package` builds (npm run build:hub) and tars speechtotext/webui into
# webui-<tag>.tar.gz. `publish` runs package then uploads to the GH release.
# The archive stores paths as webui/... so the updater extracts with
#   tar -xzf webui-<tag>.tar.gz -C <repo>/speechtotext
set -euo pipefail

MODE="${1:?usage: publish-release.sh package|publish --tag vX.Y.Z}"
shift

TAG=""
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR=""
SKIP_BUILD=0
NOTES=""

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    --repo-dir) REPO_DIR="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --notes) NOTES="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$TAG" ] || { echo "--tag is required" >&2; exit 2; }
[ -n "$OUT_DIR" ] || OUT_DIR="$REPO_DIR"

package() {
  if [ "$SKIP_BUILD" -eq 0 ]; then
    ( cd "$REPO_DIR/ui" && npm run build:hub )
  fi
  local bundle="$REPO_DIR/speechtotext/webui"
  [ -f "$bundle/index.html" ] || { echo "no built bundle at $bundle" >&2; exit 1; }
  local archive="$OUT_DIR/webui-$TAG.tar.gz"
  tar -czf "$archive" -C "$REPO_DIR/speechtotext" webui
  echo "$archive"
}

case "$MODE" in
  package)
    package
    ;;
  publish)
    archive="$(package)"
    if gh release view "$TAG" --repo lieuwe89/LocalLexis >/dev/null 2>&1; then
      gh release upload "$TAG" "$archive" --repo lieuwe89/LocalLexis --clobber
    else
      gh release create "$TAG" "$archive" --repo lieuwe89/LocalLexis \
        --title "$TAG" --notes "${NOTES:-$TAG}"
    fi
    ;;
  *)
    echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
```

Make it executable: `chmod +x scripts/publish-release.sh`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/deploy/test_publish_release.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/publish-release.sh tests/deploy/__init__.py tests/deploy/test_publish_release.py
git commit -m "build(release): publish-release.sh packages web UI as GH release asset"
```

---

## Part C — The updater

### Task 4: `tests/deploy/conftest.py` fixture + `hub-update.sh` skeleton (config, args, no-op)

The updater reads all host config from env vars so tests point it at a throwaway repo with stub binaries. This task builds the fixture and the script's skeleton: arg parsing, `--dry-run`, and the "already on newest tag → no-op" path.

**Files:**
- Create: `tests/deploy/conftest.py`
- Create: `scripts/hub-update.sh`
- Test: `tests/deploy/test_hub_update.py`

- [ ] **Step 1: Write the fixture**

```python
# tests/deploy/conftest.py
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HUB_UPDATE = REPO / "scripts" / "hub-update.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _stub(path: Path, name: str, body: str):
    p = path / name
    p.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    p.chmod(0o755)


@pytest.fixture
def fake_server(tmp_path):
    """A throwaway git repo tagged v1.0.0/v1.1.0 with a fake bundle, plus a
    bin/ dir of stub gh/systemctl/sudo/curl/pip whose calls are logged and whose
    behavior is tuned via env vars the test sets."""
    repo = tmp_path / "clone"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "speechtotext").mkdir()
    (repo / "file.txt").write_text("v1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1.0.0")
    _git(repo, "tag", "v1.0.0")
    (repo / "file.txt").write_text("v1.1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1.1.0")
    _git(repo, "tag", "v1.1.0")
    # Start "installed" on v1.0.0 (detached), like the server after migration.
    _git(repo, "checkout", "-q", "v1.0.0")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "calls.log"

    # gh: writes a fake webui tarball when asked to download.
    _stub(bindir, "gh", f'''
        echo "gh $*" >> "{calls}"
        if [ "$1" = "release" ] && [ "$2" = "download" ]; then
          if [ "${{FAKE_ASSET_MISSING:-0}}" = "1" ]; then exit 1; fi
          # find -D dir
          out="."; while [ $# -gt 0 ]; do [ "$1" = "-D" ] && out="$2"; shift; done
          mkdir -p "$out/pkg/webui"
          echo "<!doctype html>" > "$out/pkg/webui/index.html"
          ( cd "$out/pkg" && tar -czf "$out/webui-fake.tar.gz" webui )
        fi
        exit 0
    ''')
    _stub(bindir, "systemctl", f'echo "systemctl $*" >> "{calls}"; exit 0')
    _stub(bindir, "sudo", f'echo "sudo $*" >> "{calls}"; shift; exec "$@"')
    _stub(bindir, "pip", f'echo "pip $*" >> "{calls}"; exit ${{FAKE_PIP_RC:-0}}')
    _stub(bindir, "curl", f'''
        echo "curl $*" >> "{calls}"
        # emulate -w '%{{http_code}}' health probe
        echo "${{FAKE_HEALTH_CODE:-200}}"
        exit 0
    ''')

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["HUB_REPO_DIR"] = str(repo)
    env["HUB_VENV"] = str(tmp_path / "venv")  # unused (pip stubbed)
    env["HUB_HEALTH_URL"] = "http://127.0.0.1:8010/health"
    env["HUB_TOKEN"] = "testtoken"
    env["HUB_SERVE_UNIT"] = "locallexis-hub.service"
    env["HUB_WATCH_UNIT"] = "locallexis-watch.service"
    env["HUB_HEALTH_TIMEOUT"] = "4"
    env["HUB_MARKER"] = str(tmp_path / "failure-marker")
    env["HUB_ASSET_GLOB"] = "webui-fake.tar.gz"

    def run(*args):
        return subprocess.run([str(HUB_UPDATE), *args], env=env,
                              capture_output=True, text=True)

    return {"repo": repo, "calls": calls, "env": env, "run": run,
            "marker": Path(env["HUB_MARKER"])}
```

- [ ] **Step 2: Write the failing test (no-op path)**

```python
# tests/deploy/test_hub_update.py
def _read(p):
    return p.read_text() if p.exists() else ""


def test_noop_when_already_on_newest(fake_server):
    # Put the clone on newest (v1.1.0); update must no-op.
    import subprocess
    subprocess.run(["git", "checkout", "-q", "v1.1.0"],
                   cwd=fake_server["repo"], check=True)
    res = fake_server["run"]()
    assert res.returncode == 0, res.stderr
    calls = _read(fake_server["calls"])
    assert "pip install" not in calls
    assert "systemctl restart" not in calls


def test_dry_run_mutates_nothing(fake_server):
    res = fake_server["run"]("--dry-run")
    assert res.returncode == 0, res.stderr
    calls = _read(fake_server["calls"])
    assert "pip install" not in calls
    assert "systemctl restart" not in calls
    # still on v1.0.0
    import subprocess
    cur = subprocess.run(["git", "describe", "--tags", "--exact-match"],
                         cwd=fake_server["repo"], capture_output=True, text=True)
    assert cur.stdout.strip() == "v1.0.0"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/deploy/test_hub_update.py -q`
Expected: FAIL (script missing).

- [ ] **Step 4: Write `scripts/hub-update.sh` skeleton**

```bash
#!/usr/bin/env bash
# Roll the LocalLexis hub to the newest v* tag; roll back on failure.
# All host config comes from env vars (defaults = the homelab) so the script
# is testable against a throwaway repo with stub binaries on PATH.
set -euo pipefail

REPO_DIR="${HUB_REPO_DIR:-/home/lieuwe/LocalLexis}"
VENV="${HUB_VENV:-$REPO_DIR/.venv}"
SERVE_UNIT="${HUB_SERVE_UNIT:-locallexis-serve.service}"
WATCH_UNIT="${HUB_WATCH_UNIT:-locallexis-watch.service}"
HEALTH_URL="${HUB_HEALTH_URL:-http://127.0.0.1:8010/health}"
HEALTH_TIMEOUT="${HUB_HEALTH_TIMEOUT:-30}"
MARKER="${HUB_MARKER:-/home/lieuwe/.local/state/locallexis/last-update-failure}"
ASSET_GLOB="${HUB_ASSET_GLOB:-webui-*.tar.gz}"
REPO_SLUG="${HUB_REPO_SLUG:-lieuwe89/LocalLexis}"
PIP_INDEX="${HUB_PIP_INDEX:-https://download.pytorch.org/whl/cpu}"
DRY_RUN=0
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

log() { echo "[hub-update] $*"; logger -t hub-update "$*" 2>/dev/null || true; }
run() { if [ "$DRY_RUN" -eq 1 ]; then log "DRY: $*"; else "$@"; fi; }

# Token for the health check (sourced from service.env on the real box).
TOKEN="${HUB_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f "${HUB_ENV_FILE:-/home/lieuwe/.config/speechtotext/service.env}" ]; then
  TOKEN="$(grep -E '^LOCALLEXIS_API_TOKEN=' "${HUB_ENV_FILE:-/home/lieuwe/.config/speechtotext/service.env}" | cut -d= -f2- || true)"
fi

cd "$REPO_DIR"
run git fetch --tags --quiet || true
current="$(git describe --tags --exact-match 2>/dev/null || git rev-parse HEAD)"
latest="$(git tag -l 'v*' | sort -V | tail -1)"

if [ -z "$latest" ]; then log "no v* tags found"; exit 0; fi
if [ "$current" = "$latest" ] && [ "$FORCE" -eq 0 ]; then
  log "already current ($current)"; exit 0
fi
if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY: would update $current -> $latest"; exit 0
fi

# --- update body added in Task 5 ---
log "TODO update body"
```

Make executable: `chmod +x scripts/hub-update.sh`.

- [ ] **Step 5: Run to verify no-op + dry-run pass**

Run: `.venv/bin/python -m pytest tests/deploy/test_hub_update.py -q`
Expected: PASS (both no-op and dry-run tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/hub-update.sh tests/deploy/conftest.py tests/deploy/test_hub_update.py
git commit -m "feat(deploy): hub-update.sh skeleton (config, dry-run, no-op) + fixture"
```

---

### Task 5: Updater happy path (checkout, asset, install, restart, health)

**Files:**
- Modify: `scripts/hub-update.sh` (replace the `# --- update body ---` placeholder)
- Test: `tests/deploy/test_hub_update.py` (add)

- [ ] **Step 1: Write the failing test**

```python
def test_happy_update_checks_out_installs_restarts(fake_server):
    res = fake_server["run"]()
    assert res.returncode == 0, res.stderr
    import subprocess
    cur = subprocess.run(["git", "describe", "--tags", "--exact-match"],
                         cwd=fake_server["repo"], capture_output=True, text=True)
    assert cur.stdout.strip() == "v1.1.0"
    # webui extracted from the fake asset
    assert (fake_server["repo"] / "speechtotext" / "webui" / "index.html").is_file()
    calls = _read(fake_server["calls"])
    assert "gh release download v1.1.0" in calls
    assert "pip install" in calls
    assert "systemctl restart" in calls
    assert not fake_server["marker"].exists()  # no failure marker on success
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/deploy/test_hub_update.py::test_happy_update_checks_out_installs_restarts -q`
Expected: FAIL (body is a TODO stub; ends on v1.0.0, no webui).

- [ ] **Step 3: Replace the update body**

Replace the final two lines (`# --- update body ---` and `log "TODO update body"`) with:

```bash
prev="$current"
log "updating $prev -> $latest"

rollback() {
  local reason="$1"
  log "FAILED ($reason); rolling back to $prev"
  git checkout --quiet "$prev" || true
  fetch_webui "$prev" || log "warn: could not restore webui for $prev"
  # bare `pip` resolves on PATH: the venv bin (Task 8 unit) in prod, the stub in tests.
  pip install -e ".[api]" -c requirements-server-cpu.txt \
     --extra-index-url "$PIP_INDEX" --quiet || true
  sudo systemctl restart "$SERVE_UNIT" "$WATCH_UNIT" || true
  mkdir -p "$(dirname "$MARKER")"
  echo "$(date -Is) failed=$latest reason=$reason rolled_back_to=$prev" > "$MARKER"
  logger -t hub-update "rollback to $prev after $reason" 2>/dev/null || true
  exit 1
}

fetch_webui() {
  local tag="$1" tmp
  tmp="$(mktemp -d)"
  gh release download "$tag" --repo "$REPO_SLUG" -p "$ASSET_GLOB" -D "$tmp" || return 1
  local arc
  arc="$(ls "$tmp"/$ASSET_GLOB 2>/dev/null | head -1)"
  [ -n "$arc" ] || return 1
  rm -rf "$REPO_DIR/speechtotext/webui"
  tar -xzf "$arc" -C "$REPO_DIR/speechtotext"
  [ -f "$REPO_DIR/speechtotext/webui/index.html" ] || return 1
}

health_ok() {
  local deadline=$(( SECONDS + HEALTH_TIMEOUT ))
  while [ "$SECONDS" -lt "$deadline" ]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' \
              -H "Authorization: Bearer $TOKEN" "$HEALTH_URL" || echo 000)"
    [ "$code" = "200" ] && return 0
    sleep 2
  done
  return 1
}

git checkout --quiet "$latest" || rollback "checkout"
fetch_webui "$latest" || rollback "webui-asset"
pip install -e ".[api]" -c requirements-server-cpu.txt \
   --extra-index-url "$PIP_INDEX" --quiet || rollback "pip"
sudo systemctl restart "$SERVE_UNIT" "$WATCH_UNIT" || rollback "restart"
health_ok || rollback "health"

rm -f "$MARKER"
log "updated to $latest OK"
```

Note: `pip`, `gh`, and `curl` are invoked **bare** so they resolve on PATH — the fixture's stub bin dir in tests, and the venv bin in production (the `hub-update.service` unit in Task 8 sets `Environment=PATH=/home/lieuwe/LocalLexis/.venv/bin:/usr/bin:/bin`). `HUB_VENV` is therefore unused by the script and kept only for clarity.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/deploy/test_hub_update.py -q`
Expected: all current tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/hub-update.sh tests/deploy/test_hub_update.py
git commit -m "feat(deploy): hub-update.sh happy path (checkout, asset, install, restart, health)"
```

---

### Task 6: Updater rollback (missing asset + health failure)

**Files:**
- Test: `tests/deploy/test_hub_update.py` (add)
- Modify: `scripts/hub-update.sh` only if a test exposes a gap

- [ ] **Step 1: Write the failing tests**

```python
def test_rollback_on_missing_asset(fake_server):
    fake_server["env"]["FAKE_ASSET_MISSING"] = "1"
    res = fake_server["run"]()
    assert res.returncode == 1
    import subprocess
    cur = subprocess.run(["git", "describe", "--tags", "--exact-match"],
                         cwd=fake_server["repo"], capture_output=True, text=True)
    assert cur.stdout.strip() == "v1.0.0"  # rolled back
    assert fake_server["marker"].exists()
    assert "reason=webui-asset" in fake_server["marker"].read_text()


def test_rollback_on_health_failure(fake_server):
    fake_server["env"]["FAKE_HEALTH_CODE"] = "503"
    res = fake_server["run"]()
    assert res.returncode == 1
    import subprocess
    cur = subprocess.run(["git", "describe", "--tags", "--exact-match"],
                         cwd=fake_server["repo"], capture_output=True, text=True)
    assert cur.stdout.strip() == "v1.0.0"
    assert fake_server["marker"].exists()
    assert "reason=health" in fake_server["marker"].read_text()
```

- [ ] **Step 2: Run to verify pass/fail**

Run: `.venv/bin/python -m pytest tests/deploy/test_hub_update.py -q`
Expected: both new tests PASS if Task 5's rollback is correct. If `test_rollback_on_missing_asset` fails because `FAKE_ASSET_MISSING` also breaks the rollback `fetch_webui "$prev"` (making it non-fatal), confirm the marker + git state are still correct (rollback tolerates a missing prev asset via `|| log warn`). Fix any discrepancy so both assertions hold.

- [ ] **Step 3: Adjust the script only if needed**

If `test_rollback_on_missing_asset` shows the rollback aborts because restoring the prev webui fails, ensure `fetch_webui "$prev"` in `rollback()` is guarded with `|| log ...` (already is) and does not `set -e`-exit. Confirm `rollback()` reaches the marker write. No change if tests already pass.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/deploy/test_hub_update.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/hub-update.sh tests/deploy/test_hub_update.py
git commit -m "test(deploy): hub-update.sh rolls back on missing asset + health failure"
```

---

## Part D — systemd units

### Task 7: `locallexis-hub.service` (migrated serve unit)

**Files:**
- Create: `deploy/systemd/locallexis-hub.service`
- Test: `tests/deploy/test_systemd_units.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/deploy/test_systemd_units.py
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "systemd"


def _unit(name):
    return (DEPLOY / name).read_text()


def test_hub_service_runs_headless_with_token_bind():
    u = _unit("locallexis-hub.service")
    assert "ExecStart=" in u
    assert "locallexis-hub serve" in u
    assert "LOCALLEXIS_PORT=8010" in u
    # 0.0.0.0 bind so lexis.lab.home.arpa (LAN) reaches /app; token required.
    assert "LOCALLEXIS_HOST=0.0.0.0" in u
    assert "EnvironmentFile=-/home/lieuwe/.config/speechtotext/service.env" in u
    assert "WorkingDirectory=/home/lieuwe/LocalLexis" in u
    assert "User=lieuwe" in u
    assert "WantedBy=multi-user.target" in u
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/deploy/test_systemd_units.py -q`
Expected: FAIL (file missing).

- [ ] **Step 3: Create the unit**

```ini
# deploy/systemd/locallexis-hub.service
# Install as /etc/systemd/system/locallexis-serve.service (keep the name so the
# existing enable/WantedBy wiring is unchanged), daemon-reload, restart.
[Unit]
Description=LocalLexis headless hub (locallexis-hub serve)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=lieuwe
Group=lieuwe
WorkingDirectory=/home/lieuwe/LocalLexis
Environment=HOME=/home/lieuwe
Environment=LOCALLEXIS_HOST=0.0.0.0
Environment=LOCALLEXIS_PORT=8010
EnvironmentFile=-/home/lieuwe/.config/speechtotext/service.env
ExecStart=/home/lieuwe/LocalLexis/.venv/bin/locallexis-hub serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/deploy/test_systemd_units.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/systemd/locallexis-hub.service tests/deploy/test_systemd_units.py
git commit -m "deploy(systemd): headless hub serve unit (0.0.0.0 + token)"
```

---

### Task 8: `hub-update.service` + `hub-update.timer`

**Files:**
- Create: `deploy/systemd/hub-update.service`, `deploy/systemd/hub-update.timer`
- Test: `tests/deploy/test_systemd_units.py` (add)

- [ ] **Step 1: Write the failing test**

```python
def test_update_service_and_timer():
    svc = _unit("hub-update.service")
    assert "Type=oneshot" in svc
    assert "/home/lieuwe/LocalLexis/scripts/hub-update.sh" in svc
    assert "User=lieuwe" in svc
    # venv on PATH so bare `pip` in the script resolves to the venv pip.
    assert "Environment=PATH=/home/lieuwe/LocalLexis/.venv/bin:/usr/bin:/bin" in svc

    tmr = _unit("hub-update.timer")
    assert "OnCalendar=daily" in tmr
    assert "Persistent=true" in tmr
    assert "WantedBy=timers.target" in tmr
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/deploy/test_systemd_units.py::test_update_service_and_timer -q`
Expected: FAIL (files missing).

- [ ] **Step 3: Create the units**

```ini
# deploy/systemd/hub-update.service
[Unit]
Description=LocalLexis hub auto-update (git-tag tracking)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=lieuwe
Group=lieuwe
WorkingDirectory=/home/lieuwe/LocalLexis
Environment=HOME=/home/lieuwe
Environment=PATH=/home/lieuwe/LocalLexis/.venv/bin:/usr/bin:/bin
EnvironmentFile=-/home/lieuwe/.config/speechtotext/service.env
ExecStart=/home/lieuwe/LocalLexis/scripts/hub-update.sh
```

```ini
# deploy/systemd/hub-update.timer
[Unit]
Description=Run LocalLexis hub auto-update daily

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/deploy/test_systemd_units.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/systemd/hub-update.service deploy/systemd/hub-update.timer tests/deploy/test_systemd_units.py
git commit -m "deploy(systemd): daily hub-update oneshot + timer"
```

---

## Part E — Runbook

### Task 9: `docs/deploy/homelab-runbook.md`

**Files:**
- Create: `docs/deploy/homelab-runbook.md`
- Test: `tests/deploy/test_runbook.py`

- [ ] **Step 1: Write the failing test (guards against referencing files that don't exist)**

```python
# tests/deploy/test_runbook.py
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "deploy" / "homelab-runbook.md"


def test_runbook_references_real_repo_files():
    assert RUNBOOK.is_file()
    text = RUNBOOK.read_text()
    # Every repo-relative path it tells you to copy must exist.
    for rel in [
        "deploy/systemd/locallexis-hub.service",
        "deploy/systemd/hub-update.service",
        "deploy/systemd/hub-update.timer",
        "scripts/hub-update.sh",
        "requirements-server-cpu.txt",
    ]:
        assert rel in text, f"runbook should mention {rel}"
        assert (REPO / rel).exists(), f"{rel} referenced but missing"
    # Mentions the token generation and both reachability URLs.
    assert "openssl rand -hex 32" in text
    assert "lexis.lab.home.arpa:8010/app" in text
    assert "homelab.tail788d49.ts.net:8010/app" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/deploy/test_runbook.py -q`
Expected: FAIL (runbook missing).

- [ ] **Step 3: Write the runbook**

Create `docs/deploy/homelab-runbook.md` with copy-paste commands covering, in order: (1) `openssl rand -hex 32` → append `LOCALLEXIS_API_TOKEN=` to `/home/lieuwe/.config/speechtotext/service.env` (chmod 600); (2) first manual hop to `v0.12.0` — `git fetch --tags`, `git checkout v0.12.0`, `gh release download v0.12.0 -p 'webui-*.tar.gz'` + extract, `pip install -e ".[api]" -c requirements-server-cpu.txt --extra-index-url https://download.pytorch.org/whl/cpu`; (3) install `deploy/systemd/locallexis-hub.service` as `/etc/systemd/system/locallexis-serve.service`, `daemon-reload`, `restart`; (4) verify: loopback `/app`→200, `/health` 401 without token / 200 with, `http://lexis.lab.home.arpa:8010/app` and `https://homelab.tail788d49.ts.net:8010/app` both show login, log in + relabel round-trip; (5) install `scripts/hub-update.sh` path + `hub-update.service`/`hub-update.timer`, `enable --now hub-update.timer`; (6) rollback proof — publish a throwaway broken tag, run `hub-update.sh`, confirm rollback to `v0.12.0` + marker file, then delete the throwaway tag/release. Include the exact commands for each. Must literally contain the strings `deploy/systemd/locallexis-hub.service`, `deploy/systemd/hub-update.service`, `deploy/systemd/hub-update.timer`, `scripts/hub-update.sh`, `requirements-server-cpu.txt`, `openssl rand -hex 32`, `lexis.lab.home.arpa:8010/app`, `homelab.tail788d49.ts.net:8010/app`.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/deploy/test_runbook.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/deploy/homelab-runbook.md tests/deploy/test_runbook.py
git commit -m "docs(deploy): homelab migration + rollback-proof runbook"
```

---

### Task 10: Full regression + version bump

**Files:**
- Modify: `pyproject.toml` (version)

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (existing + new `tests/deploy/*`, `tests/test_devices.py`, `tests/test_requirements_server_cpu.py`). Note the known pre-existing full-suite mic-test flake (passes isolated) if it appears.

- [ ] **Step 2: Bump the version**

Edit `pyproject.toml`: `version = "0.11.1"` → `version = "0.12.0"`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.12.0 (server deploy + auto-update)"
```

---

## Part F — Release + live migration (human-gated, NOT auto-executed)

> These steps touch the live `homelab` and the public GitHub release. The agent
> executes them supervised, after the user approves the merged build. They are
> not TDD tasks.

### Task 11: Cut the `v0.12.0` release with the web-UI asset

- [ ] Merge the branch to `main` (finishing-a-development-branch).
- [ ] Tag: `git tag -a v0.12.0 -m "Phase 3: server deploy + auto-update"` and push `--follow-tags`.
- [ ] Publish the asset: `scripts/publish-release.sh publish --tag v0.12.0` (builds `webui`, creates the GH release, uploads `webui-v0.12.0.tar.gz`).
- [ ] Verify: `gh release view v0.12.0` shows the asset; `curl -sI` the asset URL → 200.

### Task 12: Live migration on `homelab` (follow `docs/deploy/homelab-runbook.md`)

- [ ] Runbook steps 1–4: token, first manual hop to `v0.12.0`, swap the serve unit, verify all four reachability checks + a relabel round-trip.
- [ ] Runbook step 5: arm the daily timer.
- [ ] Runbook step 6: prove rollback with a throwaway broken tag, then clean it up.
- [ ] Confirm `systemctl status locallexis-serve locallexis-watch hub-update.timer` all healthy; `journalctl -u hub-update.service` clean.

---

## Self-Review

**Spec coverage:** §1 risk → Task 1 (lazy import lands on main). §2 decisions: GH asset → Tasks 3/5; 0.0.0.0+token → Task 7; daily timer → Task 8; v0.12.0 → Task 10. §3.A → Tasks 1–2. §3.B → Task 3. §3.C → Tasks 4–8. §3.D/§5 runbook → Task 9 + Tasks 11–12. §4 updater behavior (dry-run, no-op, happy, both rollbacks, health-with-token) → Tasks 4–6. §6 testing → each task's tests. §7 security (token in service.env, sudo only for systemctl) → Tasks 7/9. All covered.

**Placeholder scan:** the only `TODO` string is the deliberate skeleton stub in Task 4, replaced verbatim in Task 5. No other TBDs.

**Type/name consistency:** env var names (`HUB_REPO_DIR`, `HUB_HEALTH_URL`, `HUB_TOKEN`, `HUB_MARKER`, `HUB_ASSET_GLOB`, `HUB_SERVE_UNIT`, `HUB_WATCH_UNIT`, `HUB_HEALTH_TIMEOUT`, `HUB_VENV`, `HUB_REPO_SLUG`, `HUB_PIP_INDEX`) match between the fixture and the script. `fetch_webui`/`rollback`/`health_ok` defined once (Task 5) and referenced consistently. Unit filename `locallexis-hub.service` (repo) installs as `locallexis-serve.service` (server) — noted in Task 7 + runbook. Bare `pip`/`gh`/`curl` on PATH (fixture stubs + venv-on-PATH in Task 8) — reconciled in Task 5 Step 3 note.
