#pragma once

#include <Arduino.h>

namespace locallexis::input {

// Dedicated PWR button (GPIO18 on the Waveshare ESP32-S3-ePaper-1.54 V2), active-LOW
// with internal pull-up. Polled, no ISR: consumeLongPress() fires once when the button
// has been held continuously for >= holdMs, then stays quiet until it is released.
// Used to trigger a graceful power-off (drop the VBAT latch); see main.cpp.
class PowerButton {
public:
    PowerButton(int pin, uint32_t holdMs);

    void begin();              // pinMode INPUT_PULLUP
    bool consumeLongPress();   // call every loop; true once per qualifying hold

private:
    int pin_;
    uint32_t holdMs_;
    bool pressing_ = false;
    bool fired_ = false;
    uint32_t pressStartMs_ = 0;
};

}  // namespace locallexis::input
