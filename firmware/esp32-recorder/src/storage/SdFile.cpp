#include "storage/SdFile.h"

namespace locallexis::storage {

SdFile::SdFile(File file) : file_(file) {
    size_ = file_ ? file_.size() : 0;
}

SdFile::~SdFile() {
    if (file_) {
        file_.close();
    }
}

size_t SdFile::size() const {
    return size_;
}

bool SdFile::seekToStart() {
    if (!file_) return false;
    return file_.seek(0);
}

size_t SdFile::read(uint8_t* buf, size_t max) {
    if (!file_ || max == 0) return 0;
    const int n = file_.read(buf, max);
    return n > 0 ? static_cast<size_t>(n) : 0;
}

}  // namespace locallexis::storage
