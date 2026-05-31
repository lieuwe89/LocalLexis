#include "storage/SdFileBodySource.h"

namespace locallexis::storage {

SdFileBodySource::SdFileBodySource(std::unique_ptr<FileLike> file)
    : file_(std::move(file)) {}

size_t SdFileBodySource::size() const {
    return file_ ? file_->size() : 0;
}

bool SdFileBodySource::rewind() {
    return file_ && file_->seekToStart();
}

size_t SdFileBodySource::readChunk(uint8_t* buf, size_t max) {
    if (!file_ || max == 0) return 0;
    return file_->read(buf, max);
}

}  // namespace locallexis::storage
