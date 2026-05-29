#pragma once

#include <cstdint>
#include <string>

namespace locallexis::net {

struct HubUrl {
    bool https = false;
    std::string host;
    uint16_t port = 0;
    std::string basePath;
};

bool parseHubUrl(const std::string& hubUrl, HubUrl& out, std::string& error);
std::string hubPath(const HubUrl& hub, const std::string& absolutePathAndQuery);

}  // namespace locallexis::net
