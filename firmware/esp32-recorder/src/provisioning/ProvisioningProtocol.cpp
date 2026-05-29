#include "provisioning/ProvisioningProtocol.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>

#if __has_include(<ArduinoJson.h>)
#include <ArduinoJson.h>
#define LOCALLEXIS_HAS_ARDUINOJSON 1
#endif

namespace locallexis::provisioning {

bool FrameReassembler::accept(const std::vector<uint8_t>& frame) {
    if (!error_.empty() || complete()) {
        return false;
    }
    if (frame.size() < kFrameHeaderBytes) {
        return fail("provisioning frame too short");
    }
    if (frame.size() > kFrameMaxBytes) {
        return fail("provisioning frame too large");
    }
    if (frame[0] != kFrameVersion) {
        return fail("unsupported provisioning frame version");
    }
    const uint16_t seq = (static_cast<uint16_t>(frame[1]) << 8) | frame[2];
    const uint16_t total = (static_cast<uint16_t>(frame[3]) << 8) | frame[4];
    const size_t len = frame[5];
    if (total == 0) {
        return fail("provisioning frame total is zero");
    }
    if (static_cast<size_t>(total) * kFrameDataMaxBytes > kMaxProvisioningPayloadBytes) {
        return fail("provisioning payload too large");
    }
    if (len > kFrameDataMaxBytes || frame.size() != kFrameHeaderBytes + len) {
        return fail("provisioning frame length mismatch");
    }
    if (seq >= total) {
        return fail("provisioning frame sequence out of range");
    }
    if (total_ == 0) {
        total_ = total;
        chunks_.assign(total_, "");
        seen_.assign(total_, false);
    } else if (total != total_) {
        return fail("provisioning frame total changed");
    }
    if (seen_[seq]) {
        return fail("duplicate provisioning frame");
    }

    chunks_[seq] = std::string(
        reinterpret_cast<const char*>(frame.data() + kFrameHeaderBytes),
        len
    );
    seen_[seq] = true;
    received_ += 1;

    if (received_ == total_) {
        payload_.clear();
        for (const auto& chunk : chunks_) {
            payload_ += chunk;
        }
        return true;
    }
    return false;
}

bool FrameReassembler::complete() const {
    return total_ > 0 && received_ == total_ && error_.empty();
}

const std::string& FrameReassembler::payload() const {
    return payload_;
}

const std::string& FrameReassembler::error() const {
    return error_;
}

void FrameReassembler::reset() {
    total_ = 0;
    received_ = 0;
    chunks_.clear();
    seen_.clear();
    payload_.clear();
    error_.clear();
}

bool FrameReassembler::fail(const std::string& message) {
    error_ = message;
    return false;
}

namespace {

std::string jsonStringValue(
    const std::string& json,
    const std::string& key
) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) {
        return "";
    }
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) {
        return "";
    }
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos) {
        return "";
    }

    std::string out;
    bool escaped = false;
    for (size_t i = pos + 1; i < json.size(); ++i) {
        const char ch = json[i];
        if (escaped) {
            switch (ch) {
                case '"':
                case '\\':
                case '/':
                    out.push_back(ch);
                    break;
                case 'n':
                    out.push_back('\n');
                    break;
                case 'r':
                    out.push_back('\r');
                    break;
                case 't':
                    out.push_back('\t');
                    break;
                default:
                    out.push_back(ch);
                    break;
            }
            escaped = false;
            continue;
        }
        if (ch == '\\') {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            return out;
        }
        out.push_back(ch);
    }
    return "";
}

bool jsonUInt64Value(
    const std::string& json,
    const std::string& key,
    uint64_t& out
) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) {
        return false;
    }
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) {
        return false;
    }
    ++pos;
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) {
        ++pos;
    }
    if (pos >= json.size() || !std::isdigit(static_cast<unsigned char>(json[pos]))) {
        return false;
    }
    char* end = nullptr;
    out = std::strtoull(json.c_str() + pos, &end, 10);
    return end != json.c_str() + pos;
}

bool requireString(
    const std::string& value,
    const char* field,
    std::string& error
) {
    if (!value.empty()) {
        return true;
    }
    error = std::string("missing provisioning field: ") + field;
    return false;
}

}  // namespace

bool parseProvisioningJson(
    const std::string& json,
    ProvisioningConfig& out,
    std::string& error
) {
    error.clear();
    ProvisioningConfig parsed;

#if LOCALLEXIS_HAS_ARDUINOJSON
    JsonDocument doc;
    const DeserializationError jsonError = deserializeJson(doc, json);
    if (jsonError) {
        error = std::string("invalid provisioning JSON: ") + jsonError.c_str();
        return false;
    }

    const char* protocol = doc["protocol"] | "";
    if (std::string(protocol) != kProtocol) {
        error = "unsupported provisioning protocol";
        return false;
    }

    parsed.hubUrl = (doc["hub_url"] | "");
    parsed.workspaceId = (doc["workspace_id"] | "");
    parsed.deviceId = (doc["device_id"] | "");
    parsed.workspaceKeySealedB64 = (doc["workspace_key_sealed_b64"] | "");
    parsed.tlsSpkiB64 = (doc["tls_spki_b64"] | "");
    parsed.lamportObserved = doc["lamport_observed"] | 0;
#else
    const std::string protocol = jsonStringValue(json, "protocol");
    if (protocol != kProtocol) {
        error = "unsupported provisioning protocol";
        return false;
    }
    parsed.hubUrl = jsonStringValue(json, "hub_url");
    parsed.workspaceId = jsonStringValue(json, "workspace_id");
    parsed.deviceId = jsonStringValue(json, "device_id");
    parsed.workspaceKeySealedB64 = jsonStringValue(
        json,
        "workspace_key_sealed_b64"
    );
    parsed.tlsSpkiB64 = jsonStringValue(json, "tls_spki_b64");
    jsonUInt64Value(json, "lamport_observed", parsed.lamportObserved);
#endif

    if (!requireString(parsed.hubUrl, "hub_url", error)
        || !requireString(parsed.workspaceId, "workspace_id", error)
        || !requireString(parsed.deviceId, "device_id", error)
        || !requireString(
            parsed.workspaceKeySealedB64,
            "workspace_key_sealed_b64",
            error
        )) {
        return false;
    }
    out = parsed;
    return true;
}

}  // namespace locallexis::provisioning
