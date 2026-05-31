#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>

#include "net/BodySource.h"
#include "storage/FileLike.h"

namespace locallexis::storage {

// BodySource that pulls bytes from any FileLike. Owns the FileLike so
// the file handle is closed when the source is destroyed.
class SdFileBodySource : public locallexis::net::BodySource {
public:
    explicit SdFileBodySource(std::unique_ptr<FileLike> file);

    size_t size() const override;
    bool rewind() override;
    size_t readChunk(uint8_t* buf, size_t max) override;

private:
    std::unique_ptr<FileLike> file_;
};

}  // namespace locallexis::storage
