#include "crypto/SignedMessage.h"

#include <cstring>

namespace locallexis::crypto {

namespace {
void appendString(std::vector<uint8_t>& out, const std::string& s) {
    out.insert(out.end(), s.begin(), s.end());
}
}  // namespace

std::vector<uint8_t> buildSignedMessageV2(
    const std::string& method,
    const std::string& target,
    const std::string& timestamp,
    const std::string& nonce,
    const uint8_t bodySha256[32]
) {
    std::vector<uint8_t> out;
    const std::string tag = kSignDomainTagV2;
    out.reserve(tag.size() + method.size() + target.size()
                + timestamp.size() + nonce.size() + 32 + 5);
    appendString(out, tag);
    out.push_back('\n');
    appendString(out, method);
    out.push_back('\n');
    appendString(out, target);
    out.push_back('\n');
    appendString(out, timestamp);
    out.push_back('\n');
    appendString(out, nonce);
    out.push_back('\n');
    out.insert(out.end(), bodySha256, bodySha256 + 32);
    return out;
}

}  // namespace locallexis::crypto
