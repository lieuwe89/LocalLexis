#pragma once

#include <cstdint>

namespace locallexis::power {

// State-of-charge gauge for a single-cell Li-ion read through the board's 1:1
// divider (caller feeds battery mV, i.e. the ADC reading already x2). Pure logic,
// no Arduino deps, so it is host-testable. The caller samples at its own cadence
// (e.g. every 30 s, only while idle / never under recording load) and passes each
// reading to update().
//
// E-paper has no cheap refresh, so the gauge is built to move as little as possible:
//   - EMA smoothing: one odd sample can't shift the displayed value.
//   - 5% buckets + 2-sample confirm: a reading wobbling across a bucket boundary
//     (load sag, Wi-Fi TX) can't flip the display back and forth.
//   - Low-battery alarm latches at <=kLowPct and only clears at >=kClearPct
//     (hysteresis) so it can't chatter.
// update() reports at most one event; the caller decides whether to repaint.
class BatteryGauge {
public:
    enum class Event : uint8_t { None, BucketChanged, LowAlarm };

    // Linear 3.00 V (0%) .. 4.12 V (100%), matching Waveshare's reference BSP.
    static uint8_t levelFromMilliVolts(uint32_t mv) {
        constexpr uint32_t kEmpty = 3000, kFull = 4120;
        if (mv <= kEmpty) return 0;
        if (mv >= kFull) return 100;
        return static_cast<uint8_t>((mv - kEmpty) * 100u / (kFull - kEmpty));
    }

    // Feed one battery-voltage sample (mV). Returns the most significant event.
    Event update(uint32_t mv) {
        if (!inited_) {
            ema_ = mv;
            inited_ = true;
        } else {
            ema_ = static_cast<uint32_t>(static_cast<int32_t>(ema_) +
                   (static_cast<int32_t>(mv) - static_cast<int32_t>(ema_)) / kEmaShift);
        }
        const uint8_t pct = levelFromMilliVolts(ema_);

        // Low-battery alarm: latch with hysteresis, evaluated before the bucket logic
        // so a fresh crossing always surfaces even before the bucket "confirms".
        Event ev = Event::None;
        if (!alarmed_ && pct <= kLowPct) {
            alarmed_ = true;
            ev = Event::LowAlarm;
        } else if (alarmed_ && pct >= kClearPct) {
            alarmed_ = false;
        }

        const int bucket = (pct + 2) / 5;  // nearest 5% -> 0..20
        if (shownBucket_ < 0) {            // first reading: adopt immediately
            shownBucket_ = bucket;
            pendingBucket_ = bucket;
            confirm_ = 0;
            return ev == Event::LowAlarm ? ev : Event::BucketChanged;
        }
        if (bucket == shownBucket_) {      // back on the shown bucket: drop any pending move
            pendingBucket_ = bucket;
            confirm_ = 0;
            return ev;
        }
        // Bucket differs from what's shown: require two agreeing samples to commit.
        if (bucket == pendingBucket_) {
            if (++confirm_ >= kConfirm) {
                shownBucket_ = bucket;
                confirm_ = 0;
                return ev == Event::LowAlarm ? ev : Event::BucketChanged;
            }
        } else {
            pendingBucket_ = bucket;
            confirm_ = 1;
        }
        return ev;
    }

    uint8_t percent() const {
        return shownBucket_ < 0 ? 0 : static_cast<uint8_t>(shownBucket_ * 5);
    }
    bool lowAlarm() const { return alarmed_; }

private:
    static constexpr int kEmaShift = 4;        // EMA alpha = 1/4
    static constexpr int kConfirm  = 2;        // consecutive samples to commit a bucket move
    static constexpr uint8_t kLowPct   = 10;   // fire alarm at/below this %
    static constexpr uint8_t kClearPct = 15;   // clear alarm at/above this % (hysteresis)

    bool     inited_  = false;
    uint32_t ema_     = 0;
    int      shownBucket_   = -1;  // 0..20, -1 until first sample
    int      pendingBucket_ = -1;
    int      confirm_ = 0;
    bool     alarmed_ = false;
};

}  // namespace locallexis::power
