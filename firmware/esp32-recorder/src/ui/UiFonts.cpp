#include "ui/UiFonts.h"
// Phase 2: baked 1-bit GFX fonts (Sorts Mill Goudy + JetBrains Mono static weights).
// UiFonts.h already includes <Adafruit_GFX.h>, so GFXglyph / GFXfont are defined
// before the font headers are expanded — no duplicate-typedef risk.
#include "ui/fonts/Goudy16.h"
#include "ui/fonts/Goudy13.h"
#include "ui/fonts/Goudy11.h"
#include "ui/fonts/JBMono16.h"
#include "ui/fonts/JBMono6.h"
#include "ui/fonts/JBMonoBold6.h"

namespace locallexis::ui {

const GFXfont* fontForRole(FontRole role) {
    switch (role) {
        case FontRole::HeadXL: return &Goudy16pt7b;
        case FontRole::HeadL:  return &Goudy13pt7b;
        case FontRole::HeadM:  return &Goudy11pt7b;
        case FontRole::NumL:   return &JBMono_Medium16pt7b;
        case FontRole::Caps:   return &JBMono_Regular6pt8b;
        case FontRole::Pill:   return &JBMono_SemiBold6pt8b;
    }
    return &JBMono_Regular6pt8b;
}

}  // namespace locallexis::ui
