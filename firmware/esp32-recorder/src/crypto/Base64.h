#pragma once

#include <Arduino.h>
#include <vector>

namespace locallexis::crypto {

String base64Encode(const uint8_t* data, size_t len);
bool base64Decode(const String& input, std::vector<uint8_t>& out);

}  // namespace locallexis::crypto
