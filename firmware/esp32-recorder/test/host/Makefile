# Host (laptop) build of the firmware's pure-C++ modules. Each test binary
# links only the source files it actually needs so Arduino-only modules
# never enter the compile graph.
#
# Usage:
#   make            # build + run every test
#   make test_sign_v2 && ./test_sign_v2
#   make clean
#
# This sits beside platformio.ini's ESP32 builds — it does not feed into
# `pio run` and `pio run` does not feed into it.

CXX      ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -Wpedantic -O2 -I../../src -I../../include

TESTS = test_provisioning_protocol test_hub_url test_sign_v2 test_body_source

.PHONY: all run clean
all: run

run: $(TESTS)
	@set -e; for t in $(TESTS); do echo "==> $$t"; ./$$t; done

test_provisioning_protocol: test_provisioning_protocol.cpp ../../src/provisioning/ProvisioningProtocol.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^

test_hub_url: test_hub_url.cpp ../../src/net/HubUrl.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^

test_sign_v2: test_sign_v2.cpp ../../src/crypto/SignedMessage.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^

test_body_source: test_body_source.cpp ../../src/net/VectorBodySource.cpp ../../src/storage/SdFileBodySource.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^

clean:
	rm -f $(TESTS)
