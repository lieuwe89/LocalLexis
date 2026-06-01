#include "audio/WavFileSink.h"

#include "audio/WavWriter.h"

namespace locallexis::audio {

WavFileSink::WavFileSink(locallexis::storage::SdQueue& queue,
                         uint32_t sampleRate, uint16_t channels, size_t capacityBytes)
    : queue_(queue), sampleRate_(sampleRate), channels_(channels), capacity_(capacityBytes) {}

bool WavFileSink::open() {
    if (open_) return false;
    writer_ = queue_.openWriter(finalPath_);
    if (!writer_) return false;

    uint8_t header[kWavHeaderBytes];
    writeWavHeader(header, sampleRate_, channels_, 0);
    if (writer_->write(header, kWavHeaderBytes) != kWavHeaderBytes) {
        writer_->abort();
        writer_.reset();
        return false;
    }
    total_ = kWavHeaderBytes;
    open_ = true;
    return true;
}

bool WavFileSink::write(const uint8_t* bytes, size_t len) {
    if (!open_ || !writer_) return false;
    if (total_ + len > capacity_) return false;          // cap-hit; no partial write
    if (writer_->write(bytes, len) != len) return false;  // SD write failure
    total_ += len;
    return true;
}

size_t WavFileSink::bytesWritten() const { return total_; }
size_t WavFileSink::capacityBytes() const { return capacity_; }

bool WavFileSink::close() {
    if (!open_ || !writer_) return false;
    open_ = false;
    const uint32_t dataBytes = uint32_t(total_ - kWavHeaderBytes);

    uint8_t sizeField[4];
    putLe32(sizeField, riffChunkSize(dataBytes));
    bool ok = writer_->seekTo(4) && writer_->write(sizeField, 4) == 4;
    putLe32(sizeField, dataBytes);
    ok = ok && writer_->seekTo(40) && writer_->write(sizeField, 4) == 4;
    ok = ok && writer_->flush();

    if (!ok) {
        writer_->abort();
        writer_.reset();
        return false;
    }
    const bool committed = writer_->commit();   // rename .partial -> .wav
    writer_.reset();
    return committed;
}

void WavFileSink::discard() {
    if (writer_) {
        writer_->abort();
        writer_.reset();
    }
    open_ = false;
    total_ = 0;
}

}  // namespace locallexis::audio
