#include "net/HubUrl.h"

#include <cstdlib>

namespace locallexis::net {

namespace {
bool startsWith(const std::string& value, const char* prefix) {
    const std::string p(prefix);
    return value.rfind(p, 0) == 0;
}

void trimTrailingSlashes(std::string& value) {
    while (!value.empty() && value.back() == '/') {
        value.pop_back();
    }
}
}  // namespace

bool parseHubUrl(const std::string& hubUrl, HubUrl& out, std::string& error) {
    error.clear();
    HubUrl parsed;
    std::string rest;

    if (startsWith(hubUrl, "https://")) {
        parsed.https = true;
        parsed.port = 443;
        rest = hubUrl.substr(8);
    } else if (startsWith(hubUrl, "http://")) {
        parsed.https = false;
        parsed.port = 80;
        rest = hubUrl.substr(7);
    } else {
        error = "hub URL must start with http:// or https://";
        return false;
    }

    const size_t slash = rest.find('/');
    const std::string authority = slash == std::string::npos
        ? rest
        : rest.substr(0, slash);
    parsed.basePath = slash == std::string::npos ? "" : rest.substr(slash);
    trimTrailingSlashes(parsed.basePath);

    const size_t colon = authority.rfind(':');
    if (colon != std::string::npos) {
        parsed.host = authority.substr(0, colon);
        const std::string portText = authority.substr(colon + 1);
        char* end = nullptr;
        const long port = std::strtol(portText.c_str(), &end, 10);
        if (portText.empty() || *end != '\0' || port <= 0 || port > 65535) {
            error = "hub URL port is invalid";
            return false;
        }
        parsed.port = static_cast<uint16_t>(port);
    } else {
        parsed.host = authority;
    }

    if (parsed.host.empty()) {
        error = "hub URL host is empty";
        return false;
    }

    out = parsed;
    return true;
}

std::string hubPath(const HubUrl& hub, const std::string& absolutePathAndQuery) {
    if (absolutePathAndQuery.empty()) {
        return hub.basePath.empty() ? "/" : hub.basePath;
    }
    if (absolutePathAndQuery.front() == '/') {
        return hub.basePath + absolutePathAndQuery;
    }
    return hub.basePath + "/" + absolutePathAndQuery;
}

}  // namespace locallexis::net
