#include "ui/RecorderUi.h"

#include <SPI.h>
#include <GxEPD2_BW.h>

#include "ui/ScreenLayout.h"
#include "ui/UiFonts.h"
#include "ui/UiIcons.h"

using locallexis::audio::RecState;
using locallexis::audio::StopReason;

namespace locallexis::ui {

namespace {
constexpr uint32_t kBlinkMs = 500;
constexpr uint32_t kBootMs  = 1700;
constexpr uint32_t kSavedMs = 2400;

// One static panel instance: GxEPD2 holds the framebuffer; keep it off the stack.
GxEPD2_BW<GxEPD2_154_D67, GxEPD2_154_D67::HEIGHT>* g_display = nullptr;

inline uint16_t inkColor(bool panelInverted, bool runInverted) {
    // On a normal panel: a non-inverted run is BLACK ink. On an inverted (ink)
    // panel: a "paper ink" run (run.invert==true) is WHITE. XOR resolves both.
    return (panelInverted ^ runInverted) ? GxEPD_BLACK : GxEPD_WHITE;
}
}  // namespace

RecorderUi::RecorderUi(const EpdPins& epd, int ledPin) : epd_(epd), led_(ledPin) {}

void RecorderUi::setLed(bool on) {
    ledOn_ = on;
    digitalWrite(led_, on ? LOW : HIGH);  // active-LOW
}

void RecorderUi::begin() {
    pinMode(led_, OUTPUT);
    setLed(false);

    pinMode(epd_.pwr, OUTPUT);
    digitalWrite(epd_.pwr, LOW);  // active-LOW: power the panel
    delay(50);
    SPI.begin(epd_.sck, -1, epd_.mosi, epd_.cs);

    static GxEPD2_BW<GxEPD2_154_D67, GxEPD2_154_D67::HEIGHT> display(
        GxEPD2_154_D67(epd_.cs, epd_.dc, epd_.rst, epd_.busy));
    g_display = &display;
    g_display->init(115200, true, 2, false);
    g_display->setRotation(1);

    current_.screen = Screen::Boot;
    show(current_);
    autoAdvanceAtMs_ = millis() + kBootMs;
}

void RecorderUi::blit(const UiModel& model) {
    if (!g_display) return;
    const DrawList d = layoutFor(model);
    g_display->setFullWindow();
    g_display->firstPage();
    do {
        g_display->fillScreen(d.invertPanel ? GxEPD_BLACK : GxEPD_WHITE);
        // REC pill paper rect (Recording only): behind the pill runs.
        if (model.screen == Screen::Recording) {
            g_display->fillRect(15, 15, 52, 18, GxEPD_WHITE);
        }
        for (const auto& mt : d.meters)
            drawMeter(*g_display, mt, inkColor(d.invertPanel, mt.invert));
        for (const auto& ic : d.icons)
            drawIcon(*g_display, ic, inkColor(d.invertPanel, ic.invert));
        for (const auto& t : d.texts) {
            g_display->setFont(fontForRole(t.role));
            g_display->setTextColor(inkColor(d.invertPanel, t.invert));
            g_display->setCursor(t.x, t.y);
            g_display->print(t.text);
        }
    } while (g_display->nextPage());
    g_display->hibernate();
}

void RecorderUi::show(const UiModel& model) {
    current_ = model;
    blit(current_);
}

void RecorderUi::onState(RecState state, StopReason reason) {
    if (state == RecState::Recording) {
        blinking_ = true; lastBlinkMs_ = millis(); setLed(true);
        current_.screen = Screen::Recording;
        // startedAt/clip are populated by main.cpp before this fires (Task 19);
        // if empty, the Recording screen still renders (blank started time).
        show(current_);
        return;
    }
    if (state == RecState::Standby) {
        blinking_ = false; setLed(false);
        if (reason == StopReason::Full) {
            current_.screen = Screen::Storage;     // cap-hit maps to Storage (DECISION)
            show(current_);
        } else if (reason == StopReason::Error) {
            current_.screen = Screen::Storage;     // start-fail/SD error surface (DECISION seam)
            show(current_);
            autoAdvanceAtMs_ = millis() + kSavedMs;
        } else {
            // User stop: show Saved (clip/dur/size set by main.cpp via showSaved),
            // which auto-advances to Idle. If main hasn't set them, fall to Idle.
            current_.screen = Screen::Saved;
            show(current_);
            autoAdvanceAtMs_ = millis() + kSavedMs;
        }
    }
}

void RecorderUi::tick() {
    const uint32_t now = millis();
    if (blinking_ && now - lastBlinkMs_ >= kBlinkMs) {
        lastBlinkMs_ = now; setLed(!ledOn_);
    }
    if (autoAdvanceAtMs_ != 0 && now >= autoAdvanceAtMs_) {
        autoAdvanceAtMs_ = 0;
        current_.screen = Screen::Idle;
        show(current_);
    }
}

void RecorderUi::showBoot()  { current_.screen = Screen::Boot;  show(current_); autoAdvanceAtMs_ = millis() + kBootMs; }
void RecorderUi::showIdle()  { current_.screen = Screen::Idle;  show(current_); }
void RecorderUi::showSaved(uint16_t clip, const char* dur, const char* size) {
    current_.screen = Screen::Saved; current_.clip = clip;
    std::snprintf(current_.lastDur, sizeof(current_.lastDur), "%s", dur ? dur : "");
    std::snprintf(current_.lastSize, sizeof(current_.lastSize), "%s", size ? size : "");
    show(current_); autoAdvanceAtMs_ = millis() + kSavedMs;
}
void RecorderUi::showSyncing(uint8_t done, uint8_t total) {
    current_.screen = Screen::Syncing; current_.syncDone = done; current_.syncTotal = total;
    show(current_);
}
void RecorderUi::showConnection(uint8_t bars) { current_.screen = Screen::Connection; current_.signal = bars; show(current_); }
void RecorderUi::showBattery(uint8_t pct)     { current_.screen = Screen::Battery;    current_.battery = pct; show(current_); }
void RecorderUi::showStorage()                { current_.screen = Screen::Storage;    show(current_); }

}  // namespace locallexis::ui
