#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace locallexis::provisioning {

constexpr const char* kProtocol = "locallexis.recorder.provision.v1";
constexpr uint8_t kFrameVersion = 1;
constexpr size_t kFrameHeaderBytes = 6;
constexpr size_t kFrameMaxBytes = 20;
constexpr size_t kFrameDataMaxBytes = kFrameMaxBytes - kFrameHeaderBytes;
constexpr size_t kMaxProvisioningPayloadBytes = 4096;

struct ProvisioningConfig {
    std::string hubUrl;
    std::string workspaceId;
    std::string deviceId;
    std::string workspaceKeySealedB64;
    std::string tlsSpkiB64;
    uint64_t lamportObserved = 0;
};

class FrameReassembler {
public:
    bool accept(const std::vector<uint8_t>& frame);
    bool complete() const;
    const std::string& payload() const;
    const std::string& error() const;
    void reset();

private:
    bool fail(const std::string& message);

    uint16_t total_ = 0;
    size_t received_ = 0;
    std::vector<std::string> chunks_;
    std::vector<bool> seen_;
    std::string payload_;
    std::string error_;
};

bool parseProvisioningJson(
    const std::string& json,
    ProvisioningConfig& out,
    std::string& error
);

}  // namespace locallexis::provisioning
