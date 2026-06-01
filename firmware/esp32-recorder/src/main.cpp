#include <Arduino.h>
#include <WiFi.h>
#include <time.h>

#include "LocalLexisConfig.h"
#include "crypto/Base64.h"
#include "net/SignedHttpClient.h"
#include "provisioning/BleProvisioning.h"
#include "sim/WokwiProvisioning.h"
#include "storage/IdentityStore.h"
#if !defined(LOCALLEXIS_WOKWI_SIM)
#include "net/HttpStatus.h"
#include "storage/SdQueue.h"
#endif
#if !defined(LOCALLEXIS_DEMO_SILENT_WAV)
#include <optional>
#include "audio/Es8311Codec.h"
#include "audio/I2SCapture.h"
#include "audio/RecordingSession.h"
#include "audio/WavFileSink.h"
#include "audio/WavMemorySink.h"
#include "audio/WavSink.h"
#include "audio/WavWriter.h"
#include "input/BootButton.h"
#include "ui/RecorderUi.h"
#include "ui/ScreenLayout.h"
#endif

using locallexis::provisioning::BleProvisioning;
using locallexis::storage::DeviceIdentity;
using locallexis::storage::IdentityStore;

namespace {
IdentityStore g_store;
DeviceIdentity g_identity;
BleProvisioning* g_ble = nullptr;
#if !defined(LOCALLEXIS_WOKWI_SIM)
locallexis::storage::SdQueue g_sdQueue;
#endif

bool connectWifi() {
    if (String(LOCALLEXIS_WIFI_SSID).isEmpty()) {
        Serial.println("Wi-Fi SSID not configured; set LOCALLEXIS_WIFI_SSID before flashing.");
        return false;
    }
    WiFi.mode(WIFI_STA);
#if LOCALLEXIS_WIFI_CHANNEL > 0
    WiFi.begin(LOCALLEXIS_WIFI_SSID, LOCALLEXIS_WIFI_PASSWORD, LOCALLEXIS_WIFI_CHANNEL);
#else
    WiFi.begin(LOCALLEXIS_WIFI_SSID, LOCALLEXIS_WIFI_PASSWORD);
#endif
    Serial.printf("Connecting to Wi-Fi SSID %s", LOCALLEXIS_WIFI_SSID);
    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; ++i) {
        delay(500);
        Serial.print(".");
    }
    Serial.println();
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("Wi-Fi connection failed");
        return false;
    }
    Serial.printf("Wi-Fi connected: %s\n", WiFi.localIP().toString().c_str());
    return true;
}

bool syncClock() {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    Serial.print("Waiting for SNTP");
    for (int i = 0; i < 30; ++i) {
        const time_t now = time(nullptr);
        if (now > 1700000000) {
            Serial.printf("\nClock synced: %lu\n", static_cast<unsigned long>(now));
            return true;
        }
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nSNTP failed; signed hub requests will be rejected.");
    return false;
}

void startBleProvisioning() {
    if (g_ble && g_ble->active()) {
        return;
    }
    g_ble = new BleProvisioning(
        g_identity.keys,
        [](const locallexis::provisioning::ProvisioningConfig& cfg) {
            Serial.printf("Provisioned as %s for workspace %s\n",
                          cfg.deviceId.c_str(), cfg.workspaceId.c_str());
            g_store.saveProvisioning(cfg);
            g_identity.provisioning = cfg;
            g_identity.provisioned = true;
            if (g_ble) {
                g_ble->stop();
            }
        }
    );
    g_ble->begin(LOCALLEXIS_DEVICE_NAME);
}

#if defined(LOCALLEXIS_WOKWI_SIM)
void tryWokwiProvisioning() {
    if (g_identity.provisioned) {
        return;
    }
    Serial.printf("Wokwi HTTP pairing via %s\n", LOCALLEXIS_WOKWI_HUB_URL);
    String response;
    locallexis::provisioning::ProvisioningConfig cfg;
    if (!locallexis::sim::provisionWithPairingToken(g_identity.keys, cfg, response)) {
        Serial.printf("Wokwi pairing skipped/failed: %s\n", response.c_str());
        return;
    }
    g_store.saveProvisioning(cfg);
    g_identity.provisioning = cfg;
    g_identity.provisioned = true;
    Serial.printf("Wokwi paired as %s for workspace %s\n",
                  cfg.deviceId.c_str(), cfg.workspaceId.c_str());
}
#endif

// ===== Demo path: silent-WAV upload (sim only) =====
#if defined(LOCALLEXIS_DEMO_SILENT_WAV)
bool g_uploadedDemo = false;

void uploadDemoWavOnce() {
    if (g_uploadedDemo || !g_identity.provisioned || WiFi.status() != WL_CONNECTED) {
        return;
    }
    g_uploadedDemo = true;
    Serial.println("Uploading demo silence WAV to hub...");
    const auto wav = locallexis::net::makeSilenceWav(16000, 1);
    String response;
    locallexis::net::SignedHttpClient client;
    const bool ok = client.uploadWav(
        g_identity.provisioning, g_identity.keys, "esp32-demo.wav", wav, response);
    Serial.printf("Upload result: %s\n%s\n", ok ? "ok" : "failed", response.c_str());
}
#endif

// ===== Live recorder (real device) =====
#if !defined(LOCALLEXIS_DEMO_SILENT_WAV)
using locallexis::audio::RecState;
using locallexis::audio::StopReason;
using locallexis::audio::WavSink;

locallexis::audio::Es8311Codec g_codec(
    LOCALLEXIS_I2C_SDA, LOCALLEXIS_I2C_SCL, LOCALLEXIS_AUDIO_PWR, LOCALLEXIS_ES8311_ADDR);
locallexis::audio::I2SCapture g_capture(
    locallexis::audio::I2SPins{
        LOCALLEXIS_I2S_MCLK, LOCALLEXIS_I2S_BCLK, LOCALLEXIS_I2S_WS, LOCALLEXIS_I2S_DIN},
    LOCALLEXIS_AUDIO_SAMPLE_RATE);
locallexis::input::BootButton g_button(LOCALLEXIS_BOOT_BTN);
locallexis::ui::RecorderUi g_ui(
    locallexis::ui::EpdPins{
        LOCALLEXIS_EPD_BUSY, LOCALLEXIS_EPD_RST, LOCALLEXIS_EPD_DC, LOCALLEXIS_EPD_CS,
        LOCALLEXIS_EPD_SCK, LOCALLEXIS_EPD_MOSI, LOCALLEXIS_EPD_PWR},
    LOCALLEXIS_LED);

// SD-or-PSRAM chooser. Owns both sinks; hands a NON-owning pointer to the session for
// the duration of one recording (sinks are reusable after close()/discard()).
class MainSinkFactory : public locallexis::audio::SinkFactory {
public:
    bool sdReady() const override { return g_sdQueue.ready(); }
    WavSink* makeSink(bool sd) override {
        return sd ? static_cast<WavSink*>(&fileSink_) : static_cast<WavSink*>(&memSink_);
    }
private:
    locallexis::audio::WavFileSink fileSink_{
        g_sdQueue, LOCALLEXIS_AUDIO_SAMPLE_RATE, 1, LOCALLEXIS_AUDIO_SD_CAP_BYTES};
    locallexis::audio::WavMemorySink memSink_{
        LOCALLEXIS_AUDIO_SAMPLE_RATE, 1, LOCALLEXIS_AUDIO_NOSD_CAP_BYTES};
};
MainSinkFactory g_sinks;
locallexis::audio::RecordingSession g_session(g_codec, g_capture, g_button, g_sinks);

// Single-slot upload buffer for a PSRAM clip recorded while no card was present.
std::optional<std::vector<uint8_t>> g_pendingClip;
String g_pendingClipName;

// Display-only clip counter (zero-padded to 3 on screen).
uint16_t g_uiClip = 0;

// Double-tap in Standby => manual sync. Detected in loop(), no ISR change.
uint32_t g_lastTapMs = 0;
bool g_manualSync = false;
constexpr uint32_t kDoubleTapMs = 400;

String makeClipName() {
    return String("rec-") + String(static_cast<unsigned long>(time(nullptr))) + ".wav";
}

void onClipReady(WavSink& sink) {
    // Populate Saved fields BEFORE onState renders (RecordingSession calls onClip then emitState).
    const size_t total = sink.bytesWritten();
    const size_t dataBytes = total > locallexis::audio::kWavHeaderBytes
                                 ? total - locallexis::audio::kWavHeaderBytes : 0;
    const uint32_t secs = static_cast<uint32_t>(dataBytes / (LOCALLEXIS_AUDIO_SAMPLE_RATE * 2));
    char dur[8];  locallexis::ui::formatDuration(secs, dur);
    char sz[12];  locallexis::ui::formatSize(static_cast<uint32_t>(total), sz);
    std::snprintf(g_ui.model().lastDur,  sizeof(g_ui.model().lastDur),  "%s", dur);
    std::snprintf(g_ui.model().lastSize, sizeof(g_ui.model().lastSize), "%s", sz);
    g_ui.model().clip = ++g_uiClip;

    if (!sink.isMemoryBacked()) {
        return;  // file sink already committed Q<NNNN>.wav to the queue; drain handles it.
    }
    if (g_pendingClip.has_value()) {
        Serial.println("Recorder: overwriting an un-uploaded PSRAM clip (no card; single slot).");
    }
    g_pendingClip = sink.takeBytes();
    g_pendingClipName = makeClipName();
    Serial.printf("Recorder: PSRAM clip ready (%u bytes), pending upload\n",
                  static_cast<unsigned>(g_pendingClip->size()));
}

void uploadPendingClipStep() {
    if (!g_pendingClip.has_value()) return;
    if (!g_identity.provisioned || WiFi.status() != WL_CONNECTED) return;

    String response;
    locallexis::net::SignedHttpClient client;
    const bool ok = client.uploadWav(
        g_identity.provisioning, g_identity.keys, g_pendingClipName, *g_pendingClip, response);
    const int status = locallexis::net::httpStatusFromResponse(std::string(response.c_str()));
    Serial.printf("PSRAM clip upload: %s (HTTP %d)\n%s\n",
                  ok ? "ok" : "failed", status, response.c_str());

    if (ok || (status >= 400 && status < 500)) {
        g_pendingClip.reset();  // success OR unretryable client error -> drop
    } else {
        delay(2000);            // transient -> retry next loop
    }
}
#endif  // !LOCALLEXIS_DEMO_SILENT_WAV

// ===== SD drain (real device) =====
#if !defined(LOCALLEXIS_WOKWI_SIM)
void drainQueueStep() {
    if (!g_sdQueue.ready() || !g_identity.provisioned || WiFi.status() != WL_CONNECTED) {
        return;
    }
    String path;
    if (!g_sdQueue.peekOldestPath(path)) return;

    auto reader = g_sdQueue.openReader(path);
    if (!reader) {
        Serial.printf("Drain: could not open %s\n", path.c_str());
        delay(2000);
        return;
    }
    const int slash = path.lastIndexOf('/');
    const String filename = slash >= 0 ? path.substring(slash + 1) : path;

    Serial.printf("Draining %s (%u bytes)\n",
                  filename.c_str(), static_cast<unsigned>(reader->size()));
    String response;
    locallexis::net::SignedHttpClient client;
    const bool ok = client.uploadWav(
        g_identity.provisioning, g_identity.keys, filename, *reader, response);
    const int status = locallexis::net::httpStatusFromResponse(std::string(response.c_str()));
    Serial.printf("Drain result: %s (HTTP %d)\n%s\n",
                  ok ? "ok" : "failed", status, response.c_str());

    if (ok) {
        g_sdQueue.removeFile(path);
    } else if (status >= 400 && status < 500) {
        Serial.printf("Drain: hub rejected %s (HTTP %d); discarding\n", filename.c_str(), status);
        g_sdQueue.removeFile(path);  // unretryable: drop so the queue cannot wedge
    } else {
        delay(2000);  // transient (5xx / network) -> retry next loop
    }
}
#endif
}  // namespace

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\nLocalLexis ESP32 recorder firmware");

    if (!psramFound()) {
        Serial.println("PSRAM not detected; live recording buffers will be limited.");
    } else {
        Serial.printf("PSRAM: %u bytes\n", ESP.getPsramSize());
    }

    if (!g_store.begin()) {
        Serial.println("Failed to open NVS identity store");
    }
    g_store.load(g_identity);

#if !defined(LOCALLEXIS_WOKWI_SIM)
    g_sdQueue.begin(LOCALLEXIS_SD_CLK, LOCALLEXIS_SD_CMD, LOCALLEXIS_SD_D0);
#endif

    const String pubkeyB64 = locallexis::crypto::base64Encode(
        g_identity.keys.publicKey, sizeof(g_identity.keys.publicKey));
    Serial.printf("Device public key: %s\n", pubkeyB64.c_str());

#if !defined(LOCALLEXIS_DEMO_SILENT_WAV)
    // Live recorder: bring up UI + button, wire callbacks, arm for the first tap.
    g_ui.begin();
    g_button.begin();
    g_button.arm();  // Standby is tap-ready; the session re-arms on every state change.
    g_capture.setPcmCallback([](const uint8_t* b, size_t n) { g_session.onPcm(b, n); });
    g_session.setOnState([](RecState s, StopReason r) { g_ui.onState(s, r); });
    g_session.setOnClip(onClipReady);

    // DECISION: Connection screen — no BLE-to-Mac connect event exists. Gated OFF.
    //   To demo on first WiFi connect: g_ui.showConnection(4); (transport-neutral copy)
    // DECISION: Battery screen — no fuel gauge/ADC reader. battery pinned to 100.
    g_ui.model().battery = 100;             // never crosses the low threshold
    // DECISION: Storage screen — real trigger is a record-start failure at the SD cap,
    //   already routed via StopReason::Error/Full -> Storage in RecorderUi::onState.
#endif

    if (!g_identity.provisioned) {
#if defined(LOCALLEXIS_WOKWI_SIM)
        Serial.println("Not provisioned; Wokwi sim will try HTTP pairing after Wi-Fi.");
#else
        Serial.println("Not provisioned; starting BLE setup.");
        startBleProvisioning();
#endif
    } else {
        Serial.printf("Provisioned for hub %s as %s\n",
                      g_identity.provisioning.hubUrl.c_str(),
                      g_identity.provisioning.deviceId.c_str());
    }

    if (connectWifi()) {
#if defined(LOCALLEXIS_WOKWI_SIM)
        tryWokwiProvisioning();
#endif
        if (syncClock()) {
#if defined(LOCALLEXIS_DEMO_SILENT_WAV)
            uploadDemoWavOnce();
#endif
        }
    }
}

void loop() {
#if !defined(LOCALLEXIS_DEMO_SILENT_WAV)
    // Hold (~0.5 s) => start recording (only meaningful in Standby).
    if (g_button.consumeHold()) {
        if (g_session.state() == RecState::Standby) {
            time_t now = time(nullptr);
            struct tm lt; localtime_r(&now, &lt);
            strftime(g_ui.model().startedAt, sizeof(g_ui.model().startedAt), "%-l:%M %p", &lt);
            g_ui.model().clip = g_uiClip;   // will be incremented in onClipReady at stop
            g_session.toggle();             // -> Recording; emitState renders via onState
        }
    }
    // Short tap => stop recording (Recording); double-tap => manual sync (Standby).
    if (g_button.consumeTap()) {
        if (g_session.state() == RecState::Recording) {
            g_session.toggle();             // -> Standby; onClip+onState populate Saved
        } else if (g_session.state() == RecState::Standby) {
            const uint32_t now = millis();
            if (g_lastTapMs != 0 && now - g_lastTapMs <= kDoubleTapMs) {
                g_manualSync = true;        // two quick taps in Standby
                g_lastTapMs = 0;
            } else {
                g_lastTapMs = now;          // first tap; wait for a second
            }
        }
    }
    g_capture.pump();  // drain I2S ringbuffer -> g_session.onPcm (single-threaded; no-op when stopped)
    g_ui.tick();       // LED blink + transient error-screen timeout
#endif

    const bool online = g_identity.provisioned && WiFi.status() == WL_CONNECTED;
#if defined(LOCALLEXIS_DEMO_SILENT_WAV)
    if (online) {
        uploadDemoWavOnce();
    }
    delay(1000);
#elif !defined(LOCALLEXIS_WOKWI_SIM)
    // Upload only while idle so a blocking upload never starves capture.pump().
    if (g_session.state() == RecState::Standby) {
        if (g_manualSync) {
            g_manualSync = false;
            g_ui.showSyncing(0, 1);          // double-tap feedback (even offline)
            if (online) {
                if (g_sdQueue.ready()) drainQueueStep();
                else uploadPendingClipStep();
            }
            g_ui.showIdle();
        } else if (online) {
            if (g_sdQueue.ready()) {
                drainQueueStep();
            } else {
                uploadPendingClipStep();
            }
        }
    }
    delay(5);  // keep pump() latency low; the ring is ~1 s deep
#else
    delay(5);
#endif
}
