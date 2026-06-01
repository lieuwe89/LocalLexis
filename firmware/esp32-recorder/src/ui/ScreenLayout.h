#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "ui/UiModel.h"

namespace locallexis::ui {

// Type tokens from the handoff "Type scale" table (px sizes resolved to concrete
// fonts in Task 15). Layout references roles only — never a GFXfont.
enum class FontRole : uint8_t {
    HeadXL,   // Goudy 38-44  (Idle/Recording/Saved/Storage/Connection)
    HeadL,    // Goudy 32-34  (Battery, Boot wordmark)
    HeadM,    // Goudy 27     (Syncing)
    NumL,     // mono 30-34   (Sync done/total, Battery %)
    Caps,     // mono 9 caps  (status row, footers, sub-labels)
    Pill,     // mono 8.5/600 (REC badge)
};

enum class IconId : uint8_t { Rec, Stop, Check, Warn, Sync, BtBitmap, FullBitmap, Battery, Signal };
enum class MeterId : uint8_t { Block, Level };

struct TextRun {
    int16_t  x, y;          // baseline-left, panel-native px
    FontRole role;
    bool     invert;        // true => paper ink on ink panel (drawn as WHITE)
    char     text[32];
};

struct IconDraw {
    int16_t x, y;           // top-left
    int16_t size;           // nominal px (square-ish); blitter scales bitmaps/strokes
    IconId  id;
    bool    invert;
    uint8_t arg;            // Battery: 0..4 fill; Signal: 0..4 bars; else 0
};

struct MeterDraw {
    int16_t x, y, w, h;
    MeterId id;
    bool    invert;
    uint8_t n, k;          // Block: n cells, k filled. Level: n bars (k unused)
};

struct DrawList {
    bool                   invertPanel = false;  // whole-panel ink ground
    std::vector<TextRun>   texts;
    std::vector<IconDraw>  icons;
    std::vector<MeterDraw> meters;
};

// PURE: build the full draw list for the current model. No I/O.
DrawList layoutFor(const UiModel& m);

// Pure formatters (the Saved-screen DECISION): host-tested.
void formatDuration(uint32_t seconds, char out[8]);          // -> "mm:ss"
void formatSize(uint32_t bytes, char out[12]);               // -> "4.2 MB" / "812 KB"
void zeroPad3(uint16_t value, char out[4]);                  // 14 -> "014"

}  // namespace locallexis::ui
