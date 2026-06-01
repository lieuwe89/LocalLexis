# Recorder UI fonts

## Current state — Phase 2 (baked real fonts, ACTIVE)

`UiFonts.cpp` maps every `FontRole` to a baked 1-bit GFX font generated from
the exact OFL typefaces. Phase 1 (Adafruit built-in fallbacks) is retired.

---

## Baked font inventory

| Header | Source TTF | Size (px) | Glyph range | GFXfont symbol | FontRole |
|---|---|---|---|---|---|
| `Goudy40.h` | SortsMillGoudy-Regular.ttf | 40 | 0x20–0x7E (ASCII) | `Goudy40pt7b` | HeadXL |
| `Goudy33.h` | SortsMillGoudy-Regular.ttf | 33 | 0x20–0x7E (ASCII) | `Goudy33pt7b` | HeadL |
| `Goudy27.h` | SortsMillGoudy-Regular.ttf | 27 | 0x20–0x7E (ASCII) | `Goudy27pt7b` | HeadM |
| `JBMono32.h` | JetBrainsMono-Medium.ttf | 32 | 0x20–0x7E (ASCII) | `JBMono_Medium32pt7b` | NumL |
| `JBMono9.h` | JetBrainsMono-Regular.ttf | 9 | 0x20–0xB7 (+ middot U+00B7) | `JBMono_Regular9pt7b` | Caps |
| `JBMonoBold9.h` | JetBrainsMono-SemiBold.ttf | 9 | 0x20–0xB7 (+ middot U+00B7) | `JBMono_SemiBold9pt7b` | Pill |

The two 9 px mono headers include U+00B7 MIDDLE DOT (·) because it is used
as a separator character in footer labels.

---

## Source faces (all OFL-licensed)

### Sorts Mill Goudy Regular

- Repository: <https://github.com/google/fonts/tree/main/ofl/sortsmillgoudy>
- Download URL (as fetched 2026-06-01):
  `https://github.com/google/fonts/raw/main/ofl/sortsmillgoudy/SortsMillGoudy-Regular.ttf`
- Licence: SIL Open Font Licence 1.1 (`OFL.txt` in the Google Fonts repo)

### JetBrains Mono — STATIC weights (not the variable font from Google Fonts)

The Google Fonts copy is a variable font; fontconvert requires static TTFs.
Use the JetBrains upstream repo directly.

- Repository: <https://github.com/JetBrains/JetBrainsMono>
- Download URLs (as fetched 2026-06-01):
  - `https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Medium.ttf`
  - `https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Regular.ttf`
  - `https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-SemiBold.ttf`
- Licence: SIL Open Font Licence 1.1 (`OFL.txt` in the JetBrainsMono repo)
- Alternate host if JetBrains repo moves:
  `https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/fonts/ttf/<file>`

---

## Regenerating headers

### 1. Build fontconvert (freetype must be installed)

```bash
# from the firmware workspace root
cc $(pkg-config --cflags freetype2) \
   -o /tmp/fontconvert \
   ".pio/libdeps/waveshare-esp32-s3-epaper/Adafruit GFX Library/fontconvert/fontconvert.c" \
   $(pkg-config --libs freetype2)
```

### 2. Download TTFs

```bash
curl -fsSL -o /tmp/Goudy.ttf \
  https://github.com/google/fonts/raw/main/ofl/sortsmillgoudy/SortsMillGoudy-Regular.ttf
curl -fsSL -o /tmp/JBMono-Medium.ttf \
  https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Medium.ttf
curl -fsSL -o /tmp/JBMono-Regular.ttf \
  https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Regular.ttf
curl -fsSL -o /tmp/JBMono-SemiBold.ttf \
  https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-SemiBold.ttf
```

### 3. Generate headers

```bash
F=src/ui/fonts
/tmp/fontconvert /tmp/Goudy.ttf 40 0x20 0x7E  > $F/Goudy40.h        # FontRole::HeadXL
/tmp/fontconvert /tmp/Goudy.ttf 33 0x20 0x7E  > $F/Goudy33.h        # FontRole::HeadL
/tmp/fontconvert /tmp/Goudy.ttf 27 0x20 0x7E  > $F/Goudy27.h        # FontRole::HeadM
/tmp/fontconvert /tmp/JBMono-Medium.ttf 32 0x20 0x7E  > $F/JBMono32.h    # FontRole::NumL
/tmp/fontconvert /tmp/JBMono-Regular.ttf 9 0x20 0xB7  > $F/JBMono9.h     # FontRole::Caps
/tmp/fontconvert /tmp/JBMono-SemiBold.ttf 9 0x20 0xB7 > $F/JBMonoBold9.h # FontRole::Pill
```

Verify symbol names after generation:
```bash
grep 'const GFXfont' src/ui/fonts/*.h
```

### Include-order note

The font headers do NOT themselves include `<Adafruit_GFX.h>` — they emit raw
`const uint8_t` / `GFXglyph` / `GFXfont` literals. `UiFonts.h` includes
`<Adafruit_GFX.h>` before the font headers are pulled in via `UiFonts.cpp`,
so the typedefs are always defined first. No duplicate-definition workaround
is needed with this fontconvert version.

---

## Phase 1 (retired)

Phase 1 used Adafruit built-in fonts (`FreeSerif*` / `FreeMonoBold*`) as
fallbacks while the baked fonts were deferred. Phase 2 is now active and Phase 1
includes have been removed from `UiFonts.cpp`.
