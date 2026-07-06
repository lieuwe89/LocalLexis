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
