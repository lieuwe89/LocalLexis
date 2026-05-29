#include "crypto/Base64.h"

#include <mbedtls/base64.h>

namespace locallexis::crypto {

String base64Encode(const uint8_t* data, size_t len) {
    size_t outLen = 0;
    mbedtls_base64_encode(nullptr, 0, &outLen, data, len);
    std::vector<uint8_t> out(outLen + 1, 0);
    if (mbedtls_base64_encode(out.data(), out.size(), &outLen, data, len) != 0) {
        return "";
    }
    if (outLen > 0 && out[outLen - 1] == '\0') {
        --outLen;
    }
    return String(reinterpret_cast<const char*>(out.data()), outLen);
}

bool base64Decode(const String& input, std::vector<uint8_t>& out) {
    size_t outLen = 0;
    const auto* src = reinterpret_cast<const uint8_t*>(input.c_str());
    mbedtls_base64_decode(nullptr, 0, &outLen, src, input.length());
    out.assign(outLen, 0);
    if (outLen == 0 && input.length() > 0) {
        return false;
    }
    if (mbedtls_base64_decode(out.data(), out.size(), &outLen, src, input.length()) != 0) {
        out.clear();
        return false;
    }
    out.resize(outLen);
    return true;
}

}  // namespace locallexis::crypto
