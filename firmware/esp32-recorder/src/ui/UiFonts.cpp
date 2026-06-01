#include "ui/UiFonts.h"

#include <Fonts/FreeSerif24pt7b.h>
#include <Fonts/FreeSerif18pt7b.h>
#include <Fonts/FreeSerifBold12pt7b.h>
#include <Fonts/FreeMonoBold18pt7b.h>
#include <Fonts/FreeMonoBold9pt7b.h>

namespace locallexis::ui {

const GFXfont* fontForRole(FontRole role) {
    switch (role) {
        case FontRole::HeadXL: return &FreeSerif24pt7b;       // ~Goudy 38-44
        case FontRole::HeadL:  return &FreeSerif18pt7b;       // ~Goudy 32-34
        case FontRole::HeadM:  return &FreeSerifBold12pt7b;   // ~Goudy 27
        case FontRole::NumL:   return &FreeMonoBold18pt7b;    // ~mono 30-34
        case FontRole::Caps:   return &FreeMonoBold9pt7b;     // ~mono 9 caps
        case FontRole::Pill:   return &FreeMonoBold9pt7b;     // ~mono 8.5 (smallest avail)
    }
    return &FreeMonoBold9pt7b;
}

}  // namespace locallexis::ui
