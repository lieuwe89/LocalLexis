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
#include <vector>
#include "audio/DcBlocker.h"
#include "audio/Es8311Codec.h"
#include "audio/I2SCapture.h"
#include "audio/RecordingSession.h"
#include "audio/WavFileSink.h"
#include "audio/WavMemorySink.h"
#include "audio/WavSink.h"
#include "audio/WavWriter.h"
#include "input/BootButton.h"
#include "input/PowerButton.h"
#include "power/BatteryGauge.h"
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
locallexis::input::PowerButton g_power(LOCALLEXIS_PWR_BTN, 2000);  // hold 2 s to power off
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

// DC-blocking high-pass on the mic stream (kills the ES8311 ~+17k DC offset
// that otherwise clips transients). Filtered into a reused scratch buffer so
// the const capture bytes are not mutated. Reset at each record start.
locallexis::audio::DcBlocker g_dcBlocker;
std::vector<uint8_t> g_pcmScratch;

// Display-only clip counter (zero-padded to 3 on screen).
uint16_t g_uiClip = 0;

// Double-tap in Standby => manual sync. Detected in loop(), no ISR change.
uint32_t g_lastTapMs = 0;
bool g_manualSync = false;
constexpr uint32_t kDoubleTapMs = 400;

// Battery gauge. Sampled only while idle (never under recording load); the gauge
// smooths + 5%-buckets the reading so the e-paper rarely needs a dedicated refresh.
locallexis::power::BatteryGauge g_battery;
uint32_t g_lastBatteryMs = 0;
bool g_batterySampled = false;
constexpr uint32_t kBatterySampleMs = 30000;  // 30 s between samples

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

// PWR-button long-press => graceful shutdown. Stop any active recording first so the
// WAV is flushed + committed (stopRecording closes the sink synchronously), repaint a
// neutral frame so a stale "Listening." isn't frozen on the panel, then drop the
// VBAT latch (GPIO17 LOW) to cut the battery rail. On USB power the rail stays up, so
// we spin afterward rather than silently continue running as if still "on".
void powerOff() {
    Serial.println("PWR held: shutting down.");
    if (g_session.state() == RecState::Recording) {
        g_session.toggle();              // -> Standby: capture stop, codec off, sink close+commit
    }
    // The PWR button bridges battery->system while held, so dropping the latch can't
    // cut power until the button is released. Light the LED as a "release now" cue,
    // drop the latch, then wait for a clean release — on battery the board dies here.
    // Status LED is normally solid-on, so signal shutdown with a quick blink burst,
    // then leave it off while waiting for release (active-LOW: LOW=on, HIGH=off).
    for (int i = 0; i < 6; ++i) { digitalWrite(LOCALLEXIS_LED, (i & 1) ? LOW : HIGH); delay(80); }
    digitalWrite(LOCALLEXIS_LED, HIGH);      // off
    digitalWrite(LOCALLEXIS_VBAT_PWR, LOW);  // de-latch; takes effect once the button is up

    uint32_t releasedAt = 0;
    while (true) {
        if (digitalRead(LOCALLEXIS_PWR_BTN) == HIGH) {     // button released (pull-up)
            if (releasedAt == 0) releasedAt = millis();
            else if (millis() - releasedAt >= 50) break;   // debounced release
        } else {
            releasedAt = 0;
        }
        delay(10);
    }
    // Only reached on external (USB) power, where the rail can't be cut: reboot to a
    // clean state instead of hanging on the same frame.
    delay(50);
    ESP.restart();
}

// Averaged battery voltage in mV (ADC reading x2 for the 1:1 divider).
uint32_t readBatteryMilliVolts() {
    uint32_t acc = 0;
    for (int i = 0; i < 16; ++i) acc += analogReadMilliVolts(LOCALLEXIS_BAT_ADC);
    return (acc / 16) * 2;
}

// Sample the battery and refresh the gauge. Only runs while Standby (never under
// recording load, which would sag the reading). model().battery is kept current so
// any *other* repaint (boot/Saved/Syncing -> Idle) shows a fresh % for free; a
// dedicated refresh happens only when parked on Idle and the 5% bucket actually moves.
void serviceBattery() {
    if (g_session.state() != RecState::Standby) return;
    const uint32_t now = millis();
    if (g_batterySampled && (now - g_lastBatteryMs) < kBatterySampleMs) return;
    g_lastBatteryMs = now;
    g_batterySampled = true;

    const auto ev = g_battery.update(readBatteryMilliVolts());
    g_ui.model().battery = g_battery.percent();

    if (g_ui.model().screen != locallexis::ui::Screen::Idle) return;
    if (ev == locallexis::power::BatteryGauge::Event::LowAlarm) {
        g_ui.showBattery(g_battery.percent());            // low-power warning frame
    } else if (ev == locallexis::power::BatteryGauge::Event::BucketChanged &&
               !g_battery.lowAlarm()) {
        g_ui.showIdle();                                  // tick the corner % down
    }
}

#if LOCALLEXIS_SCREEN_TEST
// Diagnostic screen previewer: type 0-7 over serial to render each UI frame.
// Renders via model()+showCurrent() (not the show*() helpers) so no auto-advance
// timer flips the panel back to Idle before it can be photographed.
void serviceScreenTest() {
    using locallexis::ui::Screen;
    if (!Serial.available()) return;
    const int c = Serial.read();
    locallexis::ui::UiModel& m = g_ui.model();
    switch (c) {
        case '0': m.screen = Screen::Boot; g_ui.showCurrent(); break;
        case '1': m.screen = Screen::Idle; g_ui.showCurrent(); break;
        case '2':
            m.screen = Screen::Recording;
            std::snprintf(m.startedAt, sizeof(m.startedAt), "9:41 AM");
            m.clip = 14;
            g_ui.showCurrent();
            break;
        case '3':
            m.screen = Screen::Saved;
            m.clip = 14;
            std::snprintf(m.lastDur, sizeof(m.lastDur), "1:23");
            std::snprintf(m.lastSize, sizeof(m.lastSize), "2.6 MB");
            g_ui.showCurrent();
            break;
        case '4': m.screen = Screen::Syncing; m.syncDone = 2; m.syncTotal = 5; g_ui.showCurrent(); break;
        case '5': m.screen = Screen::Connection; m.signal = 4; g_ui.showCurrent(); break;
        case '6': m.screen = Screen::Battery; m.battery = 76; g_ui.showCurrent(); break;
        case '7': m.screen = Screen::Storage; g_ui.showCurrent(); break;
        case '\r':
        case '\n':
            return;
        default:
            Serial.println("screen-test keys: 0 Boot 1 Idle 2 Recording 3 Saved "
                           "4 Syncing 5 Connection 6 Battery 7 Storage");
            return;
    }
    Serial.printf("screen-test: rendered '%c'\n", static_cast<char>(c));
}
#endif  // LOCALLEXIS_SCREEN_TEST
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
    // Latch battery power ON immediately. VBAT_PWR (GPIO17) is active-HIGH; until this
    // runs the board is powered only while the PWR button is physically held, so it
    // dies the instant you let go. Driving it HIGH holds the soft-power latch closed.
    // Must be first so a hang in later init can't strand the device. Harmless on USB.
    pinMode(LOCALLEXIS_VBAT_PWR, OUTPUT);
    digitalWrite(LOCALLEXIS_VBAT_PWR, HIGH);
    // Early "powered on — you can release the button" cue: light the LED the instant
    // the latch holds, well before the e-paper boot screen renders (active-LOW). The
    // UI takes the LED over once g_ui.begin() runs.
    pinMode(LOCALLEXIS_LED, OUTPUT);
    digitalWrite(LOCALLEXIS_LED, LOW);

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
    g_power.begin();
    g_button.arm();  // Standby is tap-ready; the session re-arms on every state change.
    g_capture.setPcmCallback([](const uint8_t* b, size_t n) {
        g_pcmScratch.assign(b, b + n);
        g_dcBlocker.processBytes(g_pcmScratch.data(), g_pcmScratch.size());
        g_session.onPcm(g_pcmScratch.data(), g_pcmScratch.size());
    });
    g_session.setOnState([](RecState s, StopReason r) { g_ui.onState(s, r); });
    g_session.setOnClip(onClipReady);

    // DECISION: Connection screen — no BLE-to-Mac connect event exists. Gated OFF.
    //   To demo on first WiFi connect: g_ui.showConnection(4); (transport-neutral copy)
    // Battery gauge on GPIO4. 11 dB attenuation covers the divided cell voltage
    // (~1.5-2.06 V at the pin). Prime with one reading so the first Idle frame shows
    // a real % instead of flickering 100% -> actual on boot.
    analogSetPinAttenuation(LOCALLEXIS_BAT_ADC, ADC_11db);
    g_battery.update(readBatteryMilliVolts());
    g_ui.model().battery = g_battery.percent();
    // DECISION: Storage screen — real trigger is a record-start failure at the SD cap,
    //   already routed via StopReason::Error/Full -> Storage in RecorderUi::onState.
#if LOCALLEXIS_SCREEN_TEST
    Serial.println("SCREEN-TEST build: loop() is a serial screen previewer (recorder disabled).");
    Serial.println("screen-test keys: 0 Boot 1 Idle 2 Recording 3 Saved "
                   "4 Syncing 5 Connection 6 Battery 7 Storage");
#endif
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
#if LOCALLEXIS_SCREEN_TEST
    serviceScreenTest();   // serial-driven UI previewer; the recorder loop is disabled in this build
    delay(10);
    return;
#endif
    // PWR button held >= 2 s => power off. Checked first so a shutdown always wins.
    if (g_power.consumeLongPress()) {
        powerOff();  // does not return (cuts the battery rail)
    }
    // Hold (~0.5 s) => start recording (only meaningful in Standby).
    if (g_button.consumeHold()) {
        if (g_session.state() == RecState::Standby) {
            g_dcBlocker.reset();            // clear filter state for the new clip
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
    serviceBattery();  // idle-only ADC sample; self-gated on Standby + 30 s cadence
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
