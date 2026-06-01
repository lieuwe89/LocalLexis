#include <cassert>
#include <cstring>
#include <iostream>
#include <string>

#include "ui/ScreenLayout.h"

using namespace locallexis::ui;

namespace {

bool hasText(const DrawList& d, const char* needle) {
    for (const auto& t : d.texts)
        if (std::string(t.text).find(needle) != std::string::npos) return true;
    return false;
}
const TextRun* findText(const DrawList& d, const char* needle) {
    for (const auto& t : d.texts)
        if (std::string(t.text).find(needle) != std::string::npos) return &t;
    return nullptr;
}
bool hasIcon(const DrawList& d, IconId id) {
    for (const auto& i : d.icons) if (i.id == id) return true;
    return false;
}

void test_formatters() {
    char buf[12];
    formatDuration(0, buf);      assert(std::string(buf) == "0:00");
    formatDuration(67, buf);     assert(std::string(buf) == "1:07");
    formatDuration(727, buf);    assert(std::string(buf) == "12:07");
    char z[4];
    zeroPad3(14, z);   assert(std::string(z) == "014");
    zeroPad3(2, z);    assert(std::string(z) == "002");
    zeroPad3(137, z);  assert(std::string(z) == "137");
    char s[12];
    formatSize(4'404'019, s);    assert(std::string(s).find("MB") != std::string::npos);
    formatSize(812 * 1024, s);   assert(std::string(s).find("KB") != std::string::npos);
}

void test_boot_inverts_and_shows_wordmark() {
    UiModel m; m.screen = Screen::Boot;
    auto d = layoutFor(m);
    assert(d.invertPanel == true);
    assert(hasText(d, "Local"));     // wordmark
    assert(hasText(d, "hello"));
    for (const auto& t : d.texts) assert(t.invert == true);  // paper ink on ink panel
}

void test_idle_status_row_and_battery_pct() {
    UiModel m; m.screen = Screen::Idle; m.battery = 82;
    auto d = layoutFor(m);
    assert(d.invertPanel == false);
    assert(hasText(d, "82%"));
    assert(hasText(d, "Ready"));
    assert(hasText(d, "Hold to record"));
    assert(hasIcon(d, IconId::BtBitmap));   // BLE/sync glyph in status row
    assert(hasIcon(d, IconId::Rec));        // affordance dot
}

void test_recording_inverts_pill_and_clip_and_started() {
    UiModel m; m.screen = Screen::Recording; m.clip = 14;
    std::strcpy(m.startedAt, "2:47 PM");
    auto d = layoutFor(m);
    assert(d.invertPanel == true);
    assert(hasText(d, "REC"));
    assert(hasText(d, "Clip 014"));         // zero-padded
    assert(hasText(d, "Listening"));
    assert(hasText(d, "2:47 PM"));
    assert(hasIcon(d, IconId::Stop));
    // Pill text is NOT inverted (paper-fill badge => ink text), so it must differ
    // from the panel's paper-on-ink default.
    const TextRun* pill = findText(d, "REC");
    assert(pill && pill->invert == false);
}

void test_saved_shows_clip_dur_size_and_check() {
    UiModel m; m.screen = Screen::Saved; m.clip = 14;
    std::strcpy(m.lastDur, "12:07"); std::strcpy(m.lastSize, "4.2 MB");
    auto d = layoutFor(m);
    assert(d.invertPanel == false);
    assert(hasText(d, "Got"));
    assert(hasText(d, "014"));
    assert(hasText(d, "12:07"));
    assert(hasText(d, "4.2 MB"));
    assert(hasIcon(d, IconId::Check));
}

void test_syncing_meter_cells_match_done_total() {
    UiModel m; m.screen = Screen::Syncing; m.syncDone = 3; m.syncTotal = 5;
    auto d = layoutFor(m);
    assert(hasText(d, "3/5"));
    assert(d.meters.size() == 1);
    assert(d.meters[0].id == MeterId::Block);
    assert(d.meters[0].n == 5 && d.meters[0].k == 3);
}

void test_battery_inverts_and_fills_glyph() {
    UiModel m; m.screen = Screen::Battery; m.battery = 8;
    auto d = layoutFor(m);
    assert(d.invertPanel == true);
    assert(hasText(d, "8%"));
    assert(hasText(d, "Almost"));
    assert(hasIcon(d, IconId::Battery));
    assert(hasIcon(d, IconId::Warn));
    // Battery glyph fill clamps to >=1 segment even near empty (design uses max(0.06)).
    for (const auto& i : d.icons) if (i.id == IconId::Battery) assert(i.arg >= 1);
}

void test_storage_and_connection() {
    UiModel s; s.screen = Screen::Storage;
    auto ds = layoutFor(s);
    assert(ds.invertPanel == false);
    assert(hasText(ds, "full"));
    assert(hasIcon(ds, IconId::FullBitmap));

    UiModel c; c.screen = Screen::Connection; c.signal = 3;
    auto dc = layoutFor(c);
    assert(hasText(dc, "Linked"));
    assert(hasIcon(dc, IconId::BtBitmap));
    assert(hasIcon(dc, IconId::Signal));
    for (const auto& i : dc.icons) if (i.id == IconId::Signal) assert(i.arg == 3);
}

}  // namespace

int main() {
    test_formatters();
    test_boot_inverts_and_shows_wordmark();
    test_idle_status_row_and_battery_pct();
    test_recording_inverts_pill_and_clip_and_started();
    test_saved_shows_clip_dur_size_and_check();
    test_syncing_meter_cells_match_done_total();
    test_battery_inverts_and_fills_glyph();
    test_storage_and_connection();
    std::cout << "test_screen_layout: OK" << std::endl;
    return 0;
}
