#include "storage/SdFileWriter.h"

#include <SD_MMC.h>

namespace locallexis::storage {

SdFileWriter::SdFileWriter(File file, String finalPath, String partialPath)
    : file_(file), finalPath_(std::move(finalPath)), partialPath_(std::move(partialPath)) {}

SdFileWriter::~SdFileWriter() {
    if (!finished_) {
        abort();
    }
}

size_t SdFileWriter::write(const uint8_t* buf, size_t len) {
    if (!file_) return 0;
    return file_.write(buf, len);
}

bool SdFileWriter::seekTo(size_t pos) {
    if (!file_) return false;
    return file_.seek(pos);
}

bool SdFileWriter::flush() {
    if (!file_) return false;
    file_.flush();
    return true;
}

bool SdFileWriter::commit() {
    if (finished_) return false;
    if (file_) {
        file_.flush();
        file_.close();
    }
    finished_ = true;
    if (!SD_MMC.rename(partialPath_, finalPath_)) {
        SD_MMC.remove(partialPath_);
        return false;
    }
    return true;
}

void SdFileWriter::abort() {
    if (finished_) return;
    if (file_) {
        file_.close();
    }
    finished_ = true;
    SD_MMC.remove(partialPath_);
}

}  // namespace locallexis::storage
