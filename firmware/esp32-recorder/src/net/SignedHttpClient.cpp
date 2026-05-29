#include "net/SignedHttpClient.h"

#include <algorithm>

#include <Client.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <mbedtls/sha256.h>
#include <mbedtls/x509_crt.h>
#include <time.h>

#include "crypto/Base64.h"
#include "net/HubUrl.h"

namespace locallexis::net {

namespace {
String unixTimestamp() {
    return String(static_cast<unsigned long>(time(nullptr)));
}

bool verifySpkiPin(
    WiFiClientSecure& client,
    const locallexis::provisioning::ProvisioningConfig& cfg,
    String& response
) {
    const String expectedB64(cfg.tlsSpkiB64.c_str());
    if (expectedB64.isEmpty()) {
        response = "HTTPS hub is missing tls_spki_b64; refusing unpinned TLS upload";
        return false;
    }

    std::vector<uint8_t> expected;
    if (!locallexis::crypto::base64Decode(expectedB64, expected)
        || expected.size() != 32) {
        response = "tls_spki_b64 is not a 32-byte base64 SHA-256 digest";
        return false;
    }

    const mbedtls_x509_crt* cert = client.getPeerCertificate();
    if (cert == nullptr || cert->pk_raw.p == nullptr || cert->pk_raw.len == 0) {
        response = "TLS peer certificate is unavailable for SPKI pinning";
        return false;
    }

    uint8_t digest[32];
    if (mbedtls_sha256_ret(cert->pk_raw.p, cert->pk_raw.len, digest, 0) != 0) {
        response = "failed to hash TLS peer SPKI";
        return false;
    }
    if (!std::equal(expected.begin(), expected.end(), digest)) {
        response = "TLS SPKI pin mismatch";
        return false;
    }
    return true;
}

int parseStatusCode(const String& statusLine) {
    const int firstSpace = statusLine.indexOf(' ');
    if (firstSpace < 0) {
        return 0;
    }
    const int secondSpace = statusLine.indexOf(' ', firstSpace + 1);
    const String code = secondSpace > firstSpace
        ? statusLine.substring(firstSpace + 1, secondSpace)
        : statusLine.substring(firstSpace + 1);
    return code.toInt();
}

bool writeUploadRequest(
    Client& client,
    const HubUrl& hub,
    const String& pathAndQuery,
    const locallexis::provisioning::ProvisioningConfig& cfg,
    const String& timestamp,
    const String& nonce,
    const String& signature,
    const std::vector<uint8_t>& wavBytes,
    String& response
) {
    client.print("POST ");
    client.print(pathAndQuery);
    client.print(" HTTP/1.1\r\nHost: ");
    client.print(hub.host.c_str());
    client.print(":");
    client.print(hub.port);
    client.print("\r\nConnection: close\r\nAccept: application/json\r\nContent-Type: audio/wav\r\nContent-Length: ");
    client.print(wavBytes.size());
    client.print("\r\nX-Device-Id: ");
    client.print(cfg.deviceId.c_str());
    client.print("\r\nX-Timestamp: ");
    client.print(timestamp);
    client.print("\r\nX-Nonce: ");
    client.print(nonce);
    client.print("\r\nX-Signature-B64: ");
    client.print(signature);
    client.print("\r\n\r\n");

    if (client.write(wavBytes.data(), wavBytes.size()) != wavBytes.size()) {
        response = "failed to write full upload body";
        return false;
    }

    String statusLine = client.readStringUntil('\n');
    statusLine.trim();
    const int status = parseStatusCode(statusLine);
    response = statusLine;

    const unsigned long deadline = millis() + 10000;
    while (millis() < deadline) {
        while (client.available()) {
            response += static_cast<char>(client.read());
        }
        if (!client.connected()) {
            break;
        }
        delay(10);
    }
    return status == 202;
}

void appendLe16(std::vector<uint8_t>& out, uint16_t value) {
    out.push_back(static_cast<uint8_t>(value & 0xff));
    out.push_back(static_cast<uint8_t>((value >> 8) & 0xff));
}

void appendLe32(std::vector<uint8_t>& out, uint32_t value) {
    out.push_back(static_cast<uint8_t>(value & 0xff));
    out.push_back(static_cast<uint8_t>((value >> 8) & 0xff));
    out.push_back(static_cast<uint8_t>((value >> 16) & 0xff));
    out.push_back(static_cast<uint8_t>((value >> 24) & 0xff));
}

void appendAscii(std::vector<uint8_t>& out, const char* text) {
    while (*text) {
        out.push_back(static_cast<uint8_t>(*text++));
    }
}
}  // namespace

bool SignedHttpClient::uploadWav(
    const locallexis::provisioning::ProvisioningConfig& cfg,
    const locallexis::crypto::DeviceKeys& keys,
    const String& filename,
    const std::vector<uint8_t>& wavBytes,
    String& response
) {
    HubUrl hub;
    std::string urlError;
    if (!parseHubUrl(cfg.hubUrl, hub, urlError)) {
        response = urlError.c_str();
        return false;
    }

    const String pathAndQuery = hubPath(
        hub,
        std::string("/jobs/upload?filename=") + filename.c_str()
    ).c_str();
    const String ts = unixTimestamp();
    const String nonce = locallexis::crypto::randomNonceHex();
    const String sig = locallexis::crypto::signRequestB64(
        keys,
        "POST",
        pathAndQuery,
        ts,
        nonce,
        wavBytes.data(),
        wavBytes.size()
    );

    if (hub.https) {
        WiFiClientSecure secureClient;
        secureClient.setInsecure();
        if (!secureClient.connect(hub.host.c_str(), hub.port)) {
            response = "failed to connect to HTTPS hub";
            return false;
        }
        if (!verifySpkiPin(secureClient, cfg, response)) {
            secureClient.stop();
            return false;
        }
        const bool ok = writeUploadRequest(
            secureClient,
            hub,
            pathAndQuery,
            cfg,
            ts,
            nonce,
            sig,
            wavBytes,
            response
        );
        secureClient.stop();
        return ok;
    }

    WiFiClient plainClient;
    if (!plainClient.connect(hub.host.c_str(), hub.port)) {
        response = "failed to connect to HTTP hub";
        return false;
    }
    const bool ok = writeUploadRequest(
        plainClient,
        hub,
        pathAndQuery,
        cfg,
        ts,
        nonce,
        sig,
        wavBytes,
        response
    );
    plainClient.stop();
    return ok;
}

std::vector<uint8_t> makeSilenceWav(uint32_t sampleRate, uint16_t seconds) {
    const uint16_t channels = 1;
    const uint16_t bitsPerSample = 16;
    const uint32_t dataBytes = sampleRate * seconds * channels * (bitsPerSample / 8);
    std::vector<uint8_t> out;
    out.reserve(44 + dataBytes);

    appendAscii(out, "RIFF");
    appendLe32(out, 36 + dataBytes);
    appendAscii(out, "WAVE");
    appendAscii(out, "fmt ");
    appendLe32(out, 16);
    appendLe16(out, 1);
    appendLe16(out, channels);
    appendLe32(out, sampleRate);
    appendLe32(out, sampleRate * channels * (bitsPerSample / 8));
    appendLe16(out, channels * (bitsPerSample / 8));
    appendLe16(out, bitsPerSample);
    appendAscii(out, "data");
    appendLe32(out, dataBytes);
    out.insert(out.end(), dataBytes, 0);
    return out;
}

}  // namespace locallexis::net
