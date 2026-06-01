#pragma once

#include <Arduino.h>

#include "audio/RecordingSession.h"  // RecState, StopReason

namespace locallexis::ui {

struct EpdPins { int busy, rst, dc, cs, sck, mosi, pwr; };

class RecorderUi {
public:
    RecorderUi(const EpdPins& epd, int ledPin);

    void begin();  // power panel, init display, render STANDBY, LED off
    // Wire to RecordingSession::setOnState.
    void onState(locallexis::audio::RecState state, locallexis::audio::StopReason reason);
    void tick();   // advance LED blink + clear transient error screen; call every loop

private:
    void renderText(const char* line1, const char* line2);
    void setLed(bool on);

    EpdPins epd_;
    int led_;
    bool blinking_ = false;
    bool ledOn_ = false;
    uint32_t lastBlinkMs_ = 0;
    uint32_t errUntilMs_ = 0;
};

}  // namespace locallexis::ui
