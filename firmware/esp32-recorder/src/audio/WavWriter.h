#pragma once

#include <cstddef>
#include <cstdint>

namespace locallexis::audio {

constexpr size_t kWavHeaderBytes = 44;

void putLe32(uint8_t* p, uint32_t v);
uint32_t riffChunkSize(uint32_t dataBytes);
void writeWavHeader(uint8_t out[44], uint32_t sampleRate, uint16_t channels, uint32_t dataBytes);
void patchWavSizes(uint8_t header[44], uint32_t dataBytes);

}  // namespace locallexis::audio
