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
