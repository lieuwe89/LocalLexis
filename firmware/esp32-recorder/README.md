# LocalLexis ESP32 Recorder Firmware

Starter firmware for the Waveshare ESP32-S3 ePaper 1.54 board.

This slice proves the setup loop:

1. Generate and persist an Ed25519 device private key in NVS.
2. Advertise as a BLE peripheral named `LocalLexis Recorder`.
3. Expose a read-only hello characteristic with the device public key.
4. Receive desktop provisioning frames from LocalLexis over BLE.
5. Persist hub URL, workspace id, hub-assigned device id, sealed workspace key, and TLS pin.
6. Connect to Wi-Fi, sync SNTP time, verify the hub TLS SPKI pin when HTTPS is used, sign `POST /jobs/upload`, and upload a tiny demo WAV.

The BLE contract matches the desktop Tauri implementation:

- Service: `8f0d1b0a-1e5c-4d0c-9ad0-f0c4f5e9d001`
- Hello characteristic: `8f0d1b0a-1e5c-4d0c-9ad0-f0c4f5e9d002`
- Provisioning RX characteristic: `8f0d1b0a-1e5c-4d0c-9ad0-f0c4f5e9d003`
- Provisioning frames are 20 bytes max: version, seq, total, len, and up to 14 bytes of JSON payload.

## Configure

Create `include/LocalLexisConfig.local.h` before flashing:

```cpp
#pragma once
#include "LocalLexisConfig.local.example.h"

#undef LOCALLEXIS_WIFI_SSID
#undef LOCALLEXIS_WIFI_PASSWORD
#define LOCALLEXIS_WIFI_SSID "your-network"
#define LOCALLEXIS_WIFI_PASSWORD "your-password"
```

`include/LocalLexisConfig.local.h` is ignored by git. Wi-Fi credentials are not sent over BLE in this version because that payload is not encrypted yet.

## Build

```bash
cd firmware/esp32-recorder
pio run
pio run --target upload
pio device monitor
```

## Wokwi Private Gateway Simulation

Wokwi cannot simulate BLE, so the `wokwi-sim` build uses HTTP pairing with a
one-time LocalLexis pairing token instead of the BLE provisioning characteristic.
After pairing, it saves the hub response in NVS and runs the same signed demo
upload path as the hardware firmware.

The gateway binary is expected at `~/.local/bin/wokwigw`. Run it before starting
the simulator:

```bash
~/.local/bin/wokwigw
```

Create a local Wokwi config:

```cpp
// include/LocalLexisConfig.wokwi.local.h
#pragma once
#include "LocalLexisConfig.wokwi.local.example.h"

#undef LOCALLEXIS_WOKWI_HUB_URL
#undef LOCALLEXIS_WOKWI_PAIRING_TOKEN

#define LOCALLEXIS_WOKWI_HUB_URL "http://host.wokwi.internal:8765"
#define LOCALLEXIS_WOKWI_PAIRING_TOKEN "paste-one-time-pairing-token-here"
```

Then build the simulator firmware and open the project in Wokwi for VS Code:

```bash
pio run -e wokwi-sim
```

The checked-in `wokwi.toml` points Wokwi at
`.pio/build/wokwi-sim/firmware.bin` and configures the private gateway at
`ws://localhost:9011`. The simulator connects to Wi-Fi as `Wokwi-GUEST` on
channel 6 and reaches the hub through `host.wokwi.internal`.

## microSD Upload Queue

If a microSD card is present, recordings are buffered to `/queue/` on the
card before they are uploaded. The uploader drains the oldest file first,
deletes it on a `202` from the hub, and retries the same file on failure.
This means recording survives Wi-Fi outages, hub downtime, and reboots.

Defaults match the Waveshare ESP32-S3-ePaper-1.54 V2 wiring, which uses
1-bit SDMMC (not SPI):

| Signal | GPIO |
| ------ | ---- |
| CLK    | 39   |
| CMD    | 41   |
| D0     | 40   |

Override in `LocalLexisConfig.local.h` if your board differs:

```cpp
#undef LOCALLEXIS_SD_CLK
#define LOCALLEXIS_SD_CLK 14
```

Files are named `Q<NNNNNNNNNNNN>.wav` using a monotonic NVS counter, so
lexicographic order is chronological. In-progress writes use a
`.wav.partial` suffix and are renamed on close; any partial files left
behind by a crash are deleted on boot.

Per-file size is capped at 4 MiB. Enqueue is rejected when the card is
over 95% full.

If the card is missing or fails to mount, the firmware falls back to the
direct in-memory demo upload so single-shot smoke tests still work.

## Current Limits

- Demo upload uses a generated 1-second silent WAV (enqueued to SD when present).
- Live I2S capture and e-paper UI are not implemented yet.
- HTTPS uploads require the provisioned TLS SPKI pin and verify it before audio bytes are sent.
- The sealed workspace key is stored as received; the firmware does not need to unseal it for signed upload, but future encrypted sync features may.
- Protocol v2 (sha256(body) signing + streaming upload, gated by `LOCALLEXIS_PROTO_VERSION=2`): one-hour 16 kHz mono 16-bit recordings upload through a 4 KB streaming buffer with no full-body allocation. The drain path streams queued files chunk-by-chunk via `SdQueue::openReader` + `SignedHttpClient::uploadWav(BodySource&)`; multi-MB clips no longer load fully into RAM.
