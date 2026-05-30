# Live I2S Capture for the LocalLexis ESP32 Recorder

Date: 2026-05-30
Status: Draft — **blocked on `protocol-v2-body-hash-signing` spec landing first**
Hardware: Waveshare ESP32-S3-ePaper-1.54 V2 (ESP32-S3-PICO-1 N8R8) with onboard ES8311 audio codec.

## 0. Dependency

This spec depends on a separate `protocol-v2-body-hash-signing` spec (to be written next). That spec changes the signed-request protocol so the signature covers `sha256(body)` instead of body bytes directly. Without that change, the firmware cannot upload payloads larger than what fits in a single PSRAM `std::vector<uint8_t>` (~32 MiB), because both `Ed25519::sign` (firmware) and `await request.body()` (hub) need the full message buffer in RAM. Meeting-length recordings (60+ min ≈ 115 MiB) are unreachable without the protocol change.

Once protocol-v2 lands:
- Firmware `signRequestB64` signs a small fixed message containing the body's SHA-256 digest, not the body itself.
- `SignedHttpClient::uploadWav` accepts a `BodySource` and streams the body (hash pass, send pass) without buffering.
- `SdQueue` drain reads files chunk-by-chunk through the same `BodySource` interface.

This spec assumes that uploader is available, and integrates against it for the SD-path 256 MiB cap. The `BodySource` interface, the streaming refactor of `SignedHttpClient::uploadWav`, the chunked SHA-256 hashing, and the `SdQueue` `peekOldestPath`/`openReader` additions all live in the protocol-v2 spec, not here.

## 1. Goal

Replace the demo silent-WAV generator in the recorder firmware with a real audio capture path. After this spec lands, tapping the BOOT button starts an actual microphone recording, tapping again stops it, and the resulting WAV is uploaded to the hub (queued through SD when present, sent directly when not). A small ePaper plus LED UI tells the user whether the device is in `STANDBY`, `RECORDING`, or `FULL` state.

The 256 MiB SD-path cap, the no-SD 4 MiB cap, and the `FULL — tap to start a new recording` handling all depend on the streaming uploader delivered by the protocol-v2 spec; implementation here is blocked until that uploader exists.

## 2. Locked decisions

| | Choice |
|---|---|
| Mic source | Onboard ES8311 codec |
| Recording trigger | BOOT button (GPIO0), tap to start, tap to stop |
| UI surface | LED (GPIO3) for instant feedback + ePaper for state text |
| Sample format | 16 kHz mono 16-bit PCM |
| Capture-to-storage path | Streaming write into a `WavSink` interface; SD-backed when card present, PSRAM-backed when not |
| Per-file size cap (SD present) | 256 MiB (matches hub default `DEFAULT_MAX_UPLOAD_BYTES`) |
| Per-file size cap (no SD) | 4 MiB (safe contiguous PSRAM allocation) |
| Cap-hit behavior | Stop recording, render `FULL — tap to start a new recording`, next tap begins a fresh clip |
| Upload path | Streaming `SignedHttpClient::uploadWav(BodySource&)` — **delivered by the protocol-v2 spec**, consumed here |
| No-SD multi-clip storage | Single-slot `std::optional<PendingClip>`; second clip while first is uploading is dropped with a serial warning |

## 3. Scope

### In scope

- Live I2S audio capture via the onboard ES8311 codec
- Streaming SD writer with header-patch-on-close (`WavFileSink`)
- PSRAM RAM-buffer writer (`WavMemorySink`) for the no-SD path
- Bumping `SdQueue` cap from 4 MiB to 256 MiB (depends on protocol-v2 drain refactor existing)
- BOOT button toggle with debounce
- LED + ePaper recording-state UI
- `FULL` cap-hit handling on both storage paths
- New host-side unit tests for `WavWriter` and `RecordingSession`
- Wiring `RecordingSession` outputs into the protocol-v2 `BodySource`-based uploader
- One-time fix: drop a queued file on hub 4xx response instead of retrying forever

### Delivered by protocol-v2 (not in this spec)

- `BodySource` interface and its file-backed and vector-backed implementations
- Streaming `SignedHttpClient::uploadWav(BodySource&)` (two-pass body, chunked SHA-256, single fixed-size signed message)
- `SdQueue::peekOldestPath` + `openReader(path)` streaming reader (replaces the RAM-loaded `peekOldest`)
- Chunked SHA-256 host tests
- Hub-side body-hash verification, Android signer change, desktop signer change

### Out of scope (deferred)

- Pre-roll buffer (record the 2 seconds before the user taps)
- Voice activity detection / silence trimming
- Per-recording metadata (timestamps, notes)
- BLE-driven start/stop
- Battery-low handling beyond current PMIC defaults
- Long-duration soak testing
- USB-controlled audio injection rig for automated hardware-in-loop tests
- Per-clip retry budget on hub 5xx responses (today: retry forever with 2 s back-off)

## 4. Architecture: components and boundaries

The work splits into six new modules and four modified ones. Each module has one clear job, communicates through a narrow interface, and can be understood and tested without reading the others.

### 4.1 New modules under `firmware/esp32-recorder/src/`

- **`audio/Es8311Codec.{h,cpp}`** — Thin I2C driver for the onboard codec. Methods: `powerOn()`, `powerOff()`, `configureMicMono16k()`, `setMicGain(int)`. Hides the Audio_PWR rail (GPIO42, active-LOW) and the I2C register sequence. No knowledge of I2S, files, or recording state.
- **`audio/I2SCapture.{h,cpp}`** — Wraps the ESP-IDF I2S driver: DMA buffer configuration, BCLK/LRCK/SDIN pin mapping, FreeRTOS reader task that pulls frames from the driver. Yields `int16_t` mono PCM frames to a callback. The codec is a separate collaborator passed in at construction; `I2SCapture` itself knows nothing about the codec's register map.
- **`audio/WavSink.h`** — Pure abstract interface: `open()`, `write(bytes, len)`, `bytesWritten()`, `capacityBytes()`, `close()`. `open()` returns a success boolean rather than throwing, so the construction-vs-resource-acquisition split stays cheap to test. Two concrete implementations:
  - **`audio/WavFileSink.{h,cpp}`** — Opens `/queue/R<NNNN>.wav.partial` via `SD_MMC`, writes a 44-byte placeholder WAV header, streams samples. `close()` seeks to the header, patches the `RIFF` chunk size and the `data` chunk size, `fsync`s, closes the file, and renames `.partial` to `.wav`.
  - **`audio/WavMemorySink.{h,cpp}`** — Pre-allocates one `std::vector<uint8_t>` in PSRAM with `reserve(4 MiB + 64)`, writes the placeholder header, then samples in place. `close()` patches the same two header offsets and returns the vector by move.
- **`audio/RecordingSession.{h,cpp}`** — High-level state machine: `STANDBY → RECORDING → STOPPING → STANDBY`. On `toggle()`, reads `SdQueue::ready()` once and locks the sink choice for the session. On cap reached or a second `toggle()`, finalizes the sink and hands the result to the upload path. Emits state-change events for the UI.
- **`input/BootButton.{h,cpp}`** — GPIO0 interrupt plus debounce. Detects a tap (press, release within 800 ms). Fires `onTap` callback. Long-press is explicitly ignored and reserved for a future use.
- **`ui/RecorderUi.{h,cpp}`** — Owns the LED (GPIO3, active-LOW) blink state machine and the ePaper renderer (`GxEPD2_154_D67`). Subscribes to `RecordingSession` state events. Renders three screens: `STANDBY`, `RECORDING`, `FULL — tap to start a new recording`. Uses ePaper partial refresh on transitions.

### 4.2 Modified existing modules

- **`net/SignedHttpClient.{h,cpp}`** — No changes in this spec. The streaming `uploadWav(BodySource&)` overload arrives via protocol-v2; this spec consumes it.
- **`storage/SdQueue.{h,cpp}`** — Bump `kMaxFileBytes` from 4 MiB to 256 MiB. Add `openWriter(outPath)` returning an `SdFileWriter` for `WavFileSink` to use. (`peekOldestPath` + `openReader` are added by protocol-v2.) `removeFile` and boot-time `.partial` cleanup unchanged.
- **`main.cpp`** — Replace `enqueueDemoOnce` and `uploadDemoWavOnce` with: instantiate `Es8311Codec`, `I2SCapture`, `RecordingSession`, `BootButton`, `RecorderUi`; wire `BootButton.onTap → RecordingSession.toggle`; wire `RecordingSession.onClipReady → upload-or-enqueue` (the upload-or-enqueue function uses the protocol-v2 streaming uploader). The silent-demo path is preserved behind `#ifdef LOCALLEXIS_DEMO_SILENT_WAV` for mic-less smoke tests.
- **`include/LocalLexisConfig.h`** — Add `LOCALLEXIS_AUDIO_*` defines: sample rate (16000), bit depth (16), Audio_PWR (42), I2S pin assignments (BCLK / LRCK / SDIN, and MCLK if needed — exact GPIOs resolved during the plan phase), no-SD cap (4 MiB), SD cap (256 MiB).
- **`platformio.ini`** — Move `GxEPD2` and `Adafruit GFX Library` from the `hello-screen` env's `lib_deps` into the main `waveshare-esp32-s3-epaper` env. Drop the now-redundant override in `hello-screen`.

### 4.3 Why this shape

The capture front-end (`I2SCapture`, `Es8311Codec`) knows nothing about files, queues, or UI. The sinks know nothing about how samples were produced. `RecordingSession` is the only place where the SD-vs-PSRAM choice lives. `RecorderUi` listens but never mutates state. Each module is independently testable.

The `BodySource` interface on the uploader side mirrors the `WavSink` interface on the capture side: abstract interface, file-backed and vector-backed implementations. The two layers are symmetric — capture writes through an abstract sink, drain reads through an abstract source — so a future backend swap on either side is local.

## 5. Data flow

### 5.1 Boot → STANDBY

1. `setup()` runs the existing chain: `IdentityStore`, `SdQueue::begin`, Wi-Fi, SNTP, BLE provisioning if needed. Unchanged.
2. New: instantiate `Es8311Codec`, `I2SCapture` (passing the codec), `RecordingSession` (passing a `WavSink` factory), `BootButton`, `RecorderUi`.
3. `Es8311Codec::powerOff()` — codec rail held high (Audio_PWR=1) until first record, to keep idle current low.
4. `RecorderUi::renderStandby()` — one ePaper full refresh, "STANDBY" centered. LED off.
5. `BootButton::arm()` — interrupt attached, debounce active.
6. Main loop continues running the existing Wi-Fi-and-drain pump, now using the streaming `BodySource` path.

### 5.2 Tap → RECORDING

1. `BootButton` interrupt fires on press, debounce timer waits, release within 800 ms fires `onTap`.
2. `RecordingSession::toggle()`:
   - Reads `SdQueue::ready()` and locks the choice for this session.
   - **SD path:** `WavFileSink::open()` calls `SdQueue::openWriter()`, which allocates the next `R<NNNN>.wav.partial` path and returns an open file handle. Writes the 44-byte placeholder header. Sets `capacityBytes_ = 256 MiB`.
   - **No-SD path:** `WavMemorySink::open()` reserves 4 MiB + 64 bytes in PSRAM, writes the placeholder header. Sets `capacityBytes_ = 4 MiB`.
   - If `open()` fails, transition back to `STANDBY` with an error event (see Section 6).
3. `Es8311Codec::powerOn()` — Audio_PWR=LOW, 10 ms settle, then I2C sequence: enable ADC, mono channel, 16 kHz, default mic gain.
4. `I2SCapture::start()` — install I2S driver, set pin assignments, allocate DMA ring (8 buffers × 1024 frames), spawn reader task pinned to core 1 at `tskIDLE_PRIORITY + 5`.
5. `RecorderUi` receives `→ RECORDING`. LED begins 500 ms / 500 ms blink. ePaper partial-refresh renders "RECORDING".
6. State machine is `RECORDING`. `BootButton` re-armed for stop.

### 5.3 Steady-state recording

Reader task on core 1:
1. Blocks on `i2s_channel_read()` for one DMA buffer (~32 ms at 16 kHz with a 512-frame buffer).
2. Forwards raw PCM bytes to `RecordingSession::onPcm(bytes, len)`.
3. `RecordingSession::onPcm`:
   - Calls `sink_->write(bytes, len)`.
   - Reads `sink_->bytesWritten()` and compares to `capacityBytes_`. If reached, posts `STOP_FULL` and stops accepting further frames.

The DMA queue absorbs short SD write hiccups: the driver continues filling DMA buffers for several buffer-times before any overrun.

### 5.4 Tap → STOPPING → STANDBY (normal stop)

1. `BootButton::onTap` fires again. `RecordingSession::toggle()` posts `STOP_USER`.
2. State → `STOPPING`. `I2SCapture::stop()` drains the DMA queue with one final read, uninstalls the driver, joins the reader task.
3. `Es8311Codec::powerOff()` returns to idle.
4. `sink_->close()`:
   - **`WavFileSink::close()`** — seek to offset 4, patch `RIFF` chunk size (`4 + 8 + 16 + 8 + dataBytes`). Seek to offset 40, patch `data` chunk size (`dataBytes`). `fsync`. Close file. Rename `R<NNNN>.wav.partial` → `R<NNNN>.wav`. Return the final path.
   - **`WavMemorySink::close()`** — patch the same two header offsets in-place. Return the vector by move.
5. `RecordingSession` hands the clip handle to the upload path:
   - **SD path:** nothing to do. The clip is a normal `R<NNNN>.wav` in `/queue/`; the existing drain pump picks it up on the next loop tick.
   - **No-SD path:** stores the clip in a single-slot `std::optional<PendingClip>` for the main loop to upload once Wi-Fi and provisioning are available. A second clip arriving before the first uploads is dropped with a serial warning.
6. `RecorderUi` receives `→ STANDBY`. LED off. ePaper partial-refresh renders "STANDBY".
7. State → `STANDBY`. `BootButton` re-armed.

### 5.5 Cap reached → STOPPING(FULL) → STANDBY

Same as 5.4 with two differences:
- Trigger is `STOP_FULL` from `RecordingSession::onPcm`, not the button.
- `RecorderUi` renders "FULL — tap to start a new recording" instead of "STANDBY". The screen stays until the next tap, which is treated as a fresh start (transitions directly to "RECORDING").

### 5.6 Upload (background, runs in main loop)

The streaming uploader and `BodySource` adapters are delivered by protocol-v2. This spec is responsible only for wiring `RecordingSession`'s outputs into them:

1. Each loop tick: check provisioned + Wi-Fi connected + (`SdQueue` has files OR pending in-memory clip).
2. **SD path:** call protocol-v2's `SdQueue::peekOldestPath(outPath)` and `SdQueue::openReader(path)` to obtain a `SdFileBodySource`.
3. **No-SD path:** wrap the pending `std::vector<uint8_t>` in protocol-v2's `VectorBodySource`.
4. Call protocol-v2's streaming `SignedHttpClient::uploadWav(provisioning, keys, filename, source, response)`. Internals (hash pass, send pass, signature shape) are protocol-v2's concern.
5. On 202: `SdQueue::removeFile(path)` for SD path, or clear pending slot for no-SD path. Continue draining.
6. On 4xx (new behavior added by this spec): log status, delete the file (or clear the pending slot), continue to next. Retrying won't help.
7. On 5xx or network error: leave the file/slot in place, back off (existing 2 s delay), retry on the next drain tick.

### 5.7 Cross-path invariant

The SD-vs-PSRAM choice lives only in the `WavSink` selection and the matching `BodySource` adapter. Capture, codec, button, UI, signing, and HTTPS all run identical code on both paths.

## 6. Error handling

### 6.1 Capture-side failures

- **Codec I2C NACK on `Es8311Codec::powerOn()`** — abort start. `RecordingSession` rolls back: close and discard the sink (file sink deletes its `.partial`, memory sink frees its vector), return to `STANDBY`. UI shows "MIC ERROR" for 2 s, then re-renders "STANDBY". Serial logs the I2C error.
- **I2S driver install failure** — same rollback. Codec is powered off, sink is closed and discarded.
- **Sink open failure (SD full, PSRAM alloc failed)** — abort before the codec is touched. UI shows "SD FULL" or "OUT OF MEMORY" for 2 s, return to `STANDBY`. Serial logs the underlying error.
- **DMA overrun (reader task fell behind)** — dropped frames are unrecoverable, but recording continues. The reader task increments a counter; if more than 10 overruns happen in a single session, `RecordingSession` posts `STOP_ERROR`, finalizes whatever was captured, and the UI shows "AUDIO ERROR — clip saved" briefly before returning to `STANDBY`. The partial clip is still uploaded.
- **SD write failure mid-recording** — `WavFileSink::write()` returns false. `RecordingSession` posts `STOP_ERROR`. The sink's `close()` attempts the header patch and rename anyway; if it succeeds the file goes to the upload queue, otherwise the `.partial` is deleted. UI shows "SD ERROR" for 2 s, return to `STANDBY`.

### 6.2 State-machine failures

- **Tap arrives in `STOPPING`** — ignored. The button is only armed in `STANDBY` and `RECORDING`.
- **Tap arrives during the post-cap `FULL` screen** — treated as a fresh start, not an acknowledgement. UI goes directly to "RECORDING".
- **Provisioning lost mid-session** — `RecordingSession` does not depend on provisioning state; capture and write are decoupled from upload. The recorded clip waits in `/queue/` (or the no-SD pending slot) for provisioning to recover. No special UI state.
- **Wi-Fi lost mid-session** — same as above. Capture continues, drain pump stops, upload retries once Wi-Fi returns. This is the SD queue's reason for existing.

### 6.3 Boot-time recovery

- **`.wav.partial` files left from a crash** — already handled by `SdQueue::begin()`. No change.
- **Half-written `.wav` from an SD write failure that completed the rename** — file passes the existing `.wav` filter, gets drained, the hub either accepts the truncation or rejects with a 4xx. Section 6.4 ensures a 4xx deletes the file rather than retrying forever.

### 6.4 Upload-side failures

- **`BodySource::rewind()` failure on pass 2** — fatal for this upload attempt. Leave file/slot in place, back off, retry next tick. Log to serial.
- **TLS handshake or HTTPS error** — existing back-off, unchanged.
- **Hub 5xx** — leave file/slot, back off, retry. Existing.
- **Hub 4xx (new)** — log, delete file or clear slot, continue. The file cannot succeed; retrying jams the queue.
- **Hub 202** — delete file or clear slot. Existing.

### 6.5 Assertions

- `WavFileSink::write()` returning more bytes than `capacityBytes_` allows is a programmer error — assert in debug builds, refuse the write and treat as cap-hit in release.
- `RecordingSession::toggle()` called from anywhere but the button handler or the `STOP_FULL` event is a programmer error — assert and return.
- Any state transition not in the documented table is logged as a serial error and ignored.

### 6.6 Out-of-scope failures

- Brownout during write — PMIC handles power; on reset the `.partial` is cleaned at boot. No preservation across brownouts.
- SD removed mid-recording — treated as an SD write failure (above). No card-presence detection beyond the next write failing.
- Per-clip 5xx retry budget — deferred.
- User-visible error history — serial log only.

## 7. Testing

### 7.1 Host-side unit tests (`pio test -e native`)

**`test/host/test_wav_writer.cpp` (new)**
- `header_zero_samples_matches_canonical_bytes` — 44-byte header for an empty 16 kHz mono 16-bit WAV matches hand-computed bytes.
- `header_patch_updates_riff_and_data_sizes` — write header, append N samples, patch, verify `RIFF` size = `36 + 2*N` and `data` size = `2*N`.
- `header_patch_round_trip_one_sample` and `header_patch_round_trip_100k_samples` — boundary and realistic size.
- `wav_memory_sink_respects_capacity` — `write()` returns false (and `bytesWritten()` clamps) when capacity is reached mid-chunk.

Runs against an in-memory sink fake; no SD dependency.

**`test/host/test_recording_session.cpp` (new)**
Mocks `WavSink`, `Es8311Codec`, `I2SCapture`, and `BootButton` behind narrow abstract interfaces:
- `STANDBY → toggle → RECORDING → toggle → STANDBY` — basic cycle; sink open/close called once each; codec power on/off symmetric.
- `STANDBY → toggle → RECORDING → cap hit → STANDBY` — sink reports capacity exhausted; `STOP_FULL` emitted; UI sees FULL event.
- `STANDBY → toggle → RECORDING → STOPPING → tap-during-stopping-is-ignored → STANDBY` — second tap inside the stopping window.
- `STANDBY → toggle (sink open fails) → STANDBY` — codec never powered on; UI sees error event.
- `STANDBY → toggle (codec init fails) → STANDBY` — sink closed and discarded.
- `sd_present_at_start_picks_file_sink` and `sd_absent_picks_memory_sink` — sink choice is stable for the session.

`BodySource`-related host tests live in the protocol-v2 spec, not here.

**`test/host/test_provisioning_protocol.cpp` (existing)** and **`test/host/test_hub_url.cpp` (existing)** — untouched.

The host suite is the gate: if it is red, no firmware flash happens.

### 7.2 Build verification

`pio run -e waveshare-esp32-s3-epaper` must succeed cleanly. Any new warning is a finding. The streaming `SignedHttpClient` refactor especially is build-verified to confirm the wrapper preserves the public API used by `main.cpp`.

### 7.3 Hardware integration (batched manual session)

One connected-board session at the end of implementation, serial monitor open:

1. **Cold boot, SD present.** ePaper "STANDBY", LED off, serial shows codec idle and SD mounted.
2. **Tap to record, speak 5 s, tap to stop.** "RECORDING" → "STANDBY" on ePaper, LED blinks during recording, one `R<NNNN>.wav` appears in `/queue/`, drain pump uploads, hub returns 202, file deleted.
3. **Tap to record, reboot mid-recording.** Power-cycle while LED blinks. After reboot: "STANDBY", no `.partial` left in `/queue/`, no malformed `.wav`.
4. **Tap to record, force Wi-Fi off, tap to stop, re-enable Wi-Fi.** Clip lands in `/queue/`, drain blocks until Wi-Fi returns, then uploads cleanly.
5. **Tap to record, leave running 3 minutes.** Resulting WAV is the right length, uploads inside the 256 MiB ceiling cleanly.
6. **Eject SD, reboot, tap to record, speak 5 s, tap to stop.** Memory sink path, "STANDBY"/"RECORDING"/"STANDBY" flow, direct upload, no queue. Then tap again, record briefly, verify the second clip is accepted once the first finishes uploading.
7. **Eject SD, reboot, hold recording until the ~4 MiB cap (~2 min).** "FULL — tap to start a new recording" appears, LED stops, the captured chunk uploads, next tap starts a fresh recording cleanly.
8. **Audio sanity.** Spot-check one uploaded clip on the desktop — valid 16 kHz mono 16-bit PCM, no clipping, recognizable speech.

If any item fails, the spec phase didn't capture something and we revisit before declaring done.

### 7.4 Explicitly not tested

- Long-duration soak (8+ hours of repeated record cycles) — rely on host tests and existing SD queue resilience.
- Automated failure injection on the hub side — exercised by hand if needed.
- Mic frequency response or codec EQ tuning — quality target is "recognizable speech."

## 8. Open questions for the plan phase

These do not block the spec but must be resolved before code is written:

1. **Protocol-v2 spec must land first.** Without it, this spec cannot deliver the 256 MiB cap behavior or stream multi-MB uploads. See Section 0.
2. **Exact I2S pin assignments** (BCLK, LRCK, SDIN, and whether the codec needs an external MCLK from the ESP32). Authoritative source: the Waveshare reference firmware repository (`github:waveshareteam/ESP32-S3-ePaper-1.54`, `port_bsp` / `port_audio` components). The plan phase will check that source and pin these down.
3. **ES8311 I2C address and exact register sequence for mono 16 kHz ADC.** Same authoritative source. Default address is `0x18`, but cross-check.
4. **DMA buffer sizing.** The 8 × 1024 frames choice is a starting point. The plan phase may revise after measuring real codec interrupt cadence.
5. **Host-test build mechanism.** The existing `test/host/` files use plain `<cassert>` and a manual `int main` — confirm there is a working build path (`platformio.ini` has no `[env:native]` entry yet) and add one if needed, before the new host tests can be exercised in CI.

## 9. References

- `firmware/esp32-recorder/README.md` — current firmware behavior and known gaps.
- `firmware/esp32-recorder/src/main.cpp` — boot sequence the new modules will integrate with.
- `firmware/esp32-recorder/src/storage/SdQueue.cpp` — current 4 MiB cap and RAM-loading drain path.
- `firmware/esp32-recorder/src/net/SignedHttpClient.cpp` — current `uploadWav(... std::vector<uint8_t>&)` signature that gains a streaming overload.
- `speechtotext/api/routes_ingest.py` — `DEFAULT_MAX_UPLOAD_BYTES = 256 MiB`, the source of the SD-path cap.
- Memory `reference_waveshare_epaper_pinout.md` — board pin map; `Audio_PWR=GPIO42` active-LOW.
- Memory `feedback_waveshare_epaper_gotchas.md` — bring-up rules for this specific board variant.
