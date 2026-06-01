#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace locallexis::audio {

// bytesWritten()/capacityBytes() count TOTAL file bytes (44-byte header + PCM data).
class WavSink {
public:
    virtual ~WavSink() = default;
    virtual bool open() = 0;
    virtual bool write(const uint8_t* bytes, size_t len) = 0;
    virtual size_t bytesWritten() const = 0;
    virtual size_t capacityBytes() const = 0;
    virtual bool close() = 0;
    virtual void discard() = 0;
    virtual bool isMemoryBacked() const = 0;
    virtual std::vector<uint8_t> takeBytes() = 0;
};

}  // namespace locallexis::audio
