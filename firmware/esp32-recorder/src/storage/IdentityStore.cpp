#include "storage/IdentityStore.h"

namespace locallexis::storage {

namespace {
constexpr const char* kNamespace = "locallexis";
constexpr const char* kPrivateKey = "priv_key";
constexpr const char* kHubUrl = "hub_url";
constexpr const char* kWorkspaceId = "ws_id";
constexpr const char* kDeviceId = "dev_id";
constexpr const char* kSealedKey = "sealed_w";
constexpr const char* kTlsSpki = "tls_spki";
constexpr const char* kLamport = "lamport";
}

bool IdentityStore::begin() {
    return prefs_.begin(kNamespace, false);
}

bool IdentityStore::load(DeviceIdentity& out) {
    const size_t keyLen = prefs_.getBytesLength(kPrivateKey);
    if (keyLen == 32) {
        prefs_.getBytes(kPrivateKey, out.keys.privateKey, 32);
    } else {
        locallexis::crypto::generatePrivateKey(out.keys.privateKey);
        savePrivateKey(out.keys.privateKey);
    }
    locallexis::crypto::deriveKeys(out.keys);

    out.provisioning.hubUrl = prefs_.getString(kHubUrl, "").c_str();
    out.provisioning.workspaceId = prefs_.getString(kWorkspaceId, "").c_str();
    out.provisioning.deviceId = prefs_.getString(kDeviceId, "").c_str();
    out.provisioning.workspaceKeySealedB64 = prefs_.getString(kSealedKey, "").c_str();
    out.provisioning.tlsSpkiB64 = prefs_.getString(kTlsSpki, "").c_str();
    out.provisioning.lamportObserved = prefs_.getULong64(kLamport, 0);
    out.provisioned = !out.provisioning.hubUrl.empty()
        && !out.provisioning.deviceId.empty()
        && !out.provisioning.workspaceKeySealedB64.empty();
    return true;
}

bool IdentityStore::savePrivateKey(const uint8_t privateKey[32]) {
    return prefs_.putBytes(kPrivateKey, privateKey, 32) == 32;
}

bool IdentityStore::saveProvisioning(
    const locallexis::provisioning::ProvisioningConfig& cfg
) {
    prefs_.putString(kHubUrl, cfg.hubUrl.c_str());
    prefs_.putString(kWorkspaceId, cfg.workspaceId.c_str());
    prefs_.putString(kDeviceId, cfg.deviceId.c_str());
    prefs_.putString(kSealedKey, cfg.workspaceKeySealedB64.c_str());
    prefs_.putString(kTlsSpki, cfg.tlsSpkiB64.c_str());
    prefs_.putULong64(kLamport, cfg.lamportObserved);
    return true;
}

void IdentityStore::clear() {
    prefs_.clear();
}

}  // namespace locallexis::storage
