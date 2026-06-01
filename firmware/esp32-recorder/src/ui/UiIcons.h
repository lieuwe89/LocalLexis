#pragma once

#include <Adafruit_GFX.h>

#include "ui/ScreenLayout.h"  // IconDraw, MeterDraw

namespace locallexis::ui {

// Execute one icon/meter against a GFX target. `color` is the foreground ink for
// THIS draw (the blitter passes BLACK on paper screens, WHITE on inverted ones,
// already resolved from IconDraw.invert / MeterDraw.invert).
void drawIcon(Adafruit_GFX& gfx, const IconDraw& ic, uint16_t color);
void drawMeter(Adafruit_GFX& gfx, const MeterDraw& mt, uint16_t color);

}  // namespace locallexis::ui
