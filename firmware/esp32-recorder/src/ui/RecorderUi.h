#pragma once

#include <Arduino.h>

#include "audio/RecordingSession.h"  // RecState, StopReason
#include "ui/UiModel.h"

namespace locallexis::ui {

struct EpdPins { int busy, rst, dc, cs, sck, mosi, pwr; };

class RecorderUi {
public:
    RecorderUi(const EpdPins& epd, int ledPin);

    void begin();  // power panel, init display, render Boot, LED off

    // Locked adapter — wired to RecordingSession::setOnState (Task 13, unchanged).
    void onState(locallexis::audio::RecState state, locallexis::audio::StopReason reason);

    void tick();   // advance LED blink + auto-advance timers; call every loop

    // Full model render (one full refresh).
    void show(const UiModel& model);

    // Mutating accessors so main.cpp can populate fields then re-render.
    UiModel& model() { return current_; }
    void showCurrent() { show(current_); }

    // Convenience entry points for the non-capture screens (Task 19 gates these).
    void showBoot();
    void showIdle();
    void showSaved(uint16_t clip, const char* dur, const char* size);
    void showSyncing(uint8_t done, uint8_t total);
    void showConnection(uint8_t signalBars);
    void showBattery(uint8_t pct);
    void showStorage();

private:
    void blit(const UiModel& model);   // executes layoutFor(model) on the panel
    void setLed(bool on);

    EpdPins  epd_;
    int      led_;
    UiModel  current_;
    bool     blinking_ = false;
    bool     ledOn_ = false;
    uint32_t lastBlinkMs_ = 0;
    uint32_t autoAdvanceAtMs_ = 0;     // Boot->Idle (~1.7s) and Saved->Idle (~2.4s)
};

}  // namespace locallexis::ui
