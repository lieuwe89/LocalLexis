#include <cassert>
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

#include "provisioning/ProvisioningProtocol.h"

using locallexis::provisioning::FrameReassembler;
using locallexis::provisioning::ProvisioningConfig;
using locallexis::provisioning::parseProvisioningJson;

static std::vector<uint8_t> frame(
    uint16_t seq,
    uint16_t total,
    const std::string& data
) {
    std::vector<uint8_t> out;
    out.push_back(1);
    out.push_back(static_cast<uint8_t>((seq >> 8) & 0xff));
    out.push_back(static_cast<uint8_t>(seq & 0xff));
    out.push_back(static_cast<uint8_t>((total >> 8) & 0xff));
    out.push_back(static_cast<uint8_t>(total & 0xff));
    out.push_back(static_cast<uint8_t>(data.size()));
    out.insert(out.end(), data.begin(), data.end());
    return out;
}

static void test_reassembles_out_of_order_frames() {
    FrameReassembler rx;

    assert(!rx.accept(frame(1, 3, "lo ")));
    assert(!rx.accept(frame(0, 3, "hel")));
    assert(rx.accept(frame(2, 3, "hub")));

    assert(rx.complete());
    assert(rx.payload() == "hello hub");
}

static void test_rejects_duplicate_frames() {
    FrameReassembler rx;

    assert(!rx.accept(frame(0, 2, "abc")));
    assert(!rx.accept(frame(0, 2, "abc")));
    assert(rx.error() == "duplicate provisioning frame");
}

static void test_rejects_inconsistent_total() {
    FrameReassembler rx;

    assert(!rx.accept(frame(0, 2, "abc")));
    assert(!rx.accept(frame(1, 3, "def")));
    assert(rx.error() == "provisioning frame total changed");
}

static void test_rejects_oversized_payload() {
    FrameReassembler rx;

    assert(!rx.accept(frame(0, 293, "abc")));
    assert(rx.error() == "provisioning payload too large");
}

static void test_parses_provisioning_json() {
    const std::string json =
        "{"
        "\"protocol\":\"locallexis.recorder.provision.v1\","
        "\"hub_url\":\"https://192.168.1.8:8765\","
        "\"workspace_id\":\"ws_abc\","
        "\"device_id\":\"dev-abc\","
        "\"workspace_key_sealed_b64\":\"SEALED=\","
        "\"lamport_observed\":12,"
        "\"tls_spki_b64\":\"PIN=\""
        "}";

    ProvisioningConfig cfg;
    std::string err;
    assert(parseProvisioningJson(json, cfg, err));
    assert(cfg.hubUrl == "https://192.168.1.8:8765");
    assert(cfg.workspaceId == "ws_abc");
    assert(cfg.deviceId == "dev-abc");
    assert(cfg.workspaceKeySealedB64 == "SEALED=");
    assert(cfg.lamportObserved == 12);
    assert(cfg.tlsSpkiB64 == "PIN=");
}

static void test_rejects_wrong_protocol() {
    ProvisioningConfig cfg;
    std::string err;

    assert(!parseProvisioningJson(
        "{\"protocol\":\"other\",\"hub_url\":\"https://h\"}",
        cfg,
        err
    ));
    assert(err == "unsupported provisioning protocol");
}

int main() {
    test_reassembles_out_of_order_frames();
    test_rejects_duplicate_frames();
    test_rejects_inconsistent_total();
    test_rejects_oversized_payload();
    test_parses_provisioning_json();
    test_rejects_wrong_protocol();
    std::cout << "provisioning protocol tests passed\n";
    return 0;
}
