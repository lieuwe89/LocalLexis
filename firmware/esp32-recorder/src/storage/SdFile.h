#pragma once

#include <Arduino.h>
#include <FS.h>

#include "storage/FileLike.h"

namespace locallexis::storage {

// FileLike adapter around an Arduino fs::File. Real impl only — never
// compiled into the host test binary.
class SdFile : public FileLike {
public:
    explicit SdFile(File file);
    ~SdFile() override;

    size_t size() const override;
    bool seekToStart() override;
    size_t read(uint8_t* buf, size_t max) override;

private:
    File file_;
    size_t size_ = 0;
};

}  // namespace locallexis::storage
