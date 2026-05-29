#pragma once

#if defined(LOCALLEXIS_WOKWI_SIM)

#include <Arduino.h>

#include "crypto/DeviceCrypto.h"
#include "provisioning/ProvisioningProtocol.h"

namespace locallexis::sim {

bool provisionWithPairingToken(
    const locallexis::crypto::DeviceKeys& keys,
    locallexis::provisioning::ProvisioningConfig& out,
    String& response
);

}  // namespace locallexis::sim

#endif
