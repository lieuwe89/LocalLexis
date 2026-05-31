#pragma once

#include <Arduino.h>
#include <Ed25519.h>
#include <cstdint>

namespace locallexis::crypto {

struct DeviceKeys {
    uint8_t privateKey[32]{};
    uint8_t publicKey[32]{};
};

void deriveKeys(DeviceKeys& keys);
void generatePrivateKey(uint8_t privateKey[32]);

// Sign the v2 message for a body whose SHA-256 is already computed.
// Used by the streaming uploader so the full body never lives in RAM.
String signRequestB64WithBodyDigest(
    const DeviceKeys& keys,
    const String& method,
    const String& pathAndQuery,
    const String& timestamp,
    const String& nonce,
    const uint8_t bodySha256[32]
);

String randomNonceHex();

}  // namespace locallexis::crypto
