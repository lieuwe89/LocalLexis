#pragma once

#include <cstdint>

namespace locallexis::ui {

enum class Screen : uint8_t {
    Boot, Idle, Recording, Saved, Syncing, Connection, Battery, Storage
};

// Single source of truth for the panel. Strings are fixed-capacity C buffers so
// the struct is trivially copyable and host-testable without heap churn.
struct UiModel {
    Screen   screen   = Screen::Boot;
    char     startedAt[12] = {0};   // capture start time, e.g. "2:47 PM"  (Recording)
    uint16_t clip      = 0;          // current clip number; zero-padded to 3 on screen
    char     lastDur[8]  = {0};      // "12:07"   (Saved) — formatted at stop
    char     lastSize[12] = {0};     // "4.2 MB"  (Saved) — formatted at stop
    uint8_t  battery   = 100;        // 0..100  (Idle %, Battery screen, glyph fill)
    uint8_t  syncDone  = 0;          // clips uploaded so far (Syncing meter k)
    uint8_t  syncTotal = 0;          // clips in this sync (Syncing meter n)
    uint8_t  signal    = 3;          // 0..4 BLE/link bars (Connection)
    uint16_t queued    = 0;          // clips waiting to sync
};

}  // namespace locallexis::ui
