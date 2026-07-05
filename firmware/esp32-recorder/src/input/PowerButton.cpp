#include "input/PowerButton.h"

namespace locallexis::input {

PowerButton::PowerButton(int pin, uint32_t holdMs) : pin_(pin), holdMs_(holdMs) {}

void PowerButton::begin() {
    pinMode(pin_, INPUT_PULLUP);
}

bool PowerButton::consumeLongPress() {
    const bool down = digitalRead(pin_) == LOW;  // active-LOW
    const uint32_t now = millis();
    if (down) {
        if (!pressing_) {
            pressing_ = true;
            fired_ = false;
            pressStartMs_ = now;
        }
        if (!fired_ && (now - pressStartMs_) >= holdMs_) {
            fired_ = true;
            return true;
        }
    } else {
        pressing_ = false;
    }
    return false;
}

}  // namespace locallexis::input
