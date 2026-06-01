#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <vector>

#include "audio/WavWriter.h"
#include "audio/WavMemorySink.h"

using namespace locallexis::audio;

namespace {

uint32_t le32At(const uint8_t* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}

// Canonical 44-byte header for 16 kHz mono 16-bit PCM, dataBytes = 0.
std::vector<uint8_t> canonicalZero() {
    std::vector<uint8_t> h = {
        'R','I','F','F', 36,0,0,0, 'W','A','V','E',
        'f','m','t',' ', 16,0,0,0, 1,0, 1,0,
        0x80,0x3e,0,0,            // sampleRate 16000
        0,0x7d,0,0,               // byteRate 32000
        2,0, 16,0,
        'd','a','t','a', 0,0,0,0,
    };
    return h;
}

void test_header_zero_samples_matches_canonical_bytes() {
    uint8_t out[kWavHeaderBytes];
    writeWavHeader(out, 16000, 1, 0);
    auto want = canonicalZero();
    assert(want.size() == kWavHeaderBytes);
    assert(std::memcmp(out, want.data(), kWavHeaderBytes) == 0);
}

void test_header_patch_updates_riff_and_data_sizes() {
    uint8_t h[kWavHeaderBytes];
    writeWavHeader(h, 16000, 1, 0);
    const uint32_t N = 12345;                 // samples
    const uint32_t dataBytes = 2 * N;         // mono 16-bit
    patchWavSizes(h, dataBytes);
    assert(le32At(h + 4) == 36 + dataBytes);  // RIFF size
    assert(le32At(h + 40) == dataBytes);      // data size
}

void test_header_patch_round_trip_one_sample() {
    uint8_t h[kWavHeaderBytes];
    writeWavHeader(h, 16000, 1, 0);
    patchWavSizes(h, 2);                       // 1 sample
    assert(le32At(h + 4) == 38);
    assert(le32At(h + 40) == 2);
}

void test_header_patch_round_trip_100k_samples() {
    uint8_t h[kWavHeaderBytes];
    writeWavHeader(h, 16000, 1, 0);
    patchWavSizes(h, 2 * 100000);
    assert(le32At(h + 4) == 36 + 200000);
    assert(le32At(h + 40) == 200000);
}

void test_wav_memory_sink_round_trip() {
    WavMemorySink sink(16000, 1, /*capacityBytes=*/4096);
    assert(sink.open());
    assert(sink.isMemoryBacked());
    std::vector<uint8_t> pcm(200, 0xAB);
    assert(sink.write(pcm.data(), pcm.size()));
    assert(sink.bytesWritten() == kWavHeaderBytes + 200);
    assert(sink.close());
    auto bytes = sink.takeBytes();
    assert(bytes.size() == kWavHeaderBytes + 200);
    // header was patched: data size == 200
    const uint8_t* h = bytes.data();
    const uint32_t dataSize = uint32_t(h[40]) | (uint32_t(h[41]) << 8) | (uint32_t(h[42]) << 16) | (uint32_t(h[43]) << 24);
    assert(dataSize == 200);
}

void test_wav_memory_sink_respects_capacity() {
    // capacity is TOTAL file bytes; header (44) + room for 56 data bytes = 100.
    WavMemorySink sink(16000, 1, /*capacityBytes=*/100);
    assert(sink.open());
    std::vector<uint8_t> ok(56, 1);
    assert(sink.write(ok.data(), ok.size()));      // fills exactly to capacity
    assert(sink.bytesWritten() == 100);
    std::vector<uint8_t> over(1, 1);
    assert(!sink.write(over.data(), over.size()));  // refuses; no partial write
    assert(sink.bytesWritten() == 100);             // unchanged (clamped)
}

void test_wav_memory_sink_discard_frees() {
    WavMemorySink sink(16000, 1, 4096);
    assert(sink.open());
    uint8_t b[8] = {0};
    assert(sink.write(b, sizeof(b)));
    sink.discard();
    assert(sink.takeBytes().empty());
}

}  // namespace

int main() {
    test_header_zero_samples_matches_canonical_bytes();
    test_header_patch_updates_riff_and_data_sizes();
    test_header_patch_round_trip_one_sample();
    test_header_patch_round_trip_100k_samples();
    test_wav_memory_sink_round_trip();
    test_wav_memory_sink_respects_capacity();
    test_wav_memory_sink_discard_frees();
    std::cout << "test_wav_writer: OK" << std::endl;
    return 0;
}
