# Homelab migration runbook: `stt serve` → `locallexis-hub`

This runbook migrates the homelab deployment from the loopback-only `stt serve`
process to the headless `locallexis-hub`, which is reachable over both the LAN
and the Tailscale tailnet. Because the service becomes reachable outside
loopback, it must also be auth-gated with a bearer token.

This is a **human-gated** migration: every step below is a copy-paste command
block meant to be run and checked by a human (or a supervised agent) on the
homelab host, one step at a time. Do not script the whole thing end-to-end —
verify reachability and rollback behavior before trusting the auto-updater.

Target host: `ssh lieuwe@homelab`. Repo clone: `/home/lieuwe/LocalLexis`.
Venv: `/home/lieuwe/LocalLexis/.venv`. First release to migrate to: `v0.12.0`.

---

## 1. Generate and install the admin token

`stt serve` was unauthenticated because it only ever bound to `127.0.0.1`.
`locallexis-hub` keeps the `127.0.0.1:8010` bind — Tailscale `serve` already
owns `:8010` on the tailnet IP, so a `0.0.0.0` wildcard bind would collide
(`EADDRINUSE`) — and is reached over the tailnet through the existing Tailscale
`serve` front, which is a raw **TCP passthrough** (`TCPForward` to
`localhost:8010`), so the tailnet URL is plain `http://homelab.tail788d49.ts.net:8010`
(WireGuard-encrypted on the wire, not browser-TLS). Anyone on the tailnet can
reach the API, so generate a token and gate the service with it before
switching units.

```bash
ssh lieuwe@homelab

# Generate a random 32-byte hex admin token.
openssl rand -hex 32
```

Append the generated value to the service env file, then lock down its
permissions:

```bash
# Replace <token> with the value openssl printed above.
echo 'LOCALLEXIS_API_TOKEN=<token>' >> /home/lieuwe/.config/speechtotext/service.env
chmod 600 /home/lieuwe/.config/speechtotext/service.env
```

Keep the token somewhere safe (e.g. a password manager) — you'll need it in
step 4 to log in and to authenticate health checks.

---

## 2. First manual hop to v0.12.0

The serve unit still runs `stt serve` at this point, so this hop is a plain
manual git/release update — no systemd changes yet.

```bash
cd /home/lieuwe/LocalLexis
git fetch --tags
git checkout v0.12.0

# Download and extract the web UI asset published with the release.
gh release download v0.12.0 --repo lieuwe89/LocalLexis -p 'webui-*.tar.gz' -D /tmp
rm -rf speechtotext/webui
tar -xzf /tmp/webui-*.tar.gz -C speechtotext

# Install/upgrade the package and its API extras against the CPU constraint
# file (avoids pulling CUDA wheels on this CPU-only box). This box uses uv
# (uv-created venv, no pip), so install via uv targeting the venv explicitly.
uv pip install --python /home/lieuwe/LocalLexis/.venv/bin/python -e ".[api]" \
    -c requirements-server-cpu.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu
```

---

## 3. Swap the serve unit

Install the new hub unit file, keeping the existing unit **name**
(`locallexis-serve.service`) so the current `enable`/`WantedBy` wiring and any
dependent units are untouched.

```bash
sudo cp deploy/systemd/locallexis-hub.service /etc/systemd/system/locallexis-serve.service
sudo systemctl daemon-reload
sudo systemctl restart locallexis-serve.service
```

`locallexis-watch.service` is unaffected and keeps running as-is.

---

## 4. Verify reachability

Check loopback first, then LAN, then tailnet.

```bash
# App shell should be served (200).
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/app/

# /health without a token should now be rejected (401) since it's auth-gated.
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health

# With the token from step 1, /health should succeed (200).
curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer <token>" http://127.0.0.1:8010/health
```

Expected results: `/app/` → `200`; `/health` with no token → `401`; `/health`
with `Authorization: Bearer <token>` → `200`.

From a browser on a tailnet device:

```
http://homelab.tail788d49.ts.net:8010/app
```

should show the login page. Tailscale `serve` forwards tailnet `:8010` as a raw
TCP passthrough to the loopback hub, so this is plain `http://` (the transport
is still WireGuard-encrypted), not browser-TLS — the hub speaks plain HTTP and
`serve` does not terminate TLS on this port. Log in with the token from step 1, confirm the Library
loads, and confirm a speaker relabel round-trips (rename a speaker, reload, and
see the new name persisted).

---

## 5. Arm the daily auto-updater

`scripts/hub-update.sh` is already in the repo and executable — it fetches
tags, checks out the newest `v*` tag, reinstalls, restarts, health-checks, and
rolls back automatically on any failure. Install the timer/service units that
drive it:

```bash
sudo cp deploy/systemd/hub-update.service deploy/systemd/hub-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hub-update.timer
```

Confirm it's scheduled:

```bash
systemctl list-timers hub-update.timer
```

Sanity-check that every binary the updater calls resolves under the *exact*
`PATH` the `hub-update.service` unit sets (the timer runs unattended as
`lieuwe`, so a missing tool here fails silently at 3am, not now):

```bash
PATH=/home/lieuwe/.local/bin:/home/lieuwe/LocalLexis/.venv/bin:/usr/bin:/bin \
    bash -c 'for b in gh git sudo logger curl tar uv; do command -v "$b" || echo "MISSING: $b"; done'
```

Every line should print a path; no `MISSING:` lines.

To trigger an update run immediately instead of waiting for the timer:

```bash
sudo systemctl start hub-update.service
journalctl -u hub-update.service -n 30
```

---

## 6. Prove rollback before trusting it

Before relying on the auto-updater unattended, deliberately force its
health-check to fail and confirm `hub-update.sh` rolls back cleanly.

**Run this as `lieuwe`, NOT under `sudo`.** The script self-elevates only for
its two `systemctl restart` calls (passwordless sudo). Wrapping the whole
script in `sudo` would run `git checkout` / `pip install` / the marker write as
**root**, leaving root-owned files that the next timer run (which executes as
`lieuwe`) can't touch — silently breaking the updater right after the step
meant to build confidence in it.

No throwaway tag is needed: `--force` makes the updater re-run against the
current newest tag (`v0.12.0`), and pointing the health check at a dead port
forces the `health` rollback branch. `prev` equals `v0.12.0`, so the rollback
is a no-op checkout that still exercises the full failure → restart → marker →
exit-1 path. The dead-port URL only affects the script's probe, not the real
service (which keeps serving `:8010` normally).

```bash
cd /home/lieuwe/LocalLexis
HUB_HEALTH_URL=http://127.0.0.1:9/health /home/lieuwe/LocalLexis/scripts/hub-update.sh --force
echo "exit: $?"   # expect 1 (rollback fired)
```

Confirm it exited 1, wrote the failure marker with `reason=health`, stayed on
`v0.12.0`, and the real service is still healthy:

```bash
git -C /home/lieuwe/LocalLexis describe --tags --exact-match   # expect v0.12.0
cat /home/lieuwe/.local/state/locallexis/last-update-failure   # reason=health ...
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <token>" \
    http://127.0.0.1:8010/health                                # expect 200
```

---

## Verify everything

```bash
systemctl status locallexis-serve locallexis-watch hub-update.timer
journalctl -u hub-update.service
```

All three units should show `active`, and the `hub-update.service` journal
should be clean (no unresolved rollback markers, no repeated failures).
