#include "audio/WavWriter.h"

#include <cstring>

namespace locallexis::audio {

namespace {
void putLe16(uint8_t* p, uint16_t v) {
    p[0] = uint8_t(v & 0xff);
    p[1] = uint8_t((v >> 8) & 0xff);
}
}  // namespace

void putLe32(uint8_t* p, uint32_t v) {
    p[0] = uint8_t(v & 0xff);
    p[1] = uint8_t((v >> 8) & 0xff);
    p[2] = uint8_t((v >> 16) & 0xff);
    p[3] = uint8_t((v >> 24) & 0xff);
}

uint32_t riffChunkSize(uint32_t dataBytes) {
    return 36u + dataBytes;
}

void writeWavHeader(uint8_t out[44], uint32_t sampleRate, uint16_t channels, uint32_t dataBytes) {
    const uint16_t bitsPerSample = 16;
    const uint16_t blockAlign = channels * (bitsPerSample / 8);
    const uint32_t byteRate = sampleRate * blockAlign;

    std::memcpy(out + 0, "RIFF", 4);
    putLe32(out + 4, riffChunkSize(dataBytes));
    std::memcpy(out + 8, "WAVE", 4);
    std::memcpy(out + 12, "fmt ", 4);
    putLe32(out + 16, 16);
    putLe16(out + 20, 1);            // PCM
    putLe16(out + 22, channels);
    putLe32(out + 24, sampleRate);
    putLe32(out + 28, byteRate);
    putLe16(out + 32, blockAlign);
    putLe16(out + 34, bitsPerSample);
    std::memcpy(out + 36, "data", 4);
    putLe32(out + 40, dataBytes);
}

void patchWavSizes(uint8_t header[44], uint32_t dataBytes) {
    putLe32(header + 4, riffChunkSize(dataBytes));
    putLe32(header + 40, dataBytes);
}

}  // namespace locallexis::audio
