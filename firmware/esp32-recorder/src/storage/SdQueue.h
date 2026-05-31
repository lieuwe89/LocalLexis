#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include <memory>
#include <vector>

#include "storage/SdFileBodySource.h"

namespace locallexis::storage {

struct QueueStats {
    uint32_t pending = 0;
    uint64_t totalBytes = 0;
    uint64_t usedBytes = 0;
};

class SdQueue {
public:
    bool begin(int clkPin, int cmdPin, int d0Pin,
               const char* queueDir = "/queue");
    bool ready() const { return ready_; }
    bool enqueue(const std::vector<uint8_t>& wavBytes, String* outPath = nullptr);

    // Returns the path of the oldest queued .wav without reading its bytes.
    bool peekOldestPath(String& outPath);

    // Opens a streaming reader for ``path`` (must be inside the queue dir).
    // Returns nullptr if the file cannot be opened.
    std::unique_ptr<SdFileBodySource> openReader(const String& path);

    bool removeFile(const String& path);
    QueueStats stats();

private:
    bool ready_ = false;
    String queueDir_;
    Preferences prefs_;
    uint64_t nextN_ = 1;

    bool sweepPartials();
    String nextFilenameStem();
};

}  // namespace locallexis::storage
