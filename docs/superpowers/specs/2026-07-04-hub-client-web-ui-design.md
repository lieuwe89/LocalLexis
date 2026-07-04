# Hub Client Mode, Web UI & Server Auto-Update — Design

**Date:** 2026-07-04
**Status:** Approved (brainstorm with Lieuwe)

## Problem

A headless LocalLexis hub now runs on a Linux server (`stt serve`, loopback
`:8010`, systemd, CPU torch). Laptop and phone should send audio there for
processing, and transcriptions must sync to all devices and be searchable
everywhere.

What exists: headless mode, signed audio ingest (`POST /jobs/upload`),
pull-based sync (`/sync/snapshot`, `/sync/since/{cursor}`), CRDT relabel
(`PATCH /transcripts/{id}`), QR pairing, Android + ESP32 clients.

What's missing:

1. The desktop app cannot join a hub — it always transcribes locally, and
   local transcripts never reach the hub (sync is pull-from-hub only).
2. Pairing requires the desktop UI on the hub machine; a headless hub has no
   way to mint/present pairing payloads.
3. No browsable interface on the hub itself.
4. No mechanism to keep the server installation up to date.

## Decisions (locked during brainstorm)

- **Client mode semantics:** when joined, the laptop is a pure client —
  all transcription happens on the hub. Offline capture goes to a disk
  queue and uploads later. No local-processing fallback.
- **Pre-join local library:** kept as-is; library view shows local + hub
  transcripts merged, badged by origin. No backfill upload.
- **Web UI scope:** library (search, read, relabel) + settings (pairing,
  device management) only. Capture stays on native clients (phone, laptop
  app, ESP32). More screens (summarization, RAG, sharing) come later.
- **Web auth:** admin-token login page → localStorage → bearer header.
- **Build order:** desktop client mode first, then web UI, then
  deployment/auto-update.
- **Updates:** pull-based systemd timer on the server following version
  tags. No push CI/CD, no GitHub-held tailnet secrets.
- **Network model:** hub reachable over Tailscale only. Tailnet provides
  transport encryption; hub TLS stays off initially (pairing payloads use
  `http://<tailnet-name>:8010`, no SPKI pin). Hub TLS + pinning remains
  available if ever exposed beyond the tailnet.

## Phase 1 — Desktop client mode

### New sidecar package `speechtotext/client/`

Mirrors the `api/` server package on the client side.

| Module | Responsibility |
|---|---|
| `identity.py` | Generate/store device Ed25519 keypair (`<app-data>/hub/device_key.json`, mode 0600). Curve25519 unwrap of the sealed workspace key on pairing. |
| `hub_client.py` | HTTP client for the hub. Signs requests with the existing scheme (`METHOD\nPATH\nbody`, headers `X-Device-Id` + `X-Signature-B64`; whole-body digest signing for uploads). Optional SPKI-pinned TLS for self-signed hubs. |
| `join.py` | Pairing: accept pasted pairing string = base64(JSON `PairingPayloadV1`: `hub_url`, `workspace_id`, `token`, optional `tls_spki_b64`). Claim via `POST /pair`, persist `<app-data>/hub/client_state.json` (url, workspace_id, device_id, pin, sync cursor). Leave = delete key + state, keep synced transcripts. |
| `upload_queue.py` | Disk outbox `<app-data>/hub/outbox/`. Capture writes audio + meta sidecar there; uploader loop streams to `POST /jobs/upload`, deletes on 202, retries with backoff, survives restarts. |
| `sync_puller.py` | Background task in the sidecar: poll `GET /sync/since/{cursor}` (~30 s), write transcript JSON to `<app-data>/hub/synced/`, upsert into `library.db`, advance cursor. First join: paged `GET /sync/snapshot`. |

### Library index change

`library.db` gains an `origin` column (`local` | `hub`). Synced docs are
indexed like local ones, so FTS search covers both. The index stays
rebuildable from disk (`hub/synced/` is a library dir).

### Routing when joined

- Drop / record / watch-folder → outbox (upload), not the local pipeline.
- The local pipeline is untouched for un-joined installs.
- Relabels on hub-origin transcripts → CRDT `PATCH` to the hub; the edit
  returns via sync. Local-origin relabels unchanged.
- Upload progress: poll existing `GET /jobs/{id}`.

### UI (Tauri app)

- Settings: "Join a hub" card — paste pairing string → preview workspace +
  hub URL → confirm. Joined state shows hub URL, sync status dot,
  last-sync time, Leave button.
- Library rows: small origin badge.
- IdleScreen: "processing on hub" state for queued/in-flight uploads,
  "N waiting for hub" when offline.

### Server-side addition: `locallexis-hub pair` CLI

Subcommand on the existing console script. Mints a token via the loopback
API (admin bearer), prints the base64 pairing string and an ASCII QR
(phone scans, laptop pastes). The web pairing page (Phase 2) supersedes it
for daily use; the CLI remains for bootstrap and scripting.

### Error handling

- Hub unreachable → outbox grows; UI shows count. No data loss.
- Signature rejected (device unpaired remotely) → sidecar surfaces an
  "unpaired" state; UI offers re-pair.
- Sync conflicts: hub is authoritative for hub-origin docs; the laptop
  never edits those outside CRDT ops.

### Testing

- Unit (pytest, no network): signing, identity storage, queue behavior,
  cursor persistence.
- Integration: in-process FastAPI hub (existing pattern in `tests/api/`),
  pair a fake device, upload audio, verify transcript arrives via sync,
  verify relabel round-trip.

## Phase 2 — Hub web UI

### Build

- Second Vite target of the existing `ui/`: `vite build --mode hub` →
  `dist-hub/`.
- Platform shim `ui/src/platform/` with `tauri.ts` and `web.ts`
  implementations (API base URL, dialogs, BLE, updater, opener). Screens
  import the shim, never `@tauri-apps/*` directly (~6 call sites refactor).
- Web build routes only Library + Settings; capture screens excluded.

### Serving

- FastAPI mounts the built assets at `/app` (headless mode only), with an
  SPA fallback route. Same-origin API calls; CORS stays off.
- Assets ship inside the Python package (`speechtotext/webui/` via
  package-data) so `pip install` carries them — no Node on the server.

### Auth

- Login page at `/app`: paste admin token → verified with an authed
  `GET /health` → stored in localStorage → bearer header on all calls.
  Any 401 returns to login.

### Pairing page (Settings)

- Mint via `POST /pair/tokens`, render QR client-side + copyable pairing
  string. `hub_url` pre-filled from `window.location.origin` — the browser
  already knows the reachable address (e.g. the Tailscale name), avoiding
  the LAN-IP guesswork of `/hub/info`.
- Paired-device list + unpair (existing `GET /devices/paired`,
  `DELETE /devices/paired/{id}`).

### Server changes

- Auth dependency on `PATCH /transcripts/{id}` (and device-signed read
  routes needed by the UI) becomes "admin bearer **or** device signature".
- Static mount + SPA fallback.

### Testing

- vitest: platform shim, login flow, pairing payload build.
- pytest: either-auth dependency, static serving in headless mode.
- Device/browser verification: batched manual session (per workflow
  convention).

## Phase 3 — Server deployment & auto-update

### Repo prep

- Land the lazy `sounddevice` import fix in `speechtotext/devices.py` on
  main (equivalent of the server's `headless-lazy-sounddevice` branch) so
  future server pulls don't conflict.
- Add `requirements-server-cpu.txt` constraint file: CPU
  torch/torchaudio 2.11.0, torchcodec 0.14.0 — encodes the
  CUDA-wheels-on-CPU-box gotcha as versioned config.

### Migration runbook (execution human-gated)

- Replace the `stt serve` systemd unit with `locallexis-hub`:
  `LOCALLEXIS_HEADLESS=1`, `LOCALLEXIS_PORT=8010`,
  `LOCALLEXIS_API_TOKEN=<generated>`. Reachable via Tailscale.
- `stt watch ~/transcribe-inbox` unit stays.

### Auto-update (`scripts/hub-update.sh` + systemd timer, daily)

1. `git fetch --tags` in the server clone.
2. Newest version tag ≠ installed version → checkout tag.
3. `pip install -e ".[api]" -c requirements-server-cpu.txt`.
4. Restart both units; poll `/health` (30 s budget).
5. On failure: checkout previous tag, reinstall, restart, write a marker
   file and journal entry.

Releases ride the existing convention: version bump + annotated tag on
every push, so the server tracks tagged releases, never mid-work main.

## Future (out of scope, keep room for)

Summarization, RAG search (chunker/embedder schema already in
`library.db`), and share options will land as additional web UI screens
and API routes. The platform shim, either-auth dependency, and `/app`
routing are the extension points.
