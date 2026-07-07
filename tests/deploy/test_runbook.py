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
