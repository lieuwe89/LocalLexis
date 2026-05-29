#include "provisioning/BleProvisioning.h"

#include <ArduinoJson.h>
#include <NimBLEDevice.h>
#include <utility>

#include "LocalLexisConfig.h"
#include "crypto/Base64.h"

namespace locallexis::provisioning {

namespace {
FrameReassembler g_reassembler;
ProvisionedCallback g_onProvisioned;

String buildHelloJson(const locallexis::crypto::DeviceKeys& keys) {
    JsonDocument doc;
    doc["protocol"] = kProtocol;
    doc["device_pubkey_b64"] = locallexis::crypto::base64Encode(keys.publicKey, 32);
    doc["device_name"] = LOCALLEXIS_DEVICE_NAME;
    doc["firmware"] = "0.1.0";
    String out;
    serializeJson(doc, out);
    return out;
}

class ProvisionRxCallbacks final : public NimBLECharacteristicCallbacks {
public:
    void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& connInfo) override {
        (void)connInfo;
        const std::string value = characteristic->getValue();
        std::vector<uint8_t> frame(value.begin(), value.end());
        const bool complete = g_reassembler.accept(frame);
        if (!g_reassembler.error().empty()) {
            Serial.printf("BLE provisioning error: %s\n", g_reassembler.error().c_str());
            g_reassembler.reset();
            return;
        }
        if (!complete) {
            return;
        }

        ProvisioningConfig cfg;
        std::string error;
        if (!parseProvisioningJson(g_reassembler.payload(), cfg, error)) {
            Serial.printf("Provisioning JSON error: %s\n", error.c_str());
            g_reassembler.reset();
            return;
        }
        g_reassembler.reset();
        if (g_onProvisioned) {
            g_onProvisioned(cfg);
        }
    }
};

ProvisionRxCallbacks g_rxCallbacks;
}  // namespace

BleProvisioning::BleProvisioning(
    const locallexis::crypto::DeviceKeys& keys,
    ProvisionedCallback onProvisioned
) : keys_(keys), onProvisioned_(std::move(onProvisioned)) {}

void BleProvisioning::begin(const String& advertisedName) {
    g_onProvisioned = onProvisioned_;
    g_reassembler.reset();

    NimBLEDevice::init(advertisedName.c_str());
    NimBLEDevice::setPower(ESP_PWR_LVL_P9);

    NimBLEServer* server = NimBLEDevice::createServer();
    NimBLEService* service = server->createService(LOCALLEXIS_BLE_SERVICE_UUID);

    NimBLECharacteristic* hello = service->createCharacteristic(
        LOCALLEXIS_BLE_HELLO_UUID,
        NIMBLE_PROPERTY::READ
    );
    hello->setValue(buildHelloJson(keys_).c_str());

    NimBLECharacteristic* rx = service->createCharacteristic(
        LOCALLEXIS_BLE_PROVISION_RX_UUID,
        NIMBLE_PROPERTY::WRITE
    );
    rx->setCallbacks(&g_rxCallbacks);

    NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
    advertising->addServiceUUID(LOCALLEXIS_BLE_SERVICE_UUID);
    advertising->setName(advertisedName.c_str());
    advertising->start();
    active_ = true;

    Serial.printf("BLE provisioning active as %s\n", advertisedName.c_str());
}

void BleProvisioning::stop() {
    if (!active_) {
        return;
    }
    NimBLEDevice::getAdvertising()->stop();
    active_ = false;
}

bool BleProvisioning::active() const {
    return active_;
}

}  // namespace locallexis::provisioning
