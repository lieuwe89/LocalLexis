#pragma once

#include <Arduino.h>
#include <vector>

#include "crypto/DeviceCrypto.h"
#include "provisioning/ProvisioningProtocol.h"

namespace locallexis::net {

class SignedHttpClient {
public:
    bool uploadWav(
        const locallexis::provisioning::ProvisioningConfig& cfg,
        const locallexis::crypto::DeviceKeys& keys,
        const String& filename,
        const std::vector<uint8_t>& wavBytes,
        String& response
    );
};

std::vector<uint8_t> makeSilenceWav(uint32_t sampleRate, uint16_t seconds);

}  // namespace locallexis::net
