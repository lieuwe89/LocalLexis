#include <Arduino.h>
#include <WiFi.h>
#include <time.h>

#include "LocalLexisConfig.h"
#include "crypto/Base64.h"
#include "net/SignedHttpClient.h"
#include "provisioning/BleProvisioning.h"
#include "sim/WokwiProvisioning.h"
#include "storage/IdentityStore.h"

using locallexis::provisioning::BleProvisioning;
using locallexis::storage::DeviceIdentity;
using locallexis::storage::IdentityStore;

namespace {
IdentityStore g_store;
DeviceIdentity g_identity;
BleProvisioning* g_ble = nullptr;
bool g_uploadedDemo = false;

bool connectWifi() {
    if (String(LOCALLEXIS_WIFI_SSID).isEmpty()) {
        Serial.println("Wi-Fi SSID not configured; set LOCALLEXIS_WIFI_SSID before flashing.");
        return false;
    }
    WiFi.mode(WIFI_STA);
#if LOCALLEXIS_WIFI_CHANNEL > 0
    WiFi.begin(
        LOCALLEXIS_WIFI_SSID,
        LOCALLEXIS_WIFI_PASSWORD,
        LOCALLEXIS_WIFI_CHANNEL
    );
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
                          cfg.deviceId.c_str(),
                          cfg.workspaceId.c_str());
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
                  cfg.deviceId.c_str(),
                  cfg.workspaceId.c_str());
}
#endif

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
        g_identity.provisioning,
        g_identity.keys,
        "esp32-demo.wav",
        wav,
        response
    );
    Serial.printf("Upload result: %s\n%s\n", ok ? "ok" : "failed", response.c_str());
}
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

    const String pubkeyB64 = locallexis::crypto::base64Encode(
        g_identity.keys.publicKey,
        sizeof(g_identity.keys.publicKey)
    );
    Serial.printf("Device public key: %s\n", pubkeyB64.c_str());

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
            uploadDemoWavOnce();
        }
    }
}

void loop() {
    if (g_identity.provisioned && WiFi.status() == WL_CONNECTED) {
        uploadDemoWavOnce();
    }
    delay(1000);
}
