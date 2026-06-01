#pragma once

#include <cstddef>
#include <cstdint>

namespace locallexis::ui {

// Source rows transcribed verbatim from device-kit.jsx MAP.* ('#'=ink, ' '=paper).
struct BitmapSrc { const char* const* rows; int w, h; };

// bt: 9x13 Bluetooth glyph
extern const char* const kBtRows[13];
// full: 13x13 SD/storage glyph
extern const char* const kFullRows[13];
// mic: 10x16 (available; unused in Expressive)
extern const char* const kMicRows[16];

const BitmapSrc& btBitmap();
const BitmapSrc& fullBitmap();
const BitmapSrc& micBitmap();

// Pack a '#'/' ' row-string bitmap into MSB-first bytes (row-padded to whole
// bytes), the layout Adafruit_GFX::drawBitmap consumes. Returns bytes written.
// out must hold ((w + 7) / 8) * h bytes.
size_t packBitmap(const BitmapSrc& src, uint8_t* out, size_t outCap);

}  // namespace locallexis::ui
