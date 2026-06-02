#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <vector>

#include "audio/DcBlocker.h"

using locallexis::audio::DcBlocker;

namespace {
constexpr double kPi = 3.14159265358979323846;
}

int main() {
    // A) A constant DC input decays to ~0 (HPF DC gain is zero).
    {
        DcBlocker f;
        int16_t y = 0;
        for (int i = 0; i < 4000; ++i) y = f.process(17000);
        assert(std::abs(static_cast<int>(y)) < 5);  // +17k bias fully removed
    }

    // B) DC + 300 Hz tone: bias removed, AC amplitude preserved.
    {
        DcBlocker f;
        const double dc = 17000.0, amp = 8000.0;
        std::vector<int> outs;
        for (int n = 0; n < 3200; ++n) {
            const double x = dc + amp * std::sin(2.0 * kPi * 300.0 * n / 16000.0);
            const int16_t xi = static_cast<int16_t>(std::lround(x));  // 25k peak, no clip
            const int16_t y = f.process(xi);
            if (n >= 1600) outs.push_back(y);  // steady state only
        }
        double mean = 0.0;
        int peak = 0;
        for (int v : outs) { mean += v; peak = std::max(peak, std::abs(v)); }
        mean /= static_cast<double>(outs.size());
        assert(std::abs(mean) < 200);            // DC gone
        assert(peak > 6000 && peak < 9000);      // ~8000 AC preserved
    }

    // C) processBytes == per-sample process, with correct LE pack/unpack
    //    (incl. negative + rail values).
    {
        DcBlocker fa, fb;
        const std::vector<int16_t> samp = {
            -10000, 0, 12345, -32768, 32767, 100, 17000, 17000};
        std::vector<uint8_t> buf;
        for (int16_t s : samp) {
            buf.push_back(static_cast<uint8_t>(s & 0xff));
            buf.push_back(static_cast<uint8_t>((s >> 8) & 0xff));
        }
        fa.processBytes(buf.data(), buf.size());
        for (size_t i = 0; i < samp.size(); ++i) {
            const int16_t expect = fb.process(samp[i]);
            const int16_t got = static_cast<int16_t>(
                static_cast<uint16_t>(buf[2 * i]) |
                (static_cast<uint16_t>(buf[2 * i + 1]) << 8));
            assert(got == expect);
        }
    }

    // D) reset() clears state: same input sequence yields identical output.
    {
        DcBlocker f;
        const int16_t a = f.process(12000);
        f.reset();
        const int16_t b = f.process(12000);
        assert(a == b);
    }

    std::cout << "test_dc_blocker: OK" << std::endl;
    return 0;
}
