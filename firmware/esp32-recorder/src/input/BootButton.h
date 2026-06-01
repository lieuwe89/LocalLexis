#pragma once

#include <Arduino.h>

#include "audio/RecordingSession.h"  // Button

namespace locallexis::input {

// GPIO0 (BOOT) momentary, active-LOW. ISR timestamps edges; consumeTap() runs on
// the loopTask and reports a debounced tap (press+release within kTapMaxMs).
class BootButton : public locallexis::audio::Button {
public:
    explicit BootButton(int pin);

    void begin();
    void arm() override { armed_ = true; }
    void disarm() override { armed_ = false; }

    // Returns true once per completed tap (only while armed). Call every loop.
    bool consumeTap();

    // Returns true once per completed hold (press held >= kHoldMs), only while armed.
    bool consumeHold();

private:
    static void IRAM_ATTR isrThunk(void* arg);
    void IRAM_ATTR onEdge();

    int pin_;
    volatile bool armed_ = false;
    volatile uint32_t pressMs_ = 0;
    volatile bool tapPending_ = false;
    volatile bool holdPending_ = false;
};

}  // namespace locallexis::input
