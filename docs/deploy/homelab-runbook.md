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
`locallexis-hub` binds `0.0.0.0:8010` and is fronted by both the LAN
(`lexis.lab.home.arpa`) and Tailscale `serve` TLS
(`homelab.tail788d49.ts.net`), so anyone who can reach the host on the LAN or
tailnet could hit the API. Before switching units, generate a token and gate
the service with it.

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
# file (avoids pulling CUDA wheels on this CPU-only box).
.venv/bin/pip install -e ".[api]" -c requirements-server-cpu.txt \
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

From a browser on a LAN device:

```
http://lexis.lab.home.arpa:8010/app
```

should show the login page. From a browser on a tailnet device:

```
https://homelab.tail788d49.ts.net:8010/app
```

should also show the login page (Tailscale `serve` already terminates TLS
here). Log in with the token from step 1, confirm the Library loads, and
confirm a speaker relabel round-trips (rename a speaker, reload, and see the
new name persisted).

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

To trigger an update run immediately instead of waiting for the timer:

```bash
sudo systemctl start hub-update.service
journalctl -u hub-update.service -n 30
```

---

## 6. Prove rollback before trusting it

Before relying on the auto-updater unattended, deliberately break a release
and confirm `hub-update.sh` rolls back cleanly.

```bash
# Create a throwaway tag/release whose health check will fail — e.g. by
# publishing a release where the service would bind the wrong port. The
# simplest safe way to force a failure without touching real config is to
# point the health check at a dead port for a single manual run:
cd /home/lieuwe/LocalLexis
git tag v0.12.1-broken-test
git push origin v0.12.1-broken-test
gh release create v0.12.1-broken-test --repo lieuwe89/LocalLexis \
    --title "throwaway rollback test" --notes "delete me" \
    --target v0.12.1-broken-test

# Force the updater to see this tag as latest and fail its health check.
sudo HUB_HEALTH_URL=http://127.0.0.1:9/health /home/lieuwe/LocalLexis/scripts/hub-update.sh --force
```

Confirm it rolled back to `v0.12.0`, wrote the failure marker, and the service
is still healthy:

```bash
git -C /home/lieuwe/LocalLexis describe --tags --exact-match   # expect v0.12.0
cat /home/lieuwe/.local/state/locallexis/last-update-failure
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <token>" \
    http://127.0.0.1:8010/health                                # expect 200
```

Clean up the throwaway tag and release:

```bash
gh release delete v0.12.1-broken-test --repo lieuwe89/LocalLexis --yes
git push origin :refs/tags/v0.12.1-broken-test
git tag -d v0.12.1-broken-test
```

---

## Verify everything

```bash
systemctl status locallexis-serve locallexis-watch hub-update.timer
journalctl -u hub-update.service
```

All three units should show `active`, and the `hub-update.service` journal
should be clean (no unresolved rollback markers, no repeated failures).
