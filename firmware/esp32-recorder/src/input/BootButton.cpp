#include "input/BootButton.h"

namespace locallexis::input {

namespace {
constexpr uint32_t kDebounceMs = 30;
constexpr uint32_t kTapMaxMs = 800;
}  // namespace

BootButton::BootButton(int pin) : pin_(pin) {}

void BootButton::begin() {
    pinMode(pin_, INPUT_PULLUP);
    attachInterruptArg(digitalPinToInterrupt(pin_), &BootButton::isrThunk, this, CHANGE);
}

void IRAM_ATTR BootButton::isrThunk(void* arg) {
    static_cast<BootButton*>(arg)->onEdge();
}

void IRAM_ATTR BootButton::onEdge() {
    const uint32_t now = millis();
    const bool pressed = digitalRead(pin_) == LOW;  // active-LOW
    if (pressed) {
        pressMs_ = now;
    } else {
        const uint32_t held = now - pressMs_;
        if (held >= kDebounceMs && held <= kTapMaxMs) {
            tapPending_ = true;
        }
    }
}

bool BootButton::consumeTap() {
    if (!tapPending_) return false;
    tapPending_ = false;
    if (!armed_) return false;
    return true;
}

}  // namespace locallexis::input
