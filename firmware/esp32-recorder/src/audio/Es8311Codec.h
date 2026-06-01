#pragma once

#include <Arduino.h>

#include "audio/RecordingSession.h"  // AudioCodec

namespace locallexis::audio {

// Hand-rolled ES8311 driver: ADC/mic path only, 16 kHz mono 16-bit, codec as I2S
// slave fed a 256x MCLK. Audio_PWR rail (active-LOW) is owned here.
class Es8311Codec : public AudioCodec {
public:
    Es8311Codec(int sdaPin, int sclPin, int audioPwrPin, uint8_t i2cAddr = 0x18);

    bool powerOnAndConfigure() override;  // rail on + I2C init + mono16k + default gain
    void powerOff() override;             // mute ADC + rail off

    bool setMicGain(uint8_t gainCode);    // 0..7 (ES8311_MIC_GAIN_0DB..42DB); default 0x07 (42 dB)

private:
    bool writeReg(uint8_t reg, uint8_t val);
    bool readReg(uint8_t reg, uint8_t& out);

    int sda_, scl_, pwr_;
    uint8_t addr_;
    bool wireBegun_ = false;
};

}  // namespace locallexis::audio
