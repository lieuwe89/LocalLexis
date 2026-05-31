#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <numeric>
#include <memory>
#include <vector>

#include "net/VectorBodySource.h"
#include "storage/FileLike.h"
#include "storage/SdFileBodySource.h"

using locallexis::net::VectorBodySource;

namespace {

class FakeFileLike : public locallexis::storage::FileLike {
public:
    explicit FakeFileLike(std::vector<uint8_t> bytes) : bytes_(std::move(bytes)) {}
    size_t size() const override { return bytes_.size(); }
    bool seekToStart() override { cursor_ = 0; return true; }
    size_t read(uint8_t* buf, size_t max) override {
        if (cursor_ >= bytes_.size() || max == 0) return 0;
        const size_t take = std::min(max, bytes_.size() - cursor_);
        std::memcpy(buf, bytes_.data() + cursor_, take);
        cursor_ += take;
        return take;
    }
private:
    std::vector<uint8_t> bytes_;
    size_t cursor_ = 0;
};

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

void test_sd_file_body_source_round_trip() {
    std::vector<uint8_t> bytes(513);
    for (size_t i = 0; i < bytes.size(); ++i) {
        bytes[i] = static_cast<uint8_t>((i * 7) & 0xff);
    }
    auto fake = std::make_unique<FakeFileLike>(bytes);
    locallexis::storage::SdFileBodySource src(std::move(fake));
    assert(src.size() == bytes.size());

    std::vector<uint8_t> got;
    std::vector<uint8_t> buf(64);
    while (true) {
        const size_t n = src.readChunk(buf.data(), buf.size());
        if (n == 0) break;
        got.insert(got.end(), buf.begin(), buf.begin() + n);
    }
    assert(got == bytes);
}

void test_sd_file_body_source_rewind() {
    std::vector<uint8_t> bytes = {10, 20, 30, 40};
    auto fake = std::make_unique<FakeFileLike>(bytes);
    locallexis::storage::SdFileBodySource src(std::move(fake));
    uint8_t buf[2];
    src.readChunk(buf, 2);
    assert(src.rewind());
    std::vector<uint8_t> got;
    uint8_t buf2[8];
    const size_t n = src.readChunk(buf2, sizeof(buf2));
    got.assign(buf2, buf2 + n);
    assert(got == bytes);
}

}  // namespace

int main() {
    test_round_trip_full_buffer();
    test_round_trip_chunked_matches_whole();
    test_rewind_replays_from_start();
    test_empty_body();
    test_zero_max_returns_zero_without_advancing();
    test_sd_file_body_source_round_trip();
    test_sd_file_body_source_rewind();
    std::cout << "test_body_source: OK" << std::endl;
    return 0;
}
