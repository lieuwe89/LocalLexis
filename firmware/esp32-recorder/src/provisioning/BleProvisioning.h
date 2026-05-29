#pragma once

#include <functional>

#include <Arduino.h>

#include "crypto/DeviceCrypto.h"
#include "provisioning/ProvisioningProtocol.h"

namespace locallexis::provisioning {

using ProvisionedCallback = std::function<void(const ProvisioningConfig&)>;

class BleProvisioning {
public:
    BleProvisioning(
        const locallexis::crypto::DeviceKeys& keys,
        ProvisionedCallback onProvisioned
    );

    void begin(const String& advertisedName);
    void stop();
    bool active() const;

private:
    const locallexis::crypto::DeviceKeys& keys_;
    ProvisionedCallback onProvisioned_;
    bool active_ = false;
};

}  // namespace locallexis::provisioning
