#pragma once

#include "audio/WavSink.h"

namespace locallexis::audio {

// Holds the whole WAV (header + PCM) in one std::vector. On the ESP32 a multi-MiB
// reserve necessarily lands in PSRAM (internal DRAM is far too small), so no custom
// allocator is needed. Pure C++ — host-testable.
class WavMemorySink : public WavSink {
public:
    WavMemorySink(uint32_t sampleRate, uint16_t channels, size_t capacityBytes);
    bool open() override;
    bool write(const uint8_t* bytes, size_t len) override;
    size_t bytesWritten() const override;
    size_t capacityBytes() const override;
    bool close() override;
    void discard() override;
    bool isMemoryBacked() const override { return true; }
    std::vector<uint8_t> takeBytes() override;

private:
    uint32_t sampleRate_;
    uint16_t channels_;
    size_t capacity_;
    std::vector<uint8_t> buf_;
    bool open_ = false;
    bool closed_ = false;
};

}  // namespace locallexis::audio
