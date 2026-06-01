#include "audio/Es8311Codec.h"

#include <Wire.h>

namespace locallexis::audio {

namespace {
struct RegVal { uint8_t reg; uint8_t val; };

// ES8311 ADC/mic init for 16 kHz mono 16-bit, slave, MCLK=256xfs, analog mic.
// Ordered per reference es8311.c. DAC registers intentionally omitted.
const RegVal kInit[] = {
    {0x44, 0x08},  // GPIO/test (write twice for I2C noise immunity)
    {0x44, 0x08},
    {0x01, 0x30},  // clk manager preset
    {0x02, 0x00},  // dividers/multiplier (pre_div=1, mult=1)
    {0x03, 0x10},  // ADC fsmode/osr preset
    {0x16, 0x24},  // ADC preset (gain set later)
    {0x04, 0x10},  // DAC osr preset (harmless)
    {0x05, 0x00},  // adc/dac clk divider (adc_div=1, dac_div=1)
    {0x0B, 0x00},
    {0x0C, 0x00},
    {0x10, 0x1F},  // bias/vmid
    {0x11, 0x7F},  // system
    {0x00, 0x80},  // release reset, csm on, SLAVE (bit6=0)
    {0x01, 0x3F},  // mclk src: use external MCLK (bit7=0), not inverted
    {0x14, 0x1A},  // analog mic select (bit6=0 => analog), PGA on
    {0x13, 0x10},
    {0x1B, 0x0A},  // ADC HPF / automute
    {0x1C, 0x6A},  // ADC HPF stage2
    {0x44, 0x58},  // internal reference (ADCL + DACR)
    // sample-rate coefficients (4.096 MHz row)
    {0x02, 0x00},  // pre_div-1=0, mult code 0
    {0x05, 0x00},  // (adc_div-1)<<4 | (dac_div-1)
    {0x03, 0x20},  // fs_mode 0 | adc_osr 0x20
    {0x04, 0x20},  // dac_osr 0x20
    {0x07, 0x00},  // lrck_h
    {0x08, 0xFF},  // lrck_l => LRCK div 0x00FF
    {0x06, 0x03},  // bclk_div code (4-1=3)
    // start ADC path, 16-bit
    {0x0A, 0x0C},  // ADC SDP: 16-bit, ADC SDOUT enabled (bit6=0)
    {0x17, 0xBF},  // ADC digital volume
    {0x0E, 0x02},  // analog ADC power up
    {0x12, 0x00},  // DAC off (mic-only)
    {0x0D, 0x01},  // system power up
    {0x15, 0x40},  // ADC ramp/soft-start
    {0x45, 0x00},  // GP control
};

constexpr uint8_t kRegAdcSdp = 0x0A;   // bit6 = ADC mute
}  // namespace

Es8311Codec::Es8311Codec(int sdaPin, int sclPin, int audioPwrPin, uint8_t i2cAddr)
    : sda_(sdaPin), scl_(sclPin), pwr_(audioPwrPin), addr_(i2cAddr) {}

bool Es8311Codec::writeReg(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(addr_);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission() == 0;
}

bool Es8311Codec::readReg(uint8_t reg, uint8_t& out) {
    Wire.beginTransmission(addr_);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(static_cast<int>(addr_), 1) != 1) return false;
    out = Wire.read();
    return true;
}

bool Es8311Codec::powerOnAndConfigure() {
    // Audio rail is active-LOW: drive 0 to power the codec, then settle.
    pinMode(pwr_, OUTPUT);
    digitalWrite(pwr_, LOW);
    delay(10);

    if (!wireBegun_) {
        Wire.begin(sda_, scl_);
        Wire.setClock(100000);
        wireBegun_ = true;
    }

    for (const auto& rv : kInit) {
        if (!writeReg(rv.reg, rv.val)) {
            Serial.printf("ES8311 I2C NACK at reg 0x%02X\n", rv.reg);
            powerOff();
            return false;
        }
    }
    setMicGain(0x07);  // ~42 dB default
    Serial.println("ES8311 configured: 16 kHz mono 16-bit ADC");
    return true;
}

bool Es8311Codec::setMicGain(uint8_t gainCode) {
    return writeReg(0x16, gainCode & 0x07);
}

void Es8311Codec::powerOff() {
    if (wireBegun_) {
        uint8_t sdp = 0;
        if (readReg(kRegAdcSdp, sdp)) {
            writeReg(kRegAdcSdp, sdp | 0x40);  // mute ADC SDOUT
        }
        writeReg(0x0E, 0x00);  // analog ADC power down
        writeReg(0x0D, 0x00);  // system power down
    }
    digitalWrite(pwr_, HIGH);  // cut rail (active-LOW)
}

}  // namespace locallexis::audio
