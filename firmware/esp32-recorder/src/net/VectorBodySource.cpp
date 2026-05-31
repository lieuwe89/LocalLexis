#include "net/VectorBodySource.h"

#include <algorithm>
#include <cstring>

namespace locallexis::net {

VectorBodySource::VectorBodySource(const std::vector<uint8_t>& bytes)
    : bytes_(bytes) {}

bool VectorBodySource::rewind() {
    cursor_ = 0;
    return true;
}

size_t VectorBodySource::readChunk(uint8_t* buf, size_t max) {
    if (cursor_ >= bytes_.size() || max == 0) {
        return 0;
    }
    const size_t remaining = bytes_.size() - cursor_;
    const size_t take = std::min(remaining, max);
    std::memcpy(buf, bytes_.data() + cursor_, take);
    cursor_ += take;
    return take;
}

}  // namespace locallexis::net
