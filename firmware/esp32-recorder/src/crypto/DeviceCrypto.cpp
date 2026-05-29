#include "crypto/DeviceCrypto.h"

#include <vector>

#include <esp_random.h>

#include "crypto/Base64.h"

namespace locallexis::crypto {

void generatePrivateKey(uint8_t privateKey[32]) {
    for (size_t i = 0; i < 32; i += 4) {
        const uint32_t word = esp_random();
        privateKey[i] = static_cast<uint8_t>(word & 0xff);
        privateKey[i + 1] = static_cast<uint8_t>((word >> 8) & 0xff);
        privateKey[i + 2] = static_cast<uint8_t>((word >> 16) & 0xff);
        privateKey[i + 3] = static_cast<uint8_t>((word >> 24) & 0xff);
    }
}

void deriveKeys(DeviceKeys& keys) {
    Ed25519::derivePublicKey(keys.publicKey, keys.privateKey);
}

String signRequestB64(
    const DeviceKeys& keys,
    const String& method,
    const String& pathAndQuery,
    const String& timestamp,
    const String& nonce,
    const uint8_t* body,
    size_t bodyLen
) {
    std::vector<uint8_t> message;
    const String prefix = method + "\n" + pathAndQuery + "\n" + timestamp + "\n" + nonce + "\n";
    message.insert(message.end(), prefix.begin(), prefix.end());
    message.insert(message.end(), body, body + bodyLen);

    uint8_t signature[64];
    Ed25519::sign(
        signature,
        keys.privateKey,
        keys.publicKey,
        message.data(),
        message.size()
    );
    return base64Encode(signature, sizeof(signature));
}

String randomNonceHex() {
    constexpr char hex[] = "0123456789abcdef";
    uint8_t raw[8];
    for (uint8_t& b : raw) {
        b = static_cast<uint8_t>(esp_random() & 0xff);
    }
    char out[17]{};
    for (size_t i = 0; i < sizeof(raw); ++i) {
        out[2 * i] = hex[(raw[i] >> 4) & 0x0f];
        out[2 * i + 1] = hex[raw[i] & 0x0f];
    }
    return String(out);
}

}  // namespace locallexis::crypto
