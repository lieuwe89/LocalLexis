#pragma once

#include <Arduino.h>
#include <FS.h>

namespace locallexis::storage {

// Owns an open SD_MMC ".partial" file. Append, seek-patch, then commit (rename to
// final) or abort (delete partial). Closing without commit/abort aborts.
class SdFileWriter {
public:
    SdFileWriter(File file, String finalPath, String partialPath);
    ~SdFileWriter();

    size_t write(const uint8_t* buf, size_t len);
    bool seekTo(size_t pos);
    bool flush();
    bool commit();   // flush + close + rename partial -> final
    void abort();     // close + remove partial

    SdFileWriter(const SdFileWriter&) = delete;
    SdFileWriter& operator=(const SdFileWriter&) = delete;

private:
    File file_;
    String finalPath_;
    String partialPath_;
    bool finished_ = false;
};

}  // namespace locallexis::storage
