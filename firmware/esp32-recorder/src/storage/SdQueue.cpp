#include "storage/SdQueue.h"

#include <SD_MMC.h>
#include "storage/SdFile.h"

namespace locallexis::storage {

namespace {
constexpr const char* kPrefsNs = "ll_sdq";
constexpr const char* kPrefsKey = "next";
constexpr uint64_t kMaxFileBytes = 4ULL * 1024 * 1024;
constexpr float kUsageHardCap = 0.95f;

String joinPath(const String& dir, const String& name) {
    if (dir.endsWith("/")) {
        return dir + name;
    }
    return dir + "/" + name;
}

String fullPathOf(const String& dir, const String& name) {
    return name.startsWith("/") ? name : joinPath(dir, name);
}
}  // namespace

bool SdQueue::begin(int clkPin, int cmdPin, int d0Pin,
                    const char* queueDir) {
    ready_ = false;
    queueDir_ = queueDir;

    if (!SD_MMC.setPins(clkPin, cmdPin, d0Pin)) {
        Serial.println("SD_MMC.setPins failed; recordings will not be buffered to card.");
        return false;
    }
    // 1-bit SDMMC mode matches the Waveshare ESP32-S3-ePaper-1.54 wiring.
    if (!SD_MMC.begin("/sdcard", true)) {
        Serial.println("SD mount failed; recordings will not be buffered to card.");
        return false;
    }
    if (SD_MMC.cardType() == CARD_NONE) {
        Serial.println("SD slot empty; recordings will not be buffered to card.");
        SD_MMC.end();
        return false;
    }

    if (!SD_MMC.exists(queueDir_) && !SD_MMC.mkdir(queueDir_)) {
        Serial.printf("Failed to create queue dir %s\n", queueDir_.c_str());
        SD_MMC.end();
        return false;
    }

    if (!prefs_.begin(kPrefsNs, false)) {
        Serial.println("SD queue NVS open failed");
        SD_MMC.end();
        return false;
    }
    nextN_ = prefs_.getULong64(kPrefsKey, 1ULL);
    sweepPartials();

    ready_ = true;
    Serial.printf(
        "SD queue ready at %s (next=%llu, used=%llu/%llu bytes)\n",
        queueDir_.c_str(),
        static_cast<unsigned long long>(nextN_),
        static_cast<unsigned long long>(SD_MMC.usedBytes()),
        static_cast<unsigned long long>(SD_MMC.totalBytes())
    );
    return true;
}

bool SdQueue::enqueue(const std::vector<uint8_t>& wavBytes, String* outPath) {
    if (!ready_) return false;
    if (wavBytes.empty() || wavBytes.size() > kMaxFileBytes) {
        Serial.printf("SD queue rejected enqueue: %u bytes\n",
                      static_cast<unsigned>(wavBytes.size()));
        return false;
    }

    const uint64_t total = SD_MMC.totalBytes();
    if (total > 0) {
        const uint64_t used = SD_MMC.usedBytes();
        const float ratio = static_cast<float>(used) / static_cast<float>(total);
        if (ratio >= kUsageHardCap) {
            Serial.printf("SD over %.0f%% used; rejecting enqueue\n",
                          kUsageHardCap * 100.f);
            return false;
        }
    }

    const String stem = nextFilenameStem();
    const String finalPath = joinPath(queueDir_, stem + ".wav");
    const String partialPath = joinPath(queueDir_, stem + ".wav.partial");

    File f = SD_MMC.open(partialPath, FILE_WRITE);
    if (!f) {
        Serial.printf("SD queue open failed: %s\n", partialPath.c_str());
        return false;
    }
    const size_t written = f.write(wavBytes.data(), wavBytes.size());
    f.close();
    if (written != wavBytes.size()) {
        SD_MMC.remove(partialPath);
        Serial.printf("SD queue short write %u/%u\n",
                      static_cast<unsigned>(written),
                      static_cast<unsigned>(wavBytes.size()));
        return false;
    }

    if (!SD_MMC.rename(partialPath, finalPath)) {
        SD_MMC.remove(partialPath);
        Serial.printf("SD queue rename failed: %s -> %s\n",
                      partialPath.c_str(), finalPath.c_str());
        return false;
    }

    ++nextN_;
    prefs_.putULong64(kPrefsKey, nextN_);
    if (outPath) *outPath = finalPath;
    return true;
}

bool SdQueue::peekOldestPath(String& outPath) {
    if (!ready_) return false;
    File root = SD_MMC.open(queueDir_);
    if (!root || !root.isDirectory()) {
        if (root) root.close();
        return false;
    }

    String oldest;
    File entry = root.openNextFile();
    while (entry) {
        const String name = entry.name();
        if (!entry.isDirectory() && name.endsWith(".wav")) {
            if (oldest.isEmpty() || name < oldest) {
                oldest = name;
            }
        }
        entry.close();
        entry = root.openNextFile();
    }
    root.close();
    if (oldest.isEmpty()) return false;

    outPath = fullPathOf(queueDir_, oldest);
    return true;
}

std::unique_ptr<SdFileBodySource> SdQueue::openReader(const String& path) {
    if (!ready_) return nullptr;
    File f = SD_MMC.open(path, FILE_READ);
    if (!f) return nullptr;
    auto file = std::unique_ptr<FileLike>(new SdFile(f));
    return std::unique_ptr<SdFileBodySource>(new SdFileBodySource(std::move(file)));
}

bool SdQueue::removeFile(const String& path) {
    if (!ready_) return false;
    return SD_MMC.remove(path);
}

QueueStats SdQueue::stats() {
    QueueStats s;
    if (!ready_) return s;
    s.totalBytes = SD_MMC.totalBytes();
    s.usedBytes = SD_MMC.usedBytes();
    File root = SD_MMC.open(queueDir_);
    if (root && root.isDirectory()) {
        File entry = root.openNextFile();
        while (entry) {
            if (!entry.isDirectory()) {
                const String name = entry.name();
                if (name.endsWith(".wav")) ++s.pending;
            }
            entry.close();
            entry = root.openNextFile();
        }
        root.close();
    }
    return s;
}

bool SdQueue::sweepPartials() {
    File root = SD_MMC.open(queueDir_);
    if (!root || !root.isDirectory()) {
        if (root) root.close();
        return false;
    }
    uint16_t removed = 0;
    File entry = root.openNextFile();
    while (entry) {
        const String name = entry.name();
        const bool isPartial = !entry.isDirectory() && name.endsWith(".partial");
        const String resolved = isPartial ? fullPathOf(queueDir_, name) : String();
        entry.close();
        if (isPartial && SD_MMC.remove(resolved)) {
            ++removed;
        }
        entry = root.openNextFile();
    }
    root.close();
    if (removed > 0) {
        Serial.printf("SD queue swept %u partial files\n", removed);
    }
    return true;
}

String SdQueue::nextFilenameStem() {
    char buf[24];
    snprintf(buf, sizeof(buf), "Q%012llu",
             static_cast<unsigned long long>(nextN_));
    return String(buf);
}

}  // namespace locallexis::storage
