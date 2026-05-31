#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace locallexis::crypto {

constexpr const char* kSignDomainTagV2 = "locallexis-sig-v2";

// Builds the v2 signed message bytes:
//   "locallexis-sig-v2\n" + method + "\n" + target + "\n"
//   + timestamp + "\n" + nonce + "\n" + <32-byte digest>
//
// Pure C++ — host-testable. No Arduino types in the interface so this
// file can be compiled with plain g++ for the test/host/ harness.
std::vector<uint8_t> buildSignedMessageV2(
    const std::string& method,
    const std::string& target,
    const std::string& timestamp,
    const std::string& nonce,
    const uint8_t bodySha256[32]
);

}  // namespace locallexis::crypto
