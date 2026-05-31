#pragma once

#include <Arduino.h>
#include <vector>

#include "crypto/DeviceCrypto.h"
#include "net/BodySource.h"
#include "provisioning/ProvisioningProtocol.h"

namespace locallexis::net {

class SignedHttpClient {
public:
    // Streaming overload — preferred. Hashes the body in one pass, signs
    // the digest, then sends the body in a second pass without buffering.
    bool uploadWav(
        const locallexis::provisioning::ProvisioningConfig& cfg,
        const locallexis::crypto::DeviceKeys& keys,
        const String& filename,
        BodySource& source,
        String& response
    );

    // Convenience wrapper for in-RAM bodies (the demo silence-WAV path).
    // Wraps the vector in a VectorBodySource and calls the streaming
    // overload.
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
