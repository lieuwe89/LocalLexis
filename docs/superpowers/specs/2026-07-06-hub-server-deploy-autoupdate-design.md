# Phase 3 — Hub Server Deployment & Auto-Update — Design

**Status:** Approved (2026-07-06)
**Feature:** Migrate the LocalLexis homelab from `stt serve` (loopback) to the
headless `locallexis-hub` server with the Phase 2 web UI, and add a git-tag-tracking
auto-update mechanism that rolls the server to new `v*` releases and self-heals on
failure.

Predecessors: Phase 1 (desktop hub client mode, `v0.10.0`), Phase 2 (hub web UI,
`v0.11.1`). This is the third and final phase of the multi-device arc.

---

## 1. Current state (discovered on `homelab`, 2026-07-06)

Facts gathered by probing the live server, not assumed:

- **Host:** `homelab`, Ubuntu 26.04 LTS, x86_64, passwordless sudo. Reached via
  `ssh lieuwe@homelab`.
- **Clone:** `/home/lieuwe/LocalLexis`, origin `https://github.com/lieuwe89/LocalLexis.git`
  (**public** — release assets are downloadable without auth). `gh` 2.46.0 present and
  authenticated as `lieuwe89`; `curl`/`jq` present.
- **venv:** `/home/lieuwe/LocalLexis/.venv`, Python 3.12.13, `torch 2.11.0+cpu`
  (CUDA unavailable — CPU-only box).
- **Services (both active):**
  - `locallexis-serve.service` → `.venv/bin/stt serve --host 127.0.0.1 --port 8010`
  - `locallexis-watch.service` → `.venv/bin/stt watch /home/lieuwe/transcribe-inbox`
  - Both: `User=lieuwe`, `WorkingDirectory=/home/lieuwe/LocalLexis`,
    `EnvironmentFile=-/home/lieuwe/.config/speechtotext/service.env`
    (currently only `HF_TOKEN`, `HF_HUB_ENABLE_HF_TRANSFER` — **no** `LOCALLEXIS_API_TOKEN`,
    so the API is presently **unauthenticated**, safe only because it is loopback-bound).
- **Networking:** `tailscaled` runs `tailscale serve` fronting `:8010` with real
  tailnet TLS: `https://homelab.tail788d49.ts.net:8010` → `tcp://localhost:8010`.
  Server LAN IP is `192.168.2.51` (`enp195s0`); Tailscale IP `100.88.123.48`.
- **DNS:** `lexis.lab.home.arpa` → `192.168.2.51` (the LAN interface).
- **Git divergence (the load-bearing risk):** the clone is on a private branch
  `headless-lazy-sounddevice` at `b79dc7a` (`v0.9.9-1`), one commit past `v0.9.9`.
  That commit lazy-imports `sounddevice` in `speechtotext/devices.py` so headless
  hosts don't crash on PortAudio init. **This fix never reached `main`** —
  `origin/main:speechtotext/devices.py` still has the eager top-level
  `import sounddevice as sd`. All tags through `v0.11.1` therefore lack it. The
  server can see every tag up to `v0.11.1` after `git fetch --tags`.

### Why the divergence is the crux
Auto-update works by checking out tags. The moment the updater runs
`git checkout v0.x`, the clone leaves `headless-lazy-sounddevice` and the lazy-import
fix disappears (the tag has the eager import) → `locallexis-hub` crashes importing
`devices` on a box with no audio server. **Therefore the fix MUST land on `main` and
ship in the first tag the server tracks, before the server is switched to tag-tracking.**
This makes "repo prep" a hard prerequisite, not a nicety.

---

## 2. Decisions locked (during brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Web UI delivery to server | **GitHub Release asset** (`webui-<tag>.tar.gz`) | Server has no Node and installs editable-from-git; the bundle is gitignored. Release step (local) builds + uploads; updater downloads via `gh`. Keeps build output out of git. |
| Network bind | **`0.0.0.0` + token** | `lexis.lab.home.arpa` (LAN) should reach `/app`. Headless defaults to `0.0.0.0` and requires a token for non-loopback bind — exactly the posture we want. Tailscale `serve` still proxies loopback, so its TLS path keeps working. |
| Transport | Plain HTTP on LAN, TLS via Tailscale | LAN (`http://lexis.lab.home.arpa:8010/app`) is trusted home network; token-gated. Tailnet (`https://homelab.tail788d49.ts.net:8010/app`) gets real TLS from `tailscale serve`. No self-signed certs, no reverse proxy. |
| Update cadence | **Daily** systemd timer, automatic | Matches spec; releases are infrequent. Manual trigger also available (`systemctl start hub-update.service`). |
| Release version | **`v0.12.0`** (MINOR) | Repo-prep adds a new deploy surface; first tag the server tracks. |
| Install model | Editable-from-git (`pip install -e`) | Preserves git-tag checkout + rollback model. |

---

## 3. Architecture

Four separable units, built and tested in-repo before any live change:

### A. Repo prep (lands on `main`, ships in `v0.12.0`)
1. **`speechtotext/devices.py`** — reproduce `b79dc7a`: remove the top-level
   `import sounddevice as sd`; add `import sounddevice as sd` inside
   `_default_input_index()` and `list_inputs()` (the only two users). Add the
   explanatory comment mirroring `api/warmup.py`'s lazy import.
2. **`requirements-server-cpu.txt`** — pip constraint file:
   ```
   torch==2.11.0+cpu
   torchaudio==2.11.0+cpu
   torchcodec==0.14.0
   ```
   Used with `--extra-index-url https://download.pytorch.org/whl/cpu` so pip resolves
   CPU wheels on a box with no CUDA (the "CUDA wheels on a CPU box" gotcha, encoded).

### B. Release tooling (`scripts/publish-release.sh`, runs locally)
Extends the existing bump→tag→push convention with web-asset publishing. Given a
version already bumped, tagged, and pushed (per the existing global convention):
1. `cd ui && npm run build:hub` → populates `speechtotext/webui/`.
2. `tar -czf webui-<tag>.tar.gz -C speechtotext webui` (archive contains a top-level
   `webui/` dir).
3. `gh release create <tag> webui-<tag>.tar.gz --title <tag> --notes <...>` (or
   `gh release upload <tag> ...` if the release already exists).

The archive layout is the contract between B and C: extracting it at the repo root
(`tar -xzf ... -C <repo>/speechtotext`) yields `speechtotext/webui/index.html` etc.

### C. Server artifacts (in repo; deployed to `homelab`)
1. **`scripts/hub-update.sh`** — the updater (detailed in §4).
2. **`deploy/systemd/locallexis-hub.service`** — the migrated serve unit (replaces the
   `stt serve` ExecStart).
3. **`deploy/systemd/hub-update.service`** + **`deploy/systemd/hub-update.timer`** —
   daily oneshot invoking the updater.

Unit files live in the repo as the source of truth; the runbook copies them to
`/etc/systemd/system/`.

### D. Migration runbook (`docs/`, executed live on `homelab`, supervised)
Ordered, reversible steps (§5). Executed by the agent with the human watching, after
A/B/C are built, tested, and released.

---

## 4. `scripts/hub-update.sh` — behavior

**Contract:** idempotent; safe to run when already current (no-op); leaves the server
either fully on the new release or fully rolled back to the prior one — never a
half-updated state.

**Config (env or constants):** repo dir (`/home/lieuwe/LocalLexis`), venv
(`.venv`), the two unit names, health URL (`http://127.0.0.1:8010/health`), token
(read from `service.env`), health timeout (30s), marker file
(`/home/lieuwe/.local/state/locallexis/last-update-failure`).

**Flags:**
- `--dry-run` — log every action, mutate nothing (no checkout/pip/restart). For safe
  first inspection and CI-ish validation.
- `--force` — reinstall + restart even if already on the newest tag (for re-running a
  failed asset download).

**Happy path:**
1. `git fetch --tags --quiet`.
2. `current = git describe --tags --exact-match` (or the recorded state); `latest =
   git tag -l 'v*' | sort -V | tail -1`. If `current == latest` and not `--force`: log
   "already current", exit 0.
3. Record rollback point: `prev = current` (the tag or commit currently checked out).
4. `git checkout --quiet <latest>` (detached HEAD on the tag).
5. **Web UI asset:** `gh release download <latest> -p 'webui-*.tar.gz' -D <tmp>`; if an
   asset exists, `rm -rf speechtotext/webui && tar -xzf <tmp>/webui-*.tar.gz -C speechtotext`.
   Missing asset is a **failure** (triggers rollback) — a release without its UI is
   broken for the web hub.
6. `pip install -e ".[api]" -c requirements-server-cpu.txt --extra-index-url
   https://download.pytorch.org/whl/cpu` (quiet).
7. `systemctl restart locallexis-hub.service locallexis-watch.service` (via sudo).
8. **Health check:** poll `GET /health` with `Authorization: Bearer <token>` every 2s
   up to 30s; require HTTP 200. Success → clear any stale marker, `logger`/journal a
   success line, exit 0.

**Rollback (on any failure after step 3):**
1. `git checkout --quiet <prev>`.
2. Re-download + extract the `<prev>` webui asset (if `<prev>` is a `v*` tag with one;
   if `<prev>` is the pre-migration branch, skip — but by then main-tracking is
   established).
3. Reinstall (step 6 against `<prev>`), restart units.
4. Write the marker file (timestamp, failed tag, reason) and a `journalctl`-visible
   error line. Exit non-zero (so the systemd unit records failure).

**Health-check auth note:** because the API is now token-gated, the health poll must
send the bearer token. `/health` returns 401 without it (verified in Phase 2). The
script sources the token from `service.env`.

---

## 5. Migration runbook (live, supervised)

Preconditions: `v0.12.0` tagged, pushed, and its `webui-v0.12.0.tar.gz` release asset
published (A + B done, C files in the repo at that tag).

1. **Generate token:** `openssl rand -hex 32`. Append `LOCALLEXIS_API_TOKEN=<token>` to
   `/home/lieuwe/.config/speechtotext/service.env` (mode 600).
2. **First update, manually:** on the server, `git fetch --tags`, then run
   `scripts/hub-update.sh --dry-run` from the *new* tag's copy to inspect, then a real
   run — but since the unit still points at `stt serve`, this first hop is done by hand:
   checkout `v0.12.0`, download the webui asset, `pip install -e ".[api]" -c
   requirements-server-cpu.txt --extra-index-url .../whl/cpu`.
3. **Swap the serve unit:** copy `deploy/systemd/locallexis-hub.service` to
   `/etc/systemd/system/locallexis-serve.service` (keep the unit *name* so nothing else
   changes), `daemon-reload`, `restart`. New ExecStart:
   `.venv/bin/locallexis-hub serve`; env adds nothing host-specific (headless defaults:
   `0.0.0.0:8010`, token from `service.env`, `serve_webui=True`).
4. **Verify reachability:**
   - `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/app/` → 200.
   - `curl` `/health` without token → 401; with token → 200.
   - From a LAN device: `http://lexis.lab.home.arpa:8010/app` → login page.
   - From a tailnet device: `https://homelab.tail788d49.ts.net:8010/app` → login page.
   - Log in with the token; confirm Library loads and a speaker relabel round-trips.
5. **Arm auto-update:** install `hub-update.service` + `hub-update.timer`,
   `daemon-reload`, `enable --now hub-update.timer`.
6. **Prove rollback before trusting it:** publish a deliberately-broken throwaway tag
   (e.g. one whose `/health` fails), run `hub-update.sh`, confirm it rolls back to
   `v0.12.0`, writes the marker, and the service is healthy. Then delete the throwaway
   tag/release. (Alternative if a broken tag is undesirable: temporarily point the
   health URL at a wrong port to force the failure path, verify rollback, restore.)

The `stt watch` unit is unchanged except it now runs the newer code after the pip
install (same entry point).

---

## 6. Testing strategy

- **Repo prep:** `devices.py` — a test that imports `speechtotext.devices` with
  `sounddevice` import made to raise (simulating headless PortAudio failure) and asserts
  the module still imports and non-audio functions work; verify `list_inputs()` still
  imports lazily. Full Python + UI suites stay green.
- **`hub-update.sh`:** shell-level tests (bats-style or a Python harness invoking the
  script against a throwaway local git repo with fake tags and a stub `gh`/`systemctl`/
  `curl`). Cover: no-op when current; happy update; missing-asset → rollback;
  health-fail → rollback; `--dry-run` mutates nothing. These run without the live box.
- **Release tooling:** `publish-release.sh` verified by building the tarball and
  asserting its internal layout (`webui/index.html` present) without actually calling
  `gh` (dry-run / `--no-upload`).
- **Live:** the runbook's step 4 + step 6 are the integration test — done supervised on
  `homelab`.

---

## 7. Security notes

- The token gates the API and the web UI login. On the LAN path the token is sent over
  **plain HTTP** — acceptable on a trusted home LAN (explicit decision); the tailnet
  path is TLS. If the LAN is ever untrusted, revisit with the reverse-proxy option.
- `service.env` holds the token; mode 600, owned by `lieuwe`. Rotating the token is a
  matter of editing `service.env` + `restart` — Phase 2's `setUnauthorizedHandler`
  makes browsers re-login cleanly (verified).
- The updater runs as `lieuwe` with sudo only for `systemctl` (restart/daemon-reload).
  It never runs untrusted code beyond what the pinned release + constraint file install.

---

## 8. Out of scope

- Multi-server / fleet rollout (this is one homelab).
- Publishing to PyPI (server tracks git tags + release assets, not a package index).
- HTTPS on the LAN name / internal CA (deferred; Tailscale covers the TLS need).
- Summarization, RAG search, share options (future web UI screens — the platform shim,
  either-auth dep, and `/app` routing are the extension points).

---

## 9. Deliverables checklist

- [ ] `speechtotext/devices.py` lazy `sounddevice` import + test
- [ ] `requirements-server-cpu.txt`
- [ ] `scripts/publish-release.sh` + layout test
- [ ] `scripts/hub-update.sh` + shell tests (`--dry-run`, happy, missing-asset, health-fail rollback, no-op)
- [ ] `deploy/systemd/locallexis-hub.service`
- [ ] `deploy/systemd/hub-update.service` + `hub-update.timer`
- [ ] `docs/` migration runbook (this spec §5, expanded to copy-paste commands)
- [ ] Release `v0.12.0` with `webui-v0.12.0.tar.gz` asset
- [ ] Live migration on `homelab` + rollback proof (supervised)
