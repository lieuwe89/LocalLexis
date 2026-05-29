#if defined(LOCALLEXIS_WOKWI_SIM)

#include "sim/WokwiProvisioning.h"

#include <ArduinoJson.h>
#include <WiFiClient.h>

#include "LocalLexisConfig.h"
#include "crypto/Base64.h"
#include "net/HubUrl.h"

namespace locallexis::sim {

namespace {
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

String readHttpResponse(WiFiClient& client, int& status) {
    String statusLine = client.readStringUntil('\n');
    statusLine.trim();
    status = parseStatusCode(statusLine);

    while (client.connected()) {
        String header = client.readStringUntil('\n');
        header.trim();
        if (header.isEmpty()) {
            break;
        }
    }

    String body;
    const unsigned long deadline = millis() + 10000;
    while (millis() < deadline) {
        while (client.available()) {
            body += static_cast<char>(client.read());
        }
        if (!client.connected()) {
            break;
        }
        delay(10);
    }

    return statusLine + "\n" + body;
}
}  // namespace

bool provisionWithPairingToken(
    const locallexis::crypto::DeviceKeys& keys,
    locallexis::provisioning::ProvisioningConfig& out,
    String& response
) {
    const String token(LOCALLEXIS_WOKWI_PAIRING_TOKEN);
    if (token.isEmpty() || token == "paste-one-time-pairing-token-here") {
        response = "LOCALLEXIS_WOKWI_PAIRING_TOKEN is empty";
        return false;
    }

    locallexis::net::HubUrl hub;
    std::string parseError;
    if (!locallexis::net::parseHubUrl(LOCALLEXIS_WOKWI_HUB_URL, hub, parseError)) {
        response = parseError.c_str();
        return false;
    }
    if (hub.https) {
        response = "Wokwi simulator pairing expects an http:// hub URL";
        return false;
    }

    JsonDocument requestDoc;
    requestDoc["token"] = token;
    requestDoc["device_pubkey_b64"] = locallexis::crypto::base64Encode(
        keys.publicKey,
        sizeof(keys.publicKey)
    );
    requestDoc["device_name"] = LOCALLEXIS_DEVICE_NAME;

    String body;
    serializeJson(requestDoc, body);

    WiFiClient client;
    if (!client.connect(hub.host.c_str(), hub.port)) {
        response = "failed to connect to Wokwi hub for pairing";
        return false;
    }

    const String path = locallexis::net::hubPath(hub, "/pair").c_str();
    client.print("POST ");
    client.print(path);
    client.print(" HTTP/1.1\r\nHost: ");
    client.print(hub.host.c_str());
    client.print(":");
    client.print(hub.port);
    client.print("\r\nConnection: close\r\nAccept: application/json\r\nContent-Type: application/json\r\nContent-Length: ");
    client.print(body.length());
    client.print("\r\n\r\n");
    client.print(body);

    int status = 0;
    response = readHttpResponse(client, status);
    client.stop();
    if (status != 200) {
        return false;
    }

    const int bodyStart = response.indexOf('\n');
    const String responseBody = bodyStart >= 0 ? response.substring(bodyStart + 1) : "";
    JsonDocument doc;
    const DeserializationError jsonError = deserializeJson(doc, responseBody);
    if (jsonError) {
        response = String("invalid pairing response JSON: ") + jsonError.c_str();
        return false;
    }

    locallexis::provisioning::ProvisioningConfig parsed;
    parsed.hubUrl = LOCALLEXIS_WOKWI_HUB_URL;
    parsed.deviceId = (doc["device_id"] | "");
    parsed.workspaceId = (doc["workspace_id"] | "");
    parsed.workspaceKeySealedB64 = (doc["workspace_key_sealed_b64"] | "");
    parsed.lamportObserved = doc["lamport_observed"] | 0;
    parsed.tlsSpkiB64 = LOCALLEXIS_WOKWI_TLS_SPKI_B64;

    if (parsed.deviceId.empty()
        || parsed.workspaceId.empty()
        || parsed.workspaceKeySealedB64.empty()) {
        response = "pairing response missing device_id/workspace_id/workspace_key_sealed_b64";
        return false;
    }

    out = parsed;
    return true;
}

}  // namespace locallexis::sim

#endif
