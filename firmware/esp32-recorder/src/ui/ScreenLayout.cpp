#include "ui/ScreenLayout.h"

#include <cstdio>
#include <cstring>

namespace locallexis::ui {

namespace {
constexpr int16_t kPad = 15;
constexpr int16_t kW = 200, kH = 200;

void putText(DrawList& d, int16_t x, int16_t y, FontRole r, bool inv, const char* s) {
    TextRun t{}; t.x = x; t.y = y; t.role = r; t.invert = inv;
    std::snprintf(t.text, sizeof(t.text), "%s", s);
    d.texts.push_back(t);
}
void putIcon(DrawList& d, int16_t x, int16_t y, int16_t size, IconId id, bool inv, uint8_t arg = 0) {
    d.icons.push_back(IconDraw{x, y, size, id, inv, arg});
}
}  // namespace

void zeroPad3(uint16_t value, char out[4]) {
    std::snprintf(out, 4, "%03u", static_cast<unsigned>(value % 1000));
}

void formatDuration(uint32_t seconds, char out[8]) {
    const uint32_t mm = seconds / 60, ss = seconds % 60;
    std::snprintf(out, 8, "%u:%02u", static_cast<unsigned>(mm), static_cast<unsigned>(ss));
}

void formatSize(uint32_t bytes, char out[12]) {
    if (bytes >= 1024u * 1024u) {
        std::snprintf(out, 12, "%.1f MB", static_cast<double>(bytes) / (1024.0 * 1024.0));
    } else {
        std::snprintf(out, 12, "%u KB", static_cast<unsigned>((bytes + 512) / 1024));
    }
}

DrawList layoutFor(const UiModel& m) {
    DrawList d;
    switch (m.screen) {
        // NOTE: the y-coordinates below are baseline positions transcribed from
        // expressive-screens.jsx's three-zone (top/middle/bottom) space-between
        // rhythm at padding 15. Tune at the device session; the contract the tests
        // pin is copy + inversion + meter counts, not exact baselines.
        case Screen::Boot: {
            d.invertPanel = true;
            putText(d, 40, 96, FontRole::HeadL, true, "LocalLexis");
            putText(d, 78, 118, FontRole::Caps, true, "hello.");
            break;
        }
        case Screen::Idle: {
            putIcon(d, kPad, kPad, 9, IconId::BtBitmap, false);
            putText(d, kPad + 13, kPad + 9, FontRole::Caps, false, "LocalLexis");
            char pct[8]; std::snprintf(pct, sizeof(pct), "%u%%", m.battery);
            putText(d, kW - kPad - 28, kPad + 9, FontRole::Caps, false, pct);
            putText(d, kPad, 86,  FontRole::HeadXL, false, "Ready");
            putText(d, kPad, 124, FontRole::HeadXL, false, "when");
            putText(d, kPad, 162, FontRole::HeadXL, false, "you are.");
            putIcon(d, kPad, kH - kPad - 9, 11, IconId::Rec, false);
            putText(d, kPad + 18, kH - kPad, FontRole::Caps, false, "Hold to record");
            break;
        }
        case Screen::Recording: {
            d.invertPanel = true;
            // REC pill: blitter paints the paper rect from this icon's bounds; the
            // run + dot are ink (invert=false) so they read on the paper fill.
            putIcon(d, kPad + 6, 21, 7, IconId::Rec, false);
            putText(d, kPad + 18, 27, FontRole::Pill, false, "REC");
            char clip[12]; char z[4]; zeroPad3(m.clip, z);
            std::snprintf(clip, sizeof(clip), "Clip %s", z);
            putText(d, kW - kPad - 48, kPad + 9, FontRole::Caps, true, clip);
            putText(d, kPad, 96, FontRole::HeadXL, true, "Listening.");
            d.meters.push_back(MeterDraw{kPad, 110, 150, 16, MeterId::Level, true, 22, 0});
            char started[24]; std::snprintf(started, sizeof(started), "Started %s", m.startedAt);
            putText(d, kPad, kH - kPad, FontRole::Caps, true, started);
            putIcon(d, kW - kPad - 40, kH - kPad - 9, 8, IconId::Stop, true);
            putText(d, kW - kPad - 28, kH - kPad, FontRole::Caps, true, "Stop");
            break;
        }
        case Screen::Saved: {
            putIcon(d, kPad, 52, 50, IconId::Check, false);
            putText(d, kPad, 150, FontRole::HeadXL, false, "Got it.");
            char foot[32]; char z[4]; zeroPad3(m.clip, z);
            std::snprintf(foot, sizeof(foot), "Clip %s \xC2\xB7 %s \xC2\xB7 %s", z, m.lastDur, m.lastSize);
            putText(d, kPad, kH - kPad, FontRole::Caps, false, foot);
            break;
        }
        case Screen::Syncing: {
            putIcon(d, kPad, kPad, 20, IconId::BtBitmap, false);
            putText(d, kPad + 28, kPad + 16, FontRole::HeadM, false, "Sending to");
            putText(d, kPad + 28, kPad + 40, FontRole::HeadM, false, "your Mac...");
            char ratio[12]; std::snprintf(ratio, sizeof(ratio), "%u/%u", m.syncDone, m.syncTotal);
            putText(d, kPad, 150, FontRole::NumL, false, ratio);
            d.meters.push_back(MeterDraw{kPad, 162, 170, 11, MeterId::Block, false, m.syncTotal, m.syncDone});
            putText(d, kPad, kH - kPad, FontRole::Caps, false, "clips \xC2\xB7 keep nearby");
            break;
        }
        case Screen::Connection: {
            putIcon(d, kPad, kPad, 24, IconId::BtBitmap, false);
            putIcon(d, kW - kPad - 22, kPad, 22, IconId::Signal, false, m.signal);
            putText(d, kPad, 118, FontRole::HeadXL, false, "Linked up.");
            putText(d, kPad, kH - kPad, FontRole::Caps, false, "LocalLexis \xC2\xB7 strong signal");
            break;
        }
        case Screen::Battery: {
            d.invertPanel = true;
            putIcon(d, kW - kPad - 18, kPad, 15, IconId::Warn, true);
            uint8_t fill = static_cast<uint8_t>((m.battery * 4 + 50) / 100);
            if (fill < 1) fill = 1;  // design clamps to max(0.06) so >=1 cell shows
            putIcon(d, kPad, 90, 48, IconId::Battery, true, fill);
            char pct[8]; std::snprintf(pct, sizeof(pct), "%u%%", m.battery);
            putText(d, kPad + 60, 108, FontRole::NumL, true, pct);
            putText(d, kPad, 162, FontRole::HeadL, true, "Almost out.");
            putText(d, kPad, kH - kPad, FontRole::Caps, true, "Charge soon");
            break;
        }
        case Screen::Storage: {
            putIcon(d, kW - kPad - 13, kPad, 13, IconId::FullBitmap, false);
            putText(d, kPad, 118, FontRole::HeadXL, false, "I'm full.");
            putText(d, kPad, kH - kPad, FontRole::Caps, false, "Sync to clear space");
            break;
        }
    }
    return d;
}

}  // namespace locallexis::ui
