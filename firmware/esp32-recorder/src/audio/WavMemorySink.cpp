#include "audio/WavMemorySink.h"

#include "audio/WavWriter.h"

namespace locallexis::audio {

WavMemorySink::WavMemorySink(uint32_t sampleRate, uint16_t channels, size_t capacityBytes)
    : sampleRate_(sampleRate), channels_(channels), capacity_(capacityBytes) {}

bool WavMemorySink::open() {
    if (open_) return false;
    if (capacity_ < kWavHeaderBytes) return false;
    buf_.clear();
    buf_.reserve(capacity_ + 64);
    buf_.resize(kWavHeaderBytes);
    writeWavHeader(buf_.data(), sampleRate_, channels_, 0);
    open_ = true;
    closed_ = false;
    return true;
}

bool WavMemorySink::write(const uint8_t* bytes, size_t len) {
    if (!open_ || closed_) return false;
    if (buf_.size() + len > capacity_) return false;  // refuse; no partial write
    buf_.insert(buf_.end(), bytes, bytes + len);
    return true;
}

size_t WavMemorySink::bytesWritten() const { return buf_.size(); }
size_t WavMemorySink::capacityBytes() const { return capacity_; }

bool WavMemorySink::close() {
    if (!open_ || closed_) return false;
    const uint32_t dataBytes = uint32_t(buf_.size() - kWavHeaderBytes);
    patchWavSizes(buf_.data(), dataBytes);
    closed_ = true;
    return true;
}

void WavMemorySink::discard() {
    buf_.clear();
    buf_.shrink_to_fit();
    open_ = false;
    closed_ = false;
}

std::vector<uint8_t> WavMemorySink::takeBytes() {
    std::vector<uint8_t> out = std::move(buf_);
    buf_.clear();
    return out;
}

}  // namespace locallexis::audio
