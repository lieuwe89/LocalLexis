import os
import subprocess
import tarfile
import textwrap
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


def test_package_stdout_is_only_the_archive_path_when_building(tmp_path):
    """Regression: `publish` mode does `archive="$(package)"`, so package() must
    print ONLY the archive path on stdout — the npm build's own logs must go to
    stderr, or gh gets a garbage multi-line filename."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "ui").mkdir(parents=True)
    (fake_repo / "speechtotext").mkdir(parents=True)

    # Stub `npm`: emits noise to stdout (like a real build) and creates the bundle.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    npm = bindir / "npm"
    npm.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "BUILD NOISE line 1"
        echo "vite building ..."
        mkdir -p "{fake_repo}/speechtotext/webui/assets"
        echo "<!doctype html>" > "{fake_repo}/speechtotext/webui/index.html"
    """))
    npm.chmod(0o755)

    out = tmp_path / "out"
    out.mkdir()
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    res = subprocess.run(
        [str(SCRIPT), "package", "--tag", "v9.9.9",
         "--repo-dir", str(fake_repo), "--out-dir", str(out)],  # NO --skip-build
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    # stdout must be exactly the archive path — no build noise leaked in.
    assert res.stdout.strip() == str(out / "webui-v9.9.9.tar.gz")
    assert "BUILD NOISE" not in res.stdout
    assert "BUILD NOISE" in res.stderr  # the noise went to stderr, as intended
