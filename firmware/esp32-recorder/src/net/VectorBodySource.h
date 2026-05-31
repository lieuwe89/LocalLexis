#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "net/BodySource.h"

namespace locallexis::net {

// In-RAM BodySource backed by a std::vector. Holds a reference to the
// caller's buffer — caller must keep the buffer alive for the upload.
class VectorBodySource : public BodySource {
public:
    explicit VectorBodySource(const std::vector<uint8_t>& bytes);

    size_t size() const override { return bytes_.size(); }
    bool rewind() override;
    size_t readChunk(uint8_t* buf, size_t max) override;

private:
    const std::vector<uint8_t>& bytes_;
    size_t cursor_ = 0;
};

}  // namespace locallexis::net
