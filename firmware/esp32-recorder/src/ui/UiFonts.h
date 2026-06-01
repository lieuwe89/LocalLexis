#pragma once

#include <Adafruit_GFX.h>  // GFXfont

#include "ui/ScreenLayout.h"  // FontRole

namespace locallexis::ui {

// Resolves a layout FontRole to a concrete 1-bit GFX font. Phase 1 returns the
// closest Adafruit built-in so the panel renders legibly before the exact
// Goudy/JetBrains fonts are baked (Step 3); Phase 2 swaps the bodies only.
const GFXfont* fontForRole(FontRole role);

}  // namespace locallexis::ui
