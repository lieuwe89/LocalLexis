#include <cassert>
#include <cstdint>
#include <iostream>

#include "power/BatteryGauge.h"

using locallexis::power::BatteryGauge;
using Event = locallexis::power::BatteryGauge::Event;

namespace {

// Feed the same voltage n times; return how many BucketChanged events were seen.
int feed(BatteryGauge& g, uint32_t mv, int n) {
    int changes = 0;
    for (int i = 0; i < n; ++i)
        if (g.update(mv) == Event::BucketChanged) ++changes;
    return changes;
}

}  // namespace

int main() {
    // A) Pure voltage->% curve: endpoints, clamps, midpoint.
    assert(BatteryGauge::levelFromMilliVolts(3000) == 0);
    assert(BatteryGauge::levelFromMilliVolts(4120) == 100);
    assert(BatteryGauge::levelFromMilliVolts(2500) == 0);    // below empty -> clamp
    assert(BatteryGauge::levelFromMilliVolts(4500) == 100);  // above full  -> clamp
    assert(BatteryGauge::levelFromMilliVolts(3560) == 50);   // exact midpoint

    // B) First reading is adopted immediately (no warm-up); reports a change.
    {
        BatteryGauge g;
        assert(g.update(4120) == Event::BucketChanged);
        assert(g.percent() == 100);
        assert(!g.lowAlarm());
    }

    // C) High -> low settles to the right bucket, stepping down monotonically.
    {
        BatteryGauge g;
        feed(g, 4120, 30);
        assert(g.percent() == 100);
        uint8_t prev = g.percent();
        bool sawChange = false;
        bool sawAlarm = false;
        for (int i = 0; i < 40; ++i) {
            const Event e = g.update(3560);  // 50%
            if (e == Event::BucketChanged) sawChange = true;
            if (e == Event::LowAlarm) sawAlarm = true;
            assert(g.percent() <= prev);     // never bounces back up while discharging
            prev = g.percent();
        }
        assert(g.percent() == 50);
        assert(sawChange);
        assert(!sawAlarm);                   // 50% never trips the low alarm
    }

    // D) Anti-bounce: a reading wobbling across a 5% boundary must NOT flip the
    //    display or emit repeated refreshes.
    {
        BatteryGauge g;
        feed(g, 3560, 40);                   // settle on 50%
        assert(g.percent() == 50);
        int changes = 0;
        for (int i = 0; i < 40; ++i) {
            const uint32_t mv = (i % 2 == 0) ? 3585 : 3535;  // straddles the 50% bucket edge
            if (g.update(mv) == Event::BucketChanged) ++changes;
            assert(g.percent() == 50);
        }
        assert(changes == 0);
    }

    // E) Low-battery alarm: fires once (latched), clears only with hysteresis.
    {
        BatteryGauge g;
        int alarms = 0;
        for (int i = 0; i < 40; ++i)
            if (g.update(3000) == Event::LowAlarm) ++alarms;  // 0%
        assert(alarms == 1);                 // latched: exactly one alarm event
        assert(g.lowAlarm());

        for (int i = 0; i < 60; ++i) g.update(3700);  // ~62%, well above clear threshold
        assert(!g.lowAlarm());               // hysteresis cleared the alarm
        assert(g.percent() >= 55);
    }

    std::cout << "test_battery_gauge: OK" << std::endl;
    return 0;
}
