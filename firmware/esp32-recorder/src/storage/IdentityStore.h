#pragma once

#include <Arduino.h>
#include <Preferences.h>

#include "crypto/DeviceCrypto.h"
#include "provisioning/ProvisioningProtocol.h"

namespace locallexis::storage {

struct DeviceIdentity {
    bool provisioned = false;
    locallexis::crypto::DeviceKeys keys;
    locallexis::provisioning::ProvisioningConfig provisioning;
};

class IdentityStore {
public:
    bool begin();
    bool load(DeviceIdentity& out);
    bool savePrivateKey(const uint8_t privateKey[32]);
    bool saveProvisioning(const locallexis::provisioning::ProvisioningConfig& cfg);
    void clear();

private:
    Preferences prefs_;
};

}  // namespace locallexis::storage
