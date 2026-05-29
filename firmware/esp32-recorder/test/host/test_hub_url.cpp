#include <cassert>
#include <iostream>
#include <string>

#include "net/HubUrl.h"

using locallexis::net::HubUrl;
using locallexis::net::hubPath;
using locallexis::net::parseHubUrl;

static void test_parses_default_ports() {
    HubUrl url;
    std::string error;

    assert(parseHubUrl("http://host.wokwi.internal", url, error));
    assert(!url.https);
    assert(url.host == "host.wokwi.internal");
    assert(url.port == 80);
    assert(url.basePath.empty());

    assert(parseHubUrl("https://192.168.1.50", url, error));
    assert(url.https);
    assert(url.host == "192.168.1.50");
    assert(url.port == 443);
}

static void test_parses_port_and_base_path() {
    HubUrl url;
    std::string error;

    assert(parseHubUrl("http://host.wokwi.internal:8765/locallexis/", url, error));
    assert(url.host == "host.wokwi.internal");
    assert(url.port == 8765);
    assert(url.basePath == "/locallexis");
    assert(hubPath(url, "/pair") == "/locallexis/pair");
    assert(hubPath(url, "/jobs/upload?filename=demo.wav")
        == "/locallexis/jobs/upload?filename=demo.wav");
}

static void test_rejects_bad_urls() {
    HubUrl url;
    std::string error;

    assert(!parseHubUrl("host.wokwi.internal:8765", url, error));
    assert(error == "hub URL must start with http:// or https://");

    assert(!parseHubUrl("http://host.wokwi.internal:nope", url, error));
    assert(error == "hub URL port is invalid");
}

int main() {
    test_parses_default_ports();
    test_parses_port_and_base_path();
    test_rejects_bad_urls();
    std::cout << "hub URL tests passed\n";
    return 0;
}
