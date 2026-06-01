# Recorder UI fonts

## Current state — Phase 1 (built-in fallback, ACTIVE)

`UiFonts.cpp` maps every `FontRole` to the closest Adafruit-GFX built-in
(`FreeSerif*` / `FreeMonoBold*`). The panel renders legibly with these; no
generated tables are bundled yet. `ScreenLayout` is font-role-agnostic, so
swapping in the exact faces later touches **only** `UiFonts.cpp`.

## Phase 2 — bake the exact 1-bit fonts (DEFERRED → batched manual session)

Needs `freetype` + Adafruit-GFX's `fontconvert`, and the OFL TTFs below. Not
done in the build-ahead pass because it pulls external toolchain + font assets;
batch it with the on-device acceptance session.

### Source faces (all OFL)

- **Sorts Mill Goudy** (Goudy Old Style revival) — `SortsMillGoudy-Regular.ttf`
- **JetBrains Mono** — `JetBrainsMono-Medium.ttf`, `-Regular.ttf`, `-SemiBold.ttf`
- **Silkscreen** (optional) — `Silkscreen-Regular.ttf`

Record exact download URLs, versions, and licences here when fetched.

### Build fontconvert once

```bash
# from the Adafruit-GFX-Library checkout, fontconvert/ dir:
cc -I/usr/include/freetype2 -o fontconvert fontconvert.c -lfreetype
```

### Generate (size arg = pixels; restrict to ASCII 0x20–0x7E)

| Output header | Source TTF | Sizes (px) | Role(s) |
|---|---|---|---|
| `Goudy44.h` / `Goudy39.h` / `Goudy38.h` / `Goudy40.h` | SortsMillGoudy-Regular.ttf | 44 / 39 / 38 / 40 | HeadXL |
| `Goudy34.h` / `Goudy32.h` | SortsMillGoudy-Regular.ttf | 34 / 32 | HeadL |
| `Goudy27.h` | SortsMillGoudy-Regular.ttf | 27 | HeadM |
| `JBMono34.h` / `JBMono30.h` | JetBrainsMono-Medium.ttf | 34 / 30 | NumL |
| `JBMono9.h` | JetBrainsMono-Regular.ttf | 9 | Caps |
| `JBMonoBold9.h` | JetBrainsMono-SemiBold.ttf | 9 | Pill |

```bash
./fontconvert SortsMillGoudy-Regular.ttf 44 0x20 0x7E > Goudy44.h
./fontconvert JetBrainsMono-Medium.ttf  30 0x20 0x7E > JBMono30.h
```

To avoid near-identical serif tables you MAY bake **one** representative size
per role (e.g. HeadXL=40, HeadL=33) and accept ≤2 px drift — note the choice
here. Then flip `UiFonts.cpp` to include the generated headers (Phase 2) and
drop the built-in includes once every role is covered.
