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
