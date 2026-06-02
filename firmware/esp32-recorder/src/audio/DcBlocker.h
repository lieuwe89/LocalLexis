#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>

namespace locallexis::audio {

// One-pole DC-blocking high-pass for 16-bit mono PCM.
//
//   y[n] = x[n] - x[n-1] + pole * y[n-1]
//
// The ES8311 mic path carries a large constant DC offset (~+17k LSB observed
// on hardware) that the codec's own ADC HPF does not remove; left in, it eats
// >half the headroom and clips loud transients. pole=0.995 at 16 kHz puts the
// -3 dB corner near ~12.7 Hz: kills DC, leaves voice (>80 Hz) untouched.
class DcBlocker {
public:
    explicit DcBlocker(float pole = 0.995f) : pole_(pole) {}

    void reset() {
        prevIn_ = 0.0f;
        prevOut_ = 0.0f;
    }

    int16_t process(int16_t x) {
        const float in = static_cast<float>(x);
        const float out = in - prevIn_ + pole_ * prevOut_;
        prevIn_ = in;
        prevOut_ = out;
        long v = std::lroundf(out);
        if (v > 32767) v = 32767;
        if (v < -32768) v = -32768;
        return static_cast<int16_t>(v);
    }

    // Filter an interleaved little-endian int16 mono byte buffer in place.
    // An odd trailing byte (should never occur for 16-bit frames) is left as-is.
    void processBytes(uint8_t* bytes, size_t len) {
        for (size_t i = 0; i + 1 < len; i += 2) {
            const int16_t s = static_cast<int16_t>(
                static_cast<uint16_t>(bytes[i]) |
                (static_cast<uint16_t>(bytes[i + 1]) << 8));
            const int16_t y = process(s);
            bytes[i] = static_cast<uint8_t>(y & 0xff);
            bytes[i + 1] = static_cast<uint8_t>((y >> 8) & 0xff);
        }
    }

private:
    float pole_;
    float prevIn_ = 0.0f;
    float prevOut_ = 0.0f;
};

}  // namespace locallexis::audio
