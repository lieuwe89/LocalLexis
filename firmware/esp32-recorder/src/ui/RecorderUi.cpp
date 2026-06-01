#include "ui/RecorderUi.h"

#include <SPI.h>
#include <GxEPD2_BW.h>
#include <Fonts/FreeMonoBold12pt7b.h>
#include <Fonts/FreeSansBold9pt7b.h>

using locallexis::audio::RecState;
using locallexis::audio::StopReason;

namespace locallexis::ui {

namespace {
constexpr uint32_t kBlinkMs = 500;
constexpr uint32_t kErrMs = 2000;

// One static display instance (GxEPD2 holds a large framebuffer; keep it off the stack).
GxEPD2_BW<GxEPD2_154_D67, GxEPD2_154_D67::HEIGHT>* g_display = nullptr;
EpdPins g_epd{};
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
    digitalWrite(epd_.pwr, LOW);  // active-LOW: power panel
    delay(50);
    SPI.begin(epd_.sck, -1, epd_.mosi, epd_.cs);

    g_epd = epd_;
    static GxEPD2_BW<GxEPD2_154_D67, GxEPD2_154_D67::HEIGHT> display(
        GxEPD2_154_D67(epd_.cs, epd_.dc, epd_.rst, epd_.busy));
    g_display = &display;
    g_display->init(115200, true, 2, false);
    g_display->setRotation(1);
    g_display->setTextColor(GxEPD_BLACK);

    renderText("STANDBY", "");
}

void RecorderUi::renderText(const char* line1, const char* line2) {
    if (!g_display) return;
    g_display->setFullWindow();
    g_display->firstPage();
    do {
        g_display->fillScreen(GxEPD_WHITE);
        g_display->setFont(&FreeMonoBold12pt7b);
        g_display->setCursor(10, 60);
        g_display->print(line1);
        if (line2 && line2[0]) {
            g_display->setFont(&FreeSansBold9pt7b);
            g_display->setCursor(10, 110);
            g_display->print(line2);
        }
    } while (g_display->nextPage());
    g_display->hibernate();
}

void RecorderUi::onState(RecState state, StopReason reason) {
    if (state == RecState::Recording) {
        blinking_ = true;
        lastBlinkMs_ = millis();
        setLed(true);
        renderText("RECORDING", "");
        return;
    }
    if (state == RecState::Standby) {
        blinking_ = false;
        setLed(false);
        if (reason == StopReason::Full) {
            renderText("FULL", "tap to start new");
        } else if (reason == StopReason::Error) {
            renderText("MIC/SD ERROR", "");
            errUntilMs_ = millis() + kErrMs;
        } else {
            renderText("STANDBY", "");
        }
    }
}

void RecorderUi::tick() {
    const uint32_t now = millis();
    if (blinking_ && now - lastBlinkMs_ >= kBlinkMs) {
        lastBlinkMs_ = now;
        setLed(!ledOn_);
    }
    if (errUntilMs_ != 0 && now >= errUntilMs_) {
        errUntilMs_ = 0;
        renderText("STANDBY", "");
    }
}

}  // namespace locallexis::ui
