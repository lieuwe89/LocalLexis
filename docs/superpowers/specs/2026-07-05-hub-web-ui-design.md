# Hub Web UI (Phase 2) — Design

**Date:** 2026-07-05
**Status:** Approved (brainstorm with Lieuwe)
**Parent spec:** `docs/superpowers/specs/2026-07-04-hub-client-web-ui-design.md` (§Phase 2)

## Problem

A headless LocalLexis hub now runs on a server and desktop client mode
(Phase 1, v0.10.0) is shipped. The hub has **no browsable interface**: you
cannot read/search/relabel transcripts or mint pairing codes without the
Tauri desktop app on the hub machine. Phase 2 adds a browser UI served by the
hub itself, reusing the existing React screens.

Scope (locked in the parent spec): **Library** (search, read, relabel) +
**Settings** (pairing, device management) only. Capture stays on native
clients. Auth is an admin-token login page. Hub reachable over Tailscale;
same-origin, CORS off.

## Decisions (locked in this brainstorm)

- **Platform shim mechanism:** Vite alias by build mode. `ui/src/platform/`
  provides a tauri impl (default) and a web impl (`--mode hub`); screens
  import `@/platform`, never `@tauri-apps/*`. The web bundle must contain
  zero `@tauri-apps` code.
- **Web shell:** a separate `App.web.tsx`, aliased the same way, mounting
  only Library + Settings + a login gate. Native `App.tsx` is untouched;
  capture screens/stores never enter the web bundle.
- **Server auth:** `PATCH /transcripts/{id}` becomes "admin bearer **OR**
  device signature". Read routes are already bearer-gated and need no
  change — the browser's admin token works on them as-is.
- **Packaging:** `vite build --mode hub` outputs directly into
  `speechtotext/webui/` (no copy step); shipped as package-data. FastAPI
  serves it at `/app` in headless mode only, with an SPA fallback.

## Architecture

### 1. Platform shim (`ui/src/platform/`)

A thin abstraction over every host capability the shared screens touch, so
one import site (`@/platform`) resolves to native or web at build time.

| File | Role |
|---|---|
| `index.ts` | The `Platform` surface (types + re-export of the selected impl). |
| `tauri.ts` | Default impl — wraps `@tauri-apps/*`. Used by the native build. |
| `web.ts` | Web impl — browser equivalents / no-ops. Used by `--mode hub`. |

**Surface** (derived from the ~11 current `@tauri-apps` call sites):

| Capability | tauri.ts | web.ts |
|---|---|---|
| API base URL + auth header | `invoke('sidecar_url')` → `{url, token}` | `window.location.origin` + localStorage admin token |
| `appVersion()` | `@tauri-apps/api/app` `getVersion` | `import.meta.env` / build constant |
| `openPath(p)` | `plugin-opener` | no-op / hidden in web (local-only) |
| `openFileDialog()` | `plugin-dialog` `open` | not used by web screens |
| `pathJoin` / `audioDir` | `@tauri-apps/api/path` | not used by web screens |
| updater (`check`/`ask`/`relaunch`) | `plugin-updater` + `plugin-process` | no-op |
| webview drag-drop | `getCurrentWebview` | not used by web screens |

Capabilities the web shell never invokes still need a `web.ts` stub so the
module resolves and tree-shakes cleanly (they compile to unused no-ops and
drop out of the bundle).

**Vite wiring:** `resolve.alias` maps `@/platform` →
`src/platform/web.ts` when `mode === 'hub'`, else `src/platform/tauri.ts`.
Verify the `--mode hub` bundle contains no `@tauri-apps` string.

### 2. API client (`ui/src/api/client.ts`)

The one module that currently hard-imports `invoke`. Refactor so base URL +
auth come from `@/platform`:

- **Native:** unchanged behavior — discover sidecar via `sidecar_url`, poll
  `/health`, cache `{url, token}`, bearer header.
- **Web:** base = `window.location.origin`; token read from localStorage
  (`locallexis_admin_token`). A `401` clears the stored token and signals the
  shell to return to the login screen.

### 3. Web shell (`ui/src/App.web.tsx`)

Aliased so `main.tsx`'s `import App from './App'` resolves to `App.web.tsx`
under `--mode hub` (mirror the platform alias, or a dedicated
`resolve.alias` entry for `./App`).

- **Login gate:** if no stored admin token (or token invalid), render the
  login page. Paste token → `GET /health` with `Authorization: Bearer` →
  200 stores token + enters app; 401 shows an error. (`/health` is
  bearer-gated whenever `LOCALLEXIS_API_TOKEN` is set, so it is a sufficient
  verifier.)
- **Shell:** reuse existing chrome (`Window`, `Sidebar`, `MainHeader`) with a
  2-item route table (`library`, `settings`). Reuse the existing
  `useState<Route>` routing pattern — no router library.
- **Screens:** import the existing `LibraryScreen` and `SettingsScreen`.
  Those two (and their transitive imports) must build without any
  capture-only tauri dependency once they import `@/platform`.

### 4. Server auth — either-auth dependency (`speechtotext/api/`)

Add a dependency that accepts **admin bearer OR device signature**:

```
async def verify_admin_or_device(request) -> str:
    # If a valid LOCALLEXIS_API_TOKEN bearer is present → return "admin".
    # Else fall back to verify_device_signature (returns the device_id).
    # If neither → 401.
```

- Replace `Depends(verify_device_signature)` on `PATCH /transcripts/{id}`
  (`patch_transcript_op`) with `Depends(verify_admin_or_device)`.
- History attribution: bearer path records the actor as `admin`; signed path
  keeps the signing `device_id`.
- `BearerAuthMiddleware` / `_is_lan_signed_route` unchanged: PATCH already
  bypasses the middleware bearer check, so the route dep is the sole gate and
  is the correct place for the either-logic.
- Reads (`GET /transcripts`, `/transcripts/{id}`, `/config`, `/pair/tokens`,
  `/devices/paired`) stay bearer-gated — no change.

**Edge case:** when `LOCALLEXIS_API_TOKEN` is unset (standalone `stt serve`),
the middleware skips bearer entirely; `verify_admin_or_device` must still
require a valid signature in that mode (don't treat "no token configured" as
"admin"). The bearer branch only succeeds on a present, matching token.

### 5. Pairing page (Settings, web)

- Mint via `POST /pair/tokens` (admin-bearer, already exists).
- Render QR client-side + a copyable base64 pairing string. Reuse the
  existing pairing-payload builder (`ui/src/lib/pairing.ts`).
- `hub_url` prefilled from `window.location.origin` — the browser already
  knows the reachable Tailscale address, avoiding LAN-IP guesswork.
- Paired-device list + unpair via existing `GET /devices/paired`,
  `DELETE /devices/paired/{id}`.

This page is web-only; the native Settings pairing UI (if any) is unaffected.

### 6. Serving & packaging (`speechtotext/api/app.py`)

- `vite build --mode hub` → `outDir: '../speechtotext/webui'`. Ships as
  package-data (`pyproject.toml`) so `pip install` carries the assets; no
  Node on the server.
- FastAPI mounts `speechtotext/webui/` at `/app`, gated by an explicit
  `create_app(serve_webui: bool = False)` param. `create_app()` is **shared**
  by `server.run()` (the Tauri loopback sidecar — no browser ever reaches it)
  and `server.headless()` (the LAN/server entry). Only `headless()` passes
  `serve_webui=True`, so `/app` is present exactly on the LAN-reachable entry
  and never on the loopback sidecar. Prefer this param over an env sniff —
  `create_app` is the one place both entries converge. SPA fallback:
  unmatched `/app/*` paths serve `index.html`.
- Same-origin: the web app calls the API on its own origin, so CORS stays
  off. The static mount sits behind `BearerAuthMiddleware`; `/app` assets
  themselves must be reachable pre-login (the login page has to load), so the
  static route is added to the middleware pass-through (like OPTIONS) while
  the API routes it calls stay gated.

## Data flow

1. Browser hits `http://<tailnet>:8010/app` → static `index.html` (no token
   yet) → login page.
2. User pastes admin token → `GET /health` (bearer) → 200 → token to
   localStorage → shell renders.
3. Library: `GET /transcripts?q=…` (bearer) → list/search; `GET
   /transcripts/{id}` (bearer) → read.
4. Relabel a hub transcript → `PATCH /transcripts/{id}` (bearer) →
   `verify_admin_or_device` passes on the admin branch → CRDT op applied →
   change propagates to other devices via existing sync.
5. Settings → pair: `POST /pair/tokens` (bearer) → QR + string built with
   `window.location.origin` as `hub_url`.

## Error handling

- **401 on any API call:** clear stored token, return to login.
- **Static assets missing** (dev / not built): `/app` mount is skipped
  gracefully or returns a clear 404 — never crashes app startup.
- **Non-headless process:** `/app` is not mounted; browser gets 404. The
  Tauri app is the interface there.

## Testing

- **vitest:** platform-shim resolution (web impl exports the surface, no
  tauri import), login flow (store/clear token, 401 → login), pairing-payload
  build uses `window.location.origin`.
- **pytest:** `verify_admin_or_device` — bearer path returns `admin`, valid
  signature path returns device_id, neither → 401, and "token unset →
  signature still required". `/app` static serving + SPA fallback present in
  headless mode and absent otherwise.
- **Build:** `vite build --mode hub` produces `speechtotext/webui/` with no
  `@tauri-apps` in the bundle; `tsc` clean for both targets.
- **Browser verification:** batched manual session (per workflow
  convention) — load `/app`, login, search/read/relabel, pair a device.

## Out of scope (Phase 3 and later)

Server migration to `locallexis-hub` headless, auto-update timer, CPU-torch
constraints (Phase 3). Summarization, RAG, sharing screens (future). The
platform shim, either-auth dep, and `/app` routing are the extension points.
