#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <numeric>
#include <vector>

#include "net/VectorBodySource.h"

using locallexis::net::VectorBodySource;

namespace {

std::vector<uint8_t> drain(VectorBodySource& src, size_t chunkSize) {
    std::vector<uint8_t> out;
    out.reserve(src.size());
    std::vector<uint8_t> buf(chunkSize);
    while (true) {
        const size_t n = src.readChunk(buf.data(), buf.size());
        if (n == 0) break;
        out.insert(out.end(), buf.begin(), buf.begin() + n);
    }
    return out;
}

void test_round_trip_full_buffer() {
    std::vector<uint8_t> bytes(257);
    std::iota(bytes.begin(), bytes.end(), 0);
    VectorBodySource src(bytes);
    assert(src.size() == bytes.size());
    auto got = drain(src, 4096);
    assert(got == bytes);
}

void test_round_trip_chunked_matches_whole() {
    std::vector<uint8_t> bytes(1000);
    for (size_t i = 0; i < bytes.size(); ++i) {
        bytes[i] = static_cast<uint8_t>(i & 0xff);
    }
    VectorBodySource a(bytes);
    auto whole = drain(a, bytes.size());
    assert(whole == bytes);

    VectorBodySource b(bytes);
    auto chunked = drain(b, 37);  // odd chunk size to stress boundary
    assert(chunked == bytes);
}

void test_rewind_replays_from_start() {
    std::vector<uint8_t> bytes = {1, 2, 3, 4, 5};
    VectorBodySource src(bytes);
    drain(src, 2);
    assert(src.rewind());
    auto second = drain(src, 2);
    assert(second == bytes);
}

void test_empty_body() {
    std::vector<uint8_t> bytes;
    VectorBodySource src(bytes);
    assert(src.size() == 0);
    uint8_t buf[16];
    assert(src.readChunk(buf, sizeof(buf)) == 0);
}

void test_zero_max_returns_zero_without_advancing() {
    std::vector<uint8_t> bytes = {9, 8, 7};
    VectorBodySource src(bytes);
    uint8_t buf[8];
    assert(src.readChunk(buf, 0) == 0);
    auto rest = drain(src, 8);
    assert(rest == bytes);
}

}  // namespace

int main() {
    test_round_trip_full_buffer();
    test_round_trip_chunked_matches_whole();
    test_rewind_replays_from_start();
    test_empty_body();
    test_zero_max_returns_zero_without_advancing();
    std::cout << "test_body_source: OK" << std::endl;
    return 0;
}
