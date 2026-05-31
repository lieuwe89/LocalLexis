#pragma once

#include <cstddef>
#include <cstdint>

namespace locallexis::storage {

// Three-method seam that both the real Arduino SD_MMC File and a host-
// side fake implement. Lets SdFileBodySource stay pure C++ so the
// chunked-read logic can be exercised on a laptop without an SD card.
class FileLike {
public:
    virtual ~FileLike() = default;
    virtual size_t size() const = 0;
    virtual bool seekToStart() = 0;
    virtual size_t read(uint8_t* buf, size_t max) = 0;
};

}  // namespace locallexis::storage
