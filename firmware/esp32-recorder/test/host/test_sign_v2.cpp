#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#include "crypto/SignedMessage.h"

using locallexis::crypto::buildSignedMessageV2;
using locallexis::crypto::kSignDomainTagV2;

namespace {

constexpr const char* kGoldenMsgHex =
    "6c6f63616c6c657869732d7369672d76320a504f53540a2f6a6f62732f75706c"
    "6f61643f66696c656e616d653d742e7761760a313730303030303030300a6162"
    "633132330a2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e730433"
    "62938b9824";

constexpr uint8_t kGoldenBodySha256[32] = {
    0x2c, 0xf2, 0x4d, 0xba, 0x5f, 0xb0, 0xa3, 0x0e,
    0x26, 0xe8, 0x3b, 0x2a, 0xc5, 0xb9, 0xe2, 0x9e,
    0x1b, 0x16, 0x1e, 0x5c, 0x1f, 0xa7, 0x42, 0x5e,
    0x73, 0x04, 0x33, 0x62, 0x93, 0x8b, 0x98, 0x24,
};

std::string toHex(const std::vector<uint8_t>& bytes) {
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(bytes.size() * 2);
    for (uint8_t b : bytes) {
        out.push_back(hex[(b >> 4) & 0x0f]);
        out.push_back(hex[b & 0x0f]);
    }
    return out;
}

void test_domain_tag_is_locked() {
    assert(std::string(kSignDomainTagV2) == "locallexis-sig-v2");
}

void test_golden_vector_bytes_exact() {
    const auto msg = buildSignedMessageV2(
        "POST",
        "/jobs/upload?filename=t.wav",
        "1700000000",
        "abc123",
        kGoldenBodySha256
    );
    assert(msg.size() == 101);
    assert(toHex(msg) == kGoldenMsgHex);
}

void test_empty_body_digest_well_known_layout() {
    constexpr uint8_t kEmptyDigest[32] = {
        0xe3, 0xb0, 0xc4, 0x42, 0x98, 0xfc, 0x1c, 0x14,
        0x9a, 0xfb, 0xf4, 0xc8, 0x99, 0x6f, 0xb9, 0x24,
        0x27, 0xae, 0x41, 0xe4, 0x64, 0x9b, 0x93, 0x4c,
        0xa4, 0x95, 0x99, 0x1b, 0x78, 0x52, 0xb8, 0x55,
    };
    const auto msg = buildSignedMessageV2(
        "GET", "/sync/snapshot", "1700000000", "n", kEmptyDigest
    );
    const std::string prefix = "locallexis-sig-v2\nGET\n/sync/snapshot\n1700000000\nn\n";
    assert(msg.size() == prefix.size() + 32);
    assert(std::memcmp(msg.data(), prefix.data(), prefix.size()) == 0);
    assert(std::memcmp(msg.data() + prefix.size(), kEmptyDigest, 32) == 0);
}

}  // namespace

int main() {
    test_domain_tag_is_locked();
    test_golden_vector_bytes_exact();
    test_empty_body_digest_well_known_layout();
    std::cout << "test_sign_v2: OK" << std::endl;
    return 0;
}
