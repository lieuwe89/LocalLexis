# Protocol v2: Body-Hash Signing + Streaming Upload

Date: 2026-05-30
Status: Draft — pending user review
Unblocks: `2026-05-30-live-i2s-design.md` (live I2S capture is blocked on this spec)

## 1. Goal

Change the device-signed request protocol so the Ed25519 signature covers `sha256(body)` instead of the raw body bytes, and refactor the upload path (firmware + hub) to stream large bodies instead of buffering them in RAM.

Today both the firmware (`Ed25519::sign` over method + path + ts + nonce + full body) and the hub (`await request.body()` then verify) need the entire body resident in memory. The ESP32-S3 cannot allocate the ~115 MiB a one-hour 16 kHz mono 16-bit meeting recording requires, so meeting-length uploads are impossible. Signing a fixed-size digest instead lets Ed25519 stay one-shot over a ~90-byte message while the body is hashed and sent in a streaming pass.

This is a prerequisite for live I2S capture. It is independently verifiable using the existing demo-silence-WAV upload path — no microphone needed.

## 2. Locked decisions

| | Choice |
|---|---|
| Signature covers | `sha256(body)` (32 raw digest bytes), not raw body |
| Domain separation | Signed message prefixed with `locallexis-sig-v2` element |
| Digest encoding in message | Raw 32 bytes (not hex) |
| Endpoint scope | All four signed endpoints uniformly (`/jobs/upload`, `/sync` ×2, `PATCH /transcripts/{tid}/relabel`) |
| Hub large-body handling | Stream + hash + tee to temp file in one pass for `/jobs/upload`; small endpoints keep `await request.body()` |
| Rollout | Hard cut. v1 deleted in the same change. No version negotiation, no per-device version field |
| Components changed | Firmware (C++), hub (Python), Android (Kotlin). Desktop Tauri does not sign hub requests — unchanged |
| `SdQueue::peekOldest` (RAM-loading) | Deleted; replaced by `peekOldestPath` + `openReader` streaming reader |
| Android streaming | Deferred. Android keeps buffering the body; only its signature form changes |

## 3. Scope

### In scope

- v2 signed-message format (domain tag + body digest) in firmware, hub, Android
- Firmware `BodySource` interface + `VectorBodySource` + `SdFileBodySource`
- Firmware streaming `SignedHttpClient::uploadWav(BodySource&)`
- Firmware `signRequestB64WithBodyDigest` (precomputed-digest signing)
- `SdQueue::peekOldestPath` + `openReader`; delete `peekOldest`
- Hub `build_signed_message` v2; `verify_device_signature_with_digest` helper
- Hub `/jobs/upload` streaming verify (stream + hash + tee + verify-after + finalize)
- Hub startup sweep of orphan `.partial` files in the incoming dir
- Android `CryptoBox.buildRequestMessage` v2
- Cross-language golden-vector tests pinning the byte format
- Version bumps across hub, firmware, Android (and Tauri for alignment)
- Doc updates (auth.py docstring, firmware README, CryptoBox kdoc)

### Out of scope (deferred)

- Android streaming upload (keep current buffering)
- Any v1 compatibility / transition window
- Per-device protocol version in the device registry
- Pairing-token auth (unaffected — pairing does not use device signatures)
- Content-Encoding / compressed bodies (none used today; wire bytes == body bytes is an invariant)

## 4. Protocol delta (exact byte format)

All three implementations MUST produce identical bytes or signatures silently fail to verify.

**v1 today** (firmware, hub, Android agree):
```
signed_message = method "\n" target "\n" timestamp "\n" nonce "\n" raw_body_bytes
```
where `target = path` when there is no query, else `path "?" query`. As a join: `b"\n".join((method, target, timestamp, nonce, body))`.

**v2** — two mechanical changes:
1. Prepend a domain element `locallexis-sig-v2`.
2. Replace `raw_body_bytes` with `sha256(raw_body_bytes)` — 32 raw digest bytes, not hex.

```
signed_message = b"\n".join((
    b"locallexis-sig-v2",
    method,
    target,
    timestamp,
    nonce,
    sha256(body),          # 32 raw bytes
))
```

Expanded:
```
"locallexis-sig-v2\n" + method + "\n" + target + "\n" + timestamp + "\n" + nonce + "\n" + <32 digest bytes>
```

- Signature = `Ed25519_sign(signed_message)`, one-shot over the ~90-byte message.
- The four wire headers (`X-Device-Id`, `X-Signature-B64`, `X-Timestamp`, `X-Nonce`) are unchanged. **No new headers** — the version lives inside the signed bytes, so it cannot be stripped or downgraded by a man-in-the-middle.
- Empty body (GET `/sync`): `sha256(b"")` = the well-known `e3b0c442…855` digest. No special-case branch.
- Body = raw post-transfer-decoding request body bytes, identical to what `request.stream()` yields and what the client puts on the wire. No `Content-Encoding` is used; wire bytes == body bytes (invariant).

Keeping the same `b"\n".join(...)` structure means each implementation changes by exactly two lines: prepend one element, swap `body` for its digest.

## 5. Components & boundaries

protocol-v2 owns the signature change **and** the streaming uploader (the live-I2S spec consumes both).

### 5.1 Firmware — `src/crypto/DeviceCrypto.{h,cpp}`
- `buildSignedMessageV2(method, target, ts, nonce, const uint8_t digest[32]) -> std::vector<uint8_t>` — single owner of the v2 byte format.
- `signRequestB64WithBodyDigest(keys, method, target, ts, nonce, const uint8_t digest[32]) -> String` — signs a precomputed digest. Used by the streaming uploader (no full body in RAM).
- `signRequestB64(keys, method, target, ts, nonce, const uint8_t* body, size_t bodyLen)` — keeps its existing signature; internals now SHA-256 the body via mbedtls, then call the digest variant. Convenience path for small / in-RAM bodies.

### 5.2 Firmware — `src/net/BodySource.h` + `src/net/VectorBodySource.{h,cpp}` (new)
- `BodySource` abstract: `size_t size() const`, `bool rewind()`, `size_t readChunk(uint8_t* buf, size_t max)`.
- `VectorBodySource` wraps a `std::vector<uint8_t>`. `rewind` resets a read index.

### 5.3 Firmware — `src/net/SignedHttpClient.{h,cpp}`
- New `uploadWav(cfg, keys, filename, BodySource& source, response)`: hash pass → digest, `signRequestB64WithBodyDigest`, connect, send headers with `Content-Length = source.size()`, send pass → socket.
- Existing `uploadWav(... const std::vector<uint8_t>& ...)` becomes a thin wrapper that wraps the vector in a `VectorBodySource` and calls the new overload.

### 5.4 Firmware — `src/storage/SdQueue.{h,cpp}`
- Add `bool peekOldestPath(String& outPath)` (path only, no read) and `SdFileBodySource openReader(const String& path)` (file-backed `BodySource`; `rewind` = seek 0).
- `SdFileBodySource` reads through a small `FileLike` seam so the chunked-read logic is host-testable with a fake (real impl wraps `SD_MMC` `File`).
- Delete `peekOldest(outPath, outBytes)` — the only caller (`main.cpp` drain) switches to `peekOldestPath` + `openReader` in this change.

### 5.5 Hub — `speechtotext/api/auth.py`
- `build_signed_message(method, path, query, timestamp, nonce, body_sha256: bytes) -> bytes` → v2 form (domain tag + digest). Keeps the v1 parameter list except the trailing `body: bytes` becomes `body_sha256: bytes`; it still joins `target = path` or `path "?" query` internally.
- New `verify_device_signature_with_digest(request, body_sha256: bytes) -> str` — header checks, timestamp window, device lookup, build v2 message, `VerifyKey.verify`, nonce replay check, return `device_id`. Shared verification core.
- `verify_device_signature(request) -> str` becomes a wrapper: `digest = hashlib.sha256(await request.body()).digest(); return verify_device_signature_with_digest(request, digest)`. Small-body endpoints keep using `Depends(verify_device_signature)` unchanged at the call site.

### 5.6 Hub — `speechtotext/api/routes_ingest.py`
- `/jobs/upload` stops using `Depends(verify_upload_signature)`. It inlines: stream the body via `request.stream()`, SHA-256 incrementally, tee chunks to a `<incoming>/<unique>.partial` temp file, then `verify_device_signature_with_digest(request, digest)`. Valid → `os.replace(temp, dest)` and dispatch transcription. Invalid → delete temp, propagate 401.
- Startup hook sweeps orphan `.partial` files in the incoming dir (mirrors the firmware `.partial` boot cleanup).
- `verify_upload_signature` is removed if it has no other callers.

### 5.7 Android — `data/crypto/CryptoBox.kt` (+ `SignedRequestInterceptor.kt`)
- `buildRequestMessage` → v2 form (domain tag + `MessageDigest("SHA-256")` of body).
- `signRequest` hashes the body, signs the small message. Body is still buffered and sent by OkHttp from the same buffer (streaming Android deferred).

**Boundary check:** the byte format lives in exactly three `buildSignedMessage*` functions (one per language), pinned by a shared golden vector (Section 7). `BodySource` isolates "where bytes come from" from "how they upload."

## 6. Data flow

### 6.1 Firmware streaming upload — `SignedHttpClient::uploadWav(BodySource&)`
1. `source.rewind()`.
2. Pass 1: loop `readChunk(buf, 4096)` → `mbedtls_sha256_update` per chunk → 32-byte digest.
3. `signRequestB64WithBodyDigest(keys, "POST", target, ts, nonce, digest)` → signature.
4. Connect (HTTPS: SPKI pin verify, unchanged).
5. Send request line + headers. `Content-Length = source.size()`.
6. `source.rewind()`. Pass 2: loop `readChunk` → `client.write(chunk)`.
7. Read status line. 202 == success.

Memory: one 4 KB buffer + SHA-256 context. No full-body allocation. Files of any size stream.

### 6.2 Hub small-body verify (`/sync`, `/transcripts`)
`Depends(verify_device_signature)` unchanged at call site:
1. Header presence + timestamp window + device lookup (before body).
2. `body = await request.body()` (small).
3. `digest = sha256(body)`.
4. `verify_device_signature_with_digest(request, digest)` → build v2 message → `VerifyKey.verify` → nonce replay check → `device_id`.

### 6.3 Hub streaming upload (`/jobs/upload`)
```
headers checked: device present, timestamp in window  (nonce NOT yet consumed)
  └─ Content-Length > max_upload_bytes? → 413, no temp
temp = <incoming>/<unique>.partial
hasher = sha256()
async for chunk in request.stream():
    bytes_seen += len(chunk)
    if bytes_seen > max_upload_bytes: delete temp → 413
    hasher.update(chunk); temp.write(chunk)
digest = hasher.digest()
device_id = verify_device_signature_with_digest(request, digest)   # may raise 401
  └─ on raise: delete temp, re-raise
os.replace(temp, dest); dispatch transcription; return 202
```
Order: timestamp/window/device rejected before the stream (cheap); signature verify after the stream (needs the digest) — same as v1, which also read the full body before verifying. Replay nonce is consumed inside `verify_device_signature_with_digest`, post-stream.

### 6.4 Android
Unchanged flow: buffer body → now also `sha256` → `buildRequestMessage` v2 → sign → attach headers. Body still sent by OkHttp from the same buffer.

### 6.5 Acceptance path (no live-I2S needed)
The existing demo-silence-WAV upload in `main.cpp` exercises v2 end-to-end: vector → `VectorBodySource` → streaming `uploadWav` → hub stream-verify. This proves protocol-v2 standalone.

## 7. Error handling

### 7.1 Hub streaming upload (`/jobs/upload`)
- Content-Length > max → 413 before stream, no temp.
- Stream exceeds Content-Length / max mid-read → delete temp, 413.
- Client disconnect mid-stream → `request.stream()` raises → delete temp, no response (connection dead). No orphan.
- Write error (disk full) → delete temp, 500.
- Signature verify fail (bad signature, or tampered body → digest mismatch) → delete temp, 401 `signature verification failed`.
- Stale timestamp / unknown device → 401 before stream, no temp.
- Replay nonce → checked inside `verify_device_signature_with_digest`, post-stream → delete temp, 401 `replay detected`.
- Orphan `.partial` sweep on startup (crash-left temp files).

### 7.2 Firmware streaming upload
- `rewind()` fail (SD seek error) → abort attempt, leave queue file, back off, retry. Serial log.
- `readChunk` short/error in pass 1 or 2 → abort, leave file, retry.
- `size()` ≠ bytes actually read in pass 2 → would desync `Content-Length`. Guard: assert `bytesSent == size()` after the loop; on mismatch close connection and retry.
- Connect / SPKI fail → existing back-off, unchanged.
- Hub 4xx → delete file (will never succeed). (Shared with the live-I2S 4xx fix.)
- Hub 5xx / network → leave file, back off 2 s, retry.

### 7.3 Hub small-body verify
Unchanged from v1 behavior; only the message-build internals differ. Empty body → empty-string digest, verifies normally.

### 7.4 Android
- Body read fail / one-shot body → existing `IOException` paths, unchanged.
- v2 signature rejected by a v1 hub → 401 surfaced to the caller. Under the hard cut an old Android build against the v2 hub is guaranteed 401; the acceptance test catches this.

### 7.5 Cross-implementation mismatch (the real risk)
A digest-format or domain-tag disagreement between the three languages produces a silent 401. Mitigation: the shared golden-vector test (Section 8.1) asserts identical signature bytes in firmware, hub, and Android. CI-gated.

## 8. Testing

### 8.1 Golden vector (linchpin)
Fixed input: known 32-byte Ed25519 seed, `method="POST"`, `target="/jobs/upload?filename=t.wav"`, `ts="1700000000"`, `nonce="abc123"`, `body=b"hello"`. Compute the expected `signed_message` bytes and expected `X-Signature-B64`. Hardcode both in:
- Firmware host test `test/host/test_sign_v2.cpp`
- Hub `tests/.../test_auth_v2.py`
- Android `CryptoBoxTest.kt`

All three assert the same signature string. A mismatch turns a build red.

### 8.2 Firmware host tests (`<cassert>`, manual `main`)
- `test_sign_v2.cpp` — golden vector; `buildSignedMessageV2` byte-exact; empty-body digest.
- `test_body_source.cpp` — `VectorBodySource` round-trip, rewind replay, chunked == whole; SHA-256 chunked == one-shot; `SdFileBodySource` over a `FileLike` fake (round-trip + rewind).

### 8.3 Hub pytest
- v2 signature verifies (golden vector reused).
- v1 signature now returns 401 (hard-cut proof).
- Tamper body → digest mismatch → 401.
- Stale timestamp → 401 pre-stream. Replay nonce → 401 post-stream.
- `/jobs/upload` stream: correct file written + 202; oversize → 413 + no orphan; mid-stream disconnect → no orphan; verify-fail → temp deleted.
- Small endpoints (`/sync`, `/transcripts`) still verify under v2.

### 8.4 Android (JUnit)
- `buildRequestMessage` v2 byte-exact + golden vector.
- Existing `SignedRequestInterceptorTest` and `SyncClientTest` updated to v2 expectations.

### 8.5 Hardware integration (batched manual session)
- Flash v2 firmware → demo-silence upload → hub 202 (stream-verify path).
- Old v1 firmware against v2 hub → 401 (confirms the cut).

Gates: `pytest -m "not integration"` + firmware host build + Android unit tests green before flashing.

## 9. Migration / rollout (hard cut)

Single user, no transition window. v1 deleted in the same change.

**Version bumps** (per repo convention, before any push):
- `pyproject.toml` (hub)
- Firmware: add a `LOCALLEXIS_PROTO_VERSION 2` define for traceability (firmware has no version file)
- `android/app/build.gradle` `versionName`
- `ui/package.json` + `ui/src-tauri/Cargo.toml` for alignment (Tauri is unaffected by the protocol but versions stay aligned per AGENTS.md)

**Deploy order** (near-simultaneous, single session):
1. Hub first — becomes the v2-only verifier (all old clients now 401).
2. Android — install the v2 build.
3. Firmware — reflash recorder(s).
4. Verify: demo upload 202; Android sync 202.

The mismatch window is a few minutes, acceptable for own devices.

**No per-device version field** in the registry — all devices are v2, no dispatch logic.

**Rollback:** git revert all components together, same coordinated reflash.

**Docs:** update the `auth.py` module docstring v1 → v2, the firmware README "Current Limits", and the `CryptoBox` kdoc.

## 10. Open questions for the plan phase

1. **Host-test build mechanism.** `platformio.ini` has no `[env:native]` entry; the existing `test/host/` files appear to build by some other path. Confirm or add a native build so `test_sign_v2.cpp` and `test_body_source.cpp` run in CI.
2. **FileLike seam shape.** Decide the minimal interface (`read(buf, max)`, `seek(0)`, `size()`) that both the real `SD_MMC` `File` and the host fake implement, kept small enough not to leak Arduino types into host tests.
3. **Hub incoming-dir scratch location.** Confirm the `_incoming_dir(request)` path is writable for `.partial` temp files and that the startup sweep hook has access to it.
4. **mbedtls SHA-256 streaming API** on the Arduino-ESP32 core — confirm `mbedtls_sha256_starts_ret` / `_update_ret` / `_finish_ret` (the non-deprecated variants for the pinned core version).
