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
    assert "uv pip install" not in calls
    assert "systemctl restart" not in calls


def test_dry_run_mutates_nothing(fake_server):
    res = fake_server["run"]("--dry-run")
    assert res.returncode == 0, res.stderr
    calls = _read(fake_server["calls"])
    assert "uv pip install" not in calls
    assert "systemctl restart" not in calls
    # still on v1.0.0
    import subprocess
    cur = subprocess.run(["git", "describe", "--tags", "--exact-match"],
                         cwd=fake_server["repo"], capture_output=True, text=True)
    assert cur.stdout.strip() == "v1.0.0"


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
    assert "uv pip install" in calls
    assert "systemctl restart" in calls
    assert not fake_server["marker"].exists()  # no failure marker on success


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
