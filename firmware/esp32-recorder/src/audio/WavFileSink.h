#pragma once

#include <Arduino.h>
#include <memory>

#include "audio/WavSink.h"
#include "storage/SdQueue.h"
#include "storage/SdFileWriter.h"

namespace locallexis::audio {

class WavFileSink : public WavSink {
public:
    WavFileSink(locallexis::storage::SdQueue& queue,
                uint32_t sampleRate, uint16_t channels, size_t capacityBytes);
    bool open() override;
    bool write(const uint8_t* bytes, size_t len) override;
    size_t bytesWritten() const override;
    size_t capacityBytes() const override;
    bool close() override;
    void discard() override;
    bool isMemoryBacked() const override { return false; }
    std::vector<uint8_t> takeBytes() override { return {}; }

private:
    locallexis::storage::SdQueue& queue_;
    uint32_t sampleRate_;
    uint16_t channels_;
    size_t capacity_;
    std::unique_ptr<locallexis::storage::SdFileWriter> writer_;
    String finalPath_;
    size_t total_ = 0;   // header + data bytes appended (seeks during close don't count)
    bool open_ = false;
};

}  // namespace locallexis::audio
