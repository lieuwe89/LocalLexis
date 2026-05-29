#pragma once

#include <Arduino.h>
#include <Ed25519.h>

namespace locallexis::crypto {

struct DeviceKeys {
    uint8_t privateKey[32]{};
    uint8_t publicKey[32]{};
};

void deriveKeys(DeviceKeys& keys);
void generatePrivateKey(uint8_t privateKey[32]);
String signRequestB64(
    const DeviceKeys& keys,
    const String& method,
    const String& pathAndQuery,
    const String& timestamp,
    const String& nonce,
    const uint8_t* body,
    size_t bodyLen
);
String randomNonceHex();

}  // namespace locallexis::crypto
