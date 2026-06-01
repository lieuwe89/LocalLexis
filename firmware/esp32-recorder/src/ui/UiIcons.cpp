#include "ui/UiIcons.h"

#include <Adafruit_GFX.h>

#include "ui/UiBitmaps.h"

namespace locallexis::ui {

// LEVELS from device-kit.jsx LevelMeter
static const uint8_t kLevels[] = {3, 6, 4, 9, 13, 7, 11, 16, 10, 6, 12, 18, 14, 8, 5, 10, 15, 9, 6, 11, 7, 4, 8, 5, 3};
static constexpr int kLevelsCount = static_cast<int>(sizeof(kLevels) / sizeof(kLevels[0]));

void drawIcon(Adafruit_GFX& gfx, const IconDraw& ic, uint16_t color) {
    const int16_t x = ic.x;
    const int16_t y = ic.y;
    const int16_t sz = ic.size > 0 ? ic.size : 12;

    switch (ic.id) {
        case IconId::Rec: {
            // fillCircle centered in sz×sz box
            int16_t r = sz / 2 - 1;
            if (r < 1) r = 1;
            gfx.fillCircle(x + sz / 2, y + sz / 2, r, color);
            break;
        }
        case IconId::Stop: {
            // fillRect — solid square, slight inset (matches device-kit 0.5px inset)
            gfx.fillRect(x, y, sz, sz, color);
            break;
        }
        case IconId::Check: {
            // Two drawLine segments forming the ✓ polyline: 2,7.5→5.5,11→12,3
            // scaled to sz (viewBox 14×14), strokeWidth≈2 → draw lines shifted by ±1
            // device-kit viewBox: 0 0 14 14
            // Scale factor:
            float sc = static_cast<float>(sz) / 14.0f;
            int16_t x0 = x + static_cast<int16_t>(2.0f  * sc);
            int16_t y0 = y + static_cast<int16_t>(7.5f  * sc);
            int16_t x1 = x + static_cast<int16_t>(5.5f  * sc);
            int16_t y1 = y + static_cast<int16_t>(11.0f * sc);
            int16_t x2 = x + static_cast<int16_t>(12.0f * sc);
            int16_t y2 = y + static_cast<int16_t>(3.0f  * sc);
            // Stroke width ~2: draw two passes (offset by 1 in perpendicular)
            gfx.drawLine(x0,   y0,   x1,   y1,   color);
            gfx.drawLine(x0,   y0+1, x1,   y1+1, color);
            gfx.drawLine(x1,   y1,   x2,   y2,   color);
            gfx.drawLine(x1,   y1+1, x2,   y2+1, color);
            break;
        }
        case IconId::Warn: {
            // Triangle outline (drawLine×3) + bang (fillRect stem + dot)
            // device-kit viewBox 0 0 15 13, but rendered in sz×sz
            // Triangle: M7.5 0.5 L14.3 12.4 L0.7 12.4 Z
            float scx = static_cast<float>(sz) / 15.0f;
            float scy = static_cast<float>(sz) / 13.0f;
            int16_t tx0 = x + static_cast<int16_t>(7.5f  * scx);
            int16_t ty0 = y + static_cast<int16_t>(0.5f  * scy);
            int16_t tx1 = x + static_cast<int16_t>(14.3f * scx);
            int16_t ty1 = y + static_cast<int16_t>(12.4f * scy);
            int16_t tx2 = x + static_cast<int16_t>(0.7f  * scx);
            int16_t ty2 = y + static_cast<int16_t>(12.4f * scy);
            gfx.drawLine(tx0, ty0, tx1, ty1, color);
            gfx.drawLine(tx1, ty1, tx2, ty2, color);
            gfx.drawLine(tx2, ty2, tx0, ty0, color);
            // Bang stem: x=6.8 y=4.2 w=1.4 h=4.2
            int16_t bx = x + static_cast<int16_t>(6.8f * scx);
            int16_t by = y + static_cast<int16_t>(4.2f * scy);
            int16_t bw = static_cast<int16_t>(1.4f * scx + 0.5f);
            if (bw < 1) bw = 1;
            int16_t bh = static_cast<int16_t>(4.2f * scy + 0.5f);
            if (bh < 1) bh = 1;
            gfx.fillRect(bx, by, bw, bh, color);
            // Dot: x=6.8 y=9.4 w=1.4 h=1.4
            int16_t dx = x + static_cast<int16_t>(6.8f * scx);
            int16_t dy = y + static_cast<int16_t>(9.4f * scy);
            int16_t dw = static_cast<int16_t>(1.4f * scx + 0.5f);
            if (dw < 1) dw = 1;
            int16_t dh = static_cast<int16_t>(1.4f * scy + 0.5f);
            if (dh < 1) dh = 1;
            gfx.fillRect(dx, dy, dw, dh, color);
            break;
        }
        case IconId::Sync: {
            // Two arcs approximated by drawCircleHelper + two arrowhead fillTriangle
            // device-kit viewBox 0 0 16 16, arc radius=5, center approximately (7.5,7)
            // Arc 1: M3.2 9.2 A5 5 0 0 1 12 4.4  (upper-right arc)
            // Arc 2: M12.8 6.8 A5 5 0 0 1 4 11.6 (lower-left arc)
            // Approximate arcs with drawCircleHelper quadrants
            float sc = static_cast<float>(sz) / 16.0f;
            int16_t cx = x + static_cast<int16_t>(7.6f * sc);
            int16_t cy = y + static_cast<int16_t>(7.0f * sc);
            int16_t r  = static_cast<int16_t>(5.0f * sc);
            if (r < 2) r = 2;
            // Upper-right arc (quadrants 0,1 = top-right, top-left → use 0 and 3)
            gfx.drawCircleHelper(cx, cy, r, 0b0001, color); // quadrant 0: top-right
            gfx.drawCircleHelper(cx, cy, r, 0b1000, color); // quadrant 3: bottom-left
            // Arrowhead 1: tip at approx 12,4.4 pointing up-right
            // 'M10 4.4 L12.4 3.4 L12.6 6.1 Z'
            int16_t ax0 = x + static_cast<int16_t>(10.0f * sc);
            int16_t ay0 = y + static_cast<int16_t>(4.4f  * sc);
            int16_t ax1 = x + static_cast<int16_t>(12.4f * sc);
            int16_t ay1 = y + static_cast<int16_t>(3.4f  * sc);
            int16_t ax2 = x + static_cast<int16_t>(12.6f * sc);
            int16_t ay2 = y + static_cast<int16_t>(6.1f  * sc);
            gfx.fillTriangle(ax0, ay0, ax1, ay1, ax2, ay2, color);
            // Arrowhead 2: tip at approx 4,11.6 pointing down-left
            // 'M6 11.6 L3.6 12.6 L3.4 9.9 Z'
            int16_t bx0 = x + static_cast<int16_t>(6.0f  * sc);
            int16_t by0 = y + static_cast<int16_t>(11.6f * sc);
            int16_t bx1 = x + static_cast<int16_t>(3.6f  * sc);
            int16_t by1 = y + static_cast<int16_t>(12.6f * sc);
            int16_t bx2 = x + static_cast<int16_t>(3.4f  * sc);
            int16_t by2 = y + static_cast<int16_t>(9.9f  * sc);
            gfx.fillTriangle(bx0, by0, bx1, by1, bx2, by2, color);
            break;
        }
        case IconId::Battery: {
            // device-kit: w=26, h=12, body=22×12, terminal=2.4×4.8, 4 cells
            // Scale: unit = sz/26, bw = 22*unit, h = 12*unit
            float unit = static_cast<float>(sz) / 26.0f;
            int16_t bw  = static_cast<int16_t>(22.0f * unit);
            int16_t bh  = static_cast<int16_t>(12.0f * unit);
            if (bw < 4) bw = 4;
            if (bh < 3) bh = 3;
            // Outline body
            gfx.drawRect(x, y, bw, bh, color);
            // Terminal: x=bw, y=h*0.3, w=2.4*unit, h=h*0.4
            int16_t tx = x + bw;
            int16_t ty = y + static_cast<int16_t>(bh * 0.3f);
            int16_t tw = static_cast<int16_t>(2.4f * unit + 0.5f);
            if (tw < 1) tw = 1;
            int16_t th = static_cast<int16_t>(bh * 0.4f + 0.5f);
            if (th < 1) th = 1;
            gfx.fillRect(tx, ty, tw, th, color);
            // Fill cells: arg = 0..4 filled
            const int segs = 4;
            const int fill = ic.arg < static_cast<uint8_t>(segs) ? ic.arg : segs;
            float gap    = 1.6f * unit;
            float innerW = static_cast<float>(bw) - 4.0f * unit;
            float cellW  = (innerW - gap * (segs - 1)) / segs;
            if (cellW < 1.0f) cellW = 1.0f;
            int16_t cellH = bh - static_cast<int16_t>(4.0f * unit + 0.5f);
            if (cellH < 1) cellH = 1;
            for (int i = 0; i < fill; ++i) {
                int16_t cx2 = x + static_cast<int16_t>(2.0f * unit + i * (cellW + gap));
                int16_t cy2 = y + static_cast<int16_t>(2.0f * unit);
                int16_t cw2 = static_cast<int16_t>(cellW + 0.5f);
                if (cw2 < 1) cw2 = 1;
                gfx.fillRect(cx2, cy2, cw2, cellH, color);
            }
            break;
        }
        case IconId::Signal: {
            // device-kit: total=4 bars, w=16, h=12, bw=2.6, gap=1.6
            // bar height: h*(0.32 + 0.68*(i/(total-1)))
            // arg = number of filled bars (0..4)
            const int total = 4;
            float unit = static_cast<float>(sz) / 16.0f;
            float bw   = 2.6f * unit;
            float gap  = 1.6f * unit;
            float h    = 12.0f * unit;
            const int filled = ic.arg <= static_cast<uint8_t>(total) ? ic.arg : total;
            for (int i = 0; i < total; ++i) {
                float bh_f = h * (0.32f + 0.68f * (static_cast<float>(i) / static_cast<float>(total - 1)));
                int16_t bh2 = static_cast<int16_t>(bh_f + 0.5f);
                if (bh2 < 1) bh2 = 1;
                int16_t bx2 = x + static_cast<int16_t>(i * (bw + gap));
                int16_t by2 = y + static_cast<int16_t>(h) - bh2;
                int16_t bw2 = static_cast<int16_t>(bw + 0.5f);
                if (bw2 < 1) bw2 = 1;
                if (i < filled) {
                    gfx.fillRect(bx2, by2, bw2, bh2, color);
                } else {
                    gfx.drawRect(bx2, by2, bw2, bh2, color);
                }
            }
            break;
        }
        case IconId::BtBitmap: {
            // packBitmap into static scratch, then drawBitmap
            const auto& bmp = btBitmap();
            const int stride = (bmp.w + 7) / 8;
            static uint8_t sBtBuf[2 * 13];  // stride=2 (9px), 13 rows
            packBitmap(bmp, sBtBuf, sizeof(sBtBuf));
            gfx.drawBitmap(x, y, sBtBuf, bmp.w, bmp.h, color);
            break;
        }
        case IconId::FullBitmap: {
            // packBitmap into static scratch, then drawBitmap
            const auto& bmp = fullBitmap();
            const int stride = (bmp.w + 7) / 8;
            static uint8_t sFullBuf[2 * 13];  // stride=2 (13px), 13 rows
            packBitmap(bmp, sFullBuf, sizeof(sFullBuf));
            gfx.drawBitmap(x, y, sFullBuf, bmp.w, bmp.h, color);
            break;
        }
        default:
            break;
    }
}

void drawMeter(Adafruit_GFX& gfx, const MeterDraw& mt, uint16_t color) {
    switch (mt.id) {
        case MeterId::Block: {
            // n cells across w; first k filled (fillRect), rest outline (drawRect, 1px)
            // gap=2px between cells (matches device-kit gap=2)
            const int n   = mt.n > 0 ? mt.n : 1;
            const int k   = mt.k <= static_cast<uint8_t>(n) ? mt.k : n;
            const int gap = 2;
            float cw_f = (static_cast<float>(mt.w) - gap * (n - 1)) / static_cast<float>(n);
            if (cw_f < 1.0f) cw_f = 1.0f;
            for (int i = 0; i < n; ++i) {
                int16_t cx = mt.x + static_cast<int16_t>(i * (cw_f + gap));
                int16_t cw = static_cast<int16_t>(cw_f + 0.5f);
                if (cw < 1) cw = 1;
                if (i < k) {
                    gfx.fillRect(cx, mt.y, cw, mt.h, color);
                } else {
                    gfx.drawRect(cx, mt.y, cw, mt.h, color);
                }
            }
            break;
        }
        case MeterId::Level: {
            // n vertical bars at LEVELS[] heights (purely decorative frozen waveform)
            // device-kit: bw=2.4, gap=(w - count*bw)/(count-1)
            const int count = mt.n > 0 ? mt.n : 22;
            float bw_f = 2.4f;
            float gap_f = count > 1
                ? (static_cast<float>(mt.w) - count * bw_f) / static_cast<float>(count - 1)
                : 0.0f;
            if (gap_f < 0.0f) gap_f = 0.0f;
            for (int i = 0; i < count; ++i) {
                float v   = static_cast<float>(kLevels[i % kLevelsCount]) / 18.0f;
                float bh_f = v * static_cast<float>(mt.h);
                if (bh_f < 2.0f) bh_f = 2.0f;
                int16_t bh = static_cast<int16_t>(bh_f + 0.5f);
                int16_t bw = static_cast<int16_t>(bw_f + 0.5f);
                if (bw < 1) bw = 1;
                int16_t bx = mt.x + static_cast<int16_t>(i * (bw_f + gap_f));
                // Centered vertically (alignItems: center)
                int16_t by = mt.y + (mt.h - bh) / 2;
                gfx.fillRect(bx, by, bw, bh, color);
            }
            break;
        }
        default:
            break;
    }
}

}  // namespace locallexis::ui
