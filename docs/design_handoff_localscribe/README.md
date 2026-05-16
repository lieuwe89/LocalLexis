# Handoff: LocalScribe Desktop UI

## Overview

LocalScribe is a cross-platform desktop GUI for the existing `stt` CLI / `speechtotext` Python package. It wraps the CLI in a Tauri shell and adds a transcript library, drop-zone transcribe flow, in-app recording, and a watch-folder mode. The design is privacy-forward: nothing leaves the user's machine, and that posture is reinforced through subtle UI cues (an "On-device" chip in the header, a quiet live dot in the sidebar footer, a manuscript metaphor throughout).

The full product spec lives in `2026-05-15-stt-desktop-ui-design.md` (architecture, API contract, error handling, build sequence). This handoff covers the **UI layer** only — what's been visually designed and prototyped.

## About the Design Files

The files in this bundle are **design references created in HTML** — interactive prototypes showing the intended look and behavior, not production code to copy directly.

The target codebase is **Tauri + React + Vite** (per the spec). The task is to recreate these HTML designs in that environment using whatever component library / styling system the codebase establishes. The HTML uses React via Babel-in-browser purely so the prototypes can run from a single file; production should use a normal React build pipeline.

To run the prototype:

- **Recommended:** open `LocalScribe-standalone.html` — fully self-contained, runs offline by double-clicking.
- **Source files:** the split source (`LocalScribe.html` + `*.jsx` + `styles.css`) is easier to read. Serve from a local HTTP server (e.g. `python -m http.server`); opening directly via `file://` may fail to load the sibling `.jsx` files in some browsers.

## Fidelity

**High-fidelity** for the three priority screens: Idle (drop-zone), Record, and Complete (relabel + transcript). All colors, type, spacing, and interactions are final and should be recreated pixel-close.

**Low-fidelity placeholders** for Library, Watch folder, and Settings — these render as a single centered "stub" card so the prototype's sidebar nav doesn't have dead ends. The spec describes their intended content; treat them as TODO and design/build them out before shipping.

## Screens / Views

The app is a single window split into a fixed-width left sidebar (`232px`) and a flexible main panel. macOS chrome (titlebar with traffic lights) is on by default — togglable to "plain" via the Tweaks panel.

### Sidebar (constant across all views)

- **Brand block** (padding `4px 18px 16px`):
  - Wordmark "LocalScribe" — Newsreader serif, 22px / 500, color `--ink` (`#ece9e1`), letter-spacing `-0.01em`.
  - Pronunciation guide "/ˈloʊkəlˌskraɪb/ · v1.0" — Newsreader italic, 10.5px, color `--ink-dim`.
- **"+ New transcription" button** (margin `0 14px 14px`, height 34px):
  - Inverted: bg `--ink` (off-white `#ece9e1`), text `--bg` (near-black `#0c0c0d`).
  - Leading `+` icon (13px), trailing keyboard hint `⌘N` in mono.
  - Hover: bg `#fff`.
- **Nav items** (height 30px, padding `0 10px`, gap 10):
  - `Transcribe`, `Record`, `Watch folder`, `Library` (with `47` count badge), `Settings`.
  - Inactive: color `--ink-muted`. Hover: bg `--bg-hover`, color `--ink`. Active: bg `--bg-active` + a `2px × ~16px` accent-green bar at `left: -8px` (a marginal tick into the gutter — a manuscript marginalia cue).
  - When the user is recording, the Record nav item shows a pulsing accent-green `live-dot` in place of any badge.
- **Recent section**: a `RECENT` label (mono, 9.5px, uppercase, letter-spacing `0.14em`) followed by ~5 transcript rows. Each row: title (13px), meta line below in mono 10.5px (`duration · relative-date`). Hover highlights.
- **Sidebar footer** (margin-top auto, border-top `--line`): "All processing on-device" in mono 10.5px with a `6px × 6px` accent-green dot (with a `--accent-faint` halo) on the left.

### Main panel header (constant)

- Height 52px, padding `0 28px`, bottom border `--line`.
- Left: a route crumb (mono 11px, `--ink-dim`) followed by the route title (14px / 500, `--ink`). Both single-line with ellipsis.
- Right cluster: contextual chips, all `24px` tall, `999px` radius, mono 11.5px, border `--line`, bg `--bg-elev`:
  - On Complete: a `--accent` check chip "Done in 4:12".
  - On Record: a `chip.accent` (accent-faint bg, accent-line border, accent color) with a pulsing green dot — "Live".
  - Always: an "On-device" chip with a lock icon — the persistent privacy signal.

### 1. Idle / New transcription

The default landing. Max-width `760px`, centered, padding `56px 40px 60px`, vertical rhythm via `gap: 32px`.

- **Hero**: `<h1>` "What did you *say*?" — Newsreader 44px / 400, line-height 1.05, letter-spacing `-0.015em`, `text-wrap: balance`. The `<em>` ("say") is italic at weight 300 and color `--ink-muted` — a quiet emphasis on the verb.
- Subhead `<p>`: 14.5px, `--ink-muted`, max-width 56ch, line-height 1.55. Copy: "Drop an audio file to transcribe it on this machine. Nothing leaves your device — models, audio and transcripts all live in your filesystem."
- **Drop zone**:
  - Padding `56px 32px`, radius 14px, border `1px dashed --line-strong`, bg = `--bg-elev` plus a 45° hatched overlay (`repeating-linear-gradient(45deg, transparent 0 12px, rgba(255,255,255,0.012) 12px 13px)`) for subtle paper-tooth texture.
  - Contents (centered, gap 16px): a 48px upload glyph (1.3-weight stroke, `--ink-muted`), an `<h2>` "Drag an audio file here" (Newsreader 22px / 400), a mono 13px subtitle of accepted extensions (`.mp3 · .m4a · .wav · .ogg · .flac · .webm` — single line, ellipsis), a horizontal "or" divider, and a ghost "Browse files…" button.
  - Hover / drag-over state: border switches to `--accent-line`, hatch gradient switches to `--accent-faint`. Same transition on real `dragenter`/`dragover` (the prototype wires this up; `dragleave`/`drop` reset).
- **Options row**: 3-column grid, gap 12px. Each "option" card: radius 10px, bg `--bg-elev`, border `--line`, padding `14px 14px 12px`. Inside: uppercase mono label ("LANGUAGE", "SPEAKERS", "BACKEND") followed by the current value and a chevron. Hover lifts to `--bg-hover` + `--line-strong`.
  - Defaults: `Auto-detect`, `Auto`, `faster-whisper`. The dropdowns aren't built — wire to the API contract (`GET /devices`, `GET /config`).
- **Recent files list**: a section with a `RECENT FILES` mono label, then 3 rows. Each row is a 5-col grid (`22px 1fr auto auto auto`, gap 14px): file icon, monospaced filename, duration, speaker count, relative date — separated by 0.5px row dividers (`--line-faint`).
- **Etymology card**: a deliberate flourish at the bottom. Bg `--bg-elev`, border `--line`, radius 12px. A Newsreader italic head defining "scribe / skraɪb · noun" followed by a brief etymology. This is the only piece of "marketing copy" in the UI — it carries the metaphor.

### 2. Record

Full-bleed centered layout, padding `40px 40px 32px`, gap 24px, items center-aligned.

- **Device bar** at top: a pill (height ~36px, padding `6px 12px 6px 14px`, radius 999px, bg `--bg-elev`, border `--line`). Contents: a "INPUT" label (mono 10px uppercase), a borderless `<select>` for input device (MacBook Pro Microphone / AirPods Pro / Shure SM7B), a separator dot, "48 kHz · mono". Whole bar is `white-space: nowrap`. Wire to `GET /devices`.
- **Scribe canvas** (the seismograph): the hero piece. Max-width 880px, `flex: 1`, min-height 280px, radius 14px, border `--line`, bg = `--bg-elev` plus a soft radial accent-green glow at center. Inside:
  - A custom SVG waveform renderer (`<Waveform>` in `screens.jsx`). 140 vertical bars across the canvas, deterministic-noise heights modulated by an envelope that ramps from quiet on the left ("past") to tall on the right ("now"). Each frame, `requestAnimationFrame` increments a `phase` value so the bars wobble — the visual metaphor of audio being inscribed onto paper, traveling right to left. The 3 right-most bars are slightly thicker + brighter (the "current moment"). A dashed vertical playhead line sits 34px from the right edge.
  - All strokes inherit `color: var(--accent)` (use `currentColor` for swatch flexibility).
  - Below the waveform, a row of mono 10px time marks: `−60s −45s −30s −15s now` — a manuscript-y x-axis.
- **Timer block**: a status label (mono 10px uppercase letter-spacing 0.14em — colored accent green when recording, with a leading pulsing `8px` green dot; warn-orange when paused; ink-dim when idle), and below it the big mono timer: `mm:ss` in Geist Mono 56px / 300 / tabular-nums, followed by an `.ms` decimal in 18px ink-dim. The whole stack left-aligned.
- **Controls** (row, gap 14px, center):
  - Secondary "Pause / Resume" pill button (mono 12.5px, bg `--bg-elev`, border `--line-strong`, 38px tall, pause icon).
  - Primary record button: 64px circle, bg `--bg-elev`, border `--line-strong`. The inner disc is `30px × 30px`, `border-radius: 50%`, color `--danger` when idle. When recording, the inner morphs (CSS transition 180ms ease) to a `22px` rounded square — universal "stop" iconography. Active scale 0.96.
  - Secondary "Discard" button — same chrome as Pause, but `color: --danger`.
- **Privacy note**: a single quiet line in mono 10.5px, color `--ink-dim`: a lock glyph, then "Audio is captured to disk · `~/Recordings/voice-memo-020.wav` · never sent over the network." The filename in inline mono.

### 3. Complete

Max-width 920px, padding `36px 40px 80px`. The design intent is **a typeset manuscript** — speaker names italic like a play script, monospaced timestamps in a left gutter.

- **Doc head** (bottom border `--line`, padding-bottom 22px, flex row):
  - File meta (mono 10px uppercase letter-spacing 0.12em, `--ink-dim`): the audio's absolute path on disk, separated by a faint mid-dot from "local". Establishes that the underlying file is real and on the user's machine.
  - `<h1>`: Newsreader 36px / 400, line-height 1.1, letter-spacing `-0.012em`, color `--ink`. The transcript title — derived from filename or first-line. The prototype uses "Meeting · privacy & the scribe metaphor".
  - Sub-line (mono 13px, `--ink-muted`): duration, speaker count, language, model used (`whisper-large-v3`), date — separated by `--ink-faint` mid-dots. Surfacing the model is intentional and reinforces trust.
  - Right cluster: three 32px icon buttons (Copy, Open .txt, Open .json). Transparent bg by default, hover adds `--line` border and `--bg-hover`.
- **Relabel row** (margin-top 22px, bg `--bg-elev`, border `--line`, radius 10px, padding `14px 16px`, vertical gap 12px):
  - Head row: a "SPEAKERS · 3 DETECTED" mono label on the left, an "Apply" button on the right (`--accent` bg, height 30px, radius 7px, 12px / 500). When all fields are unchanged: button shows "✓ Applied" and is disabled (bg `--bg-elev`, color `--ink-dim`). Editing any field re-enables the button.
  - Body: a responsive grid (`auto-fill, minmax(220px, 1fr)`, gap 8px). Each row has a small `8px` colored swatch (`SPEAKER_COLORS[i]`), the source label `SPEAKER_0i` in mono `--ink-dim`, a right-arrow glyph, and an input. Input has `--bg` bg, `--line-strong` border, radius 6px, 13px sans, focuses with accent border + `--bg-elev-2` bg.
  - Wire to `PATCH /transcripts/{id}/relabel` — body shape `{ "SPEAKER_00": "Alice", ... }` per the spec.
- **Transcript** (margin-top 28px):
  - Default view ("margin"): a 3-column grid per turn — `70px 110px 1fr`, gap 18px. The 70px is the right-aligned mono timestamp (11px, tabular-nums, `--ink-dim`), the 110px is the speaker block (Newsreader italic 14px, `--ink-muted`, leading 7px colored dot — `SPEAKER_COLORS[turn.spk]`), the 1fr is the body paragraph (Newsreader 17px / 1.7, color `--ink`, `text-wrap: pretty`).
  - Alternate view ("inline"): grid collapses to a single column. The speaker name moves above the paragraph, with the timestamp appended after it via `data-ts` attribute + `::after` — mono 10.5px ink-faint. Padding per turn increases from 10px to 14px to compensate for the lost gutter.
  - Density variants: `comfy` (default, 17px / 1.7) or `compact` (15px / 1.55, 6px per-turn padding). Toggle in Tweaks.

### 4. Library / Watch folder / Settings — STUBS

Each renders the same `<StubScreen>` component: a 36px outline icon, an `<h2>` (Newsreader 28px), a one-paragraph description, centered, max-width 600px. Replace with the real implementations per the spec:

- **Library**: search box + transcript list (one row per `.json` sidecar). Wire to `GET /transcripts`.
- **Watch folder**: folder picker, start/stop toggle, recent-events log. Wire to `POST /watch/start`, `POST /watch/stop`, `GET /watch/status`.
- **Settings**: form editor for `config.toml`. Wire to `GET /config`, `PATCH /config`.

## Interactions & Behavior

- **Sidebar nav** sets a top-level `route` state. Clicking any recent-transcript row in the sidebar deep-links to the Complete view. Clicking the "+ New" button or "Transcribe" nav both lead to Idle.
- **Idle → Complete**: in the prototype, both `drop` events on the drop zone and clicks on "Browse files…" jump straight to Complete for demo purposes. In production: those should `POST /jobs/transcribe`, navigate to an in-progress (state 2) view, subscribe to `GET /jobs/{id}/stream` (SSE), and on `complete` event transition to the Complete view.
- **In-progress state (NOT designed)**: the spec defines a state 2 (progress bar, stage list `Load → Diarize → Transcribe → Merge → Write`, live-streaming transcript). The prototype skips this — it should be designed before build. Suggestion: reuse the Complete view's transcript typography but with a top progress strip + a single highlighted stage chip.
- **Record screen**: `recording` and `paused` are local state. A `setInterval` advances `elapsed` 10×/sec when recording and not paused. The record button toggles recording (and resets elapsed if starting fresh). The waveform's `useEffect` only schedules `requestAnimationFrame` while recording — when stopped/paused, the animation halts. Wire to `POST /jobs/record` + `POST /jobs/{id}/stop`.
- **Relabel**: editing any input flips an `applied` boolean to false (re-enabling the Apply button). Apply sets it back to true (in production: `PATCH .../relabel` then re-fetch).
- **Tweaks panel**: bottom-right floating, toggled by the platform's "Tweaks" toolbar control. Exposes: `Chrome` (macOS / Plain), `Layout` (Margin ts / Inline ts), `Density` (Compact / Comfy), `Speaker colors` toggle, plus a quick-jump grid for every route. Defaults persist via the `EDITMODE-BEGIN/END` markers in the HTML.

## State Management

For a React + Tauri implementation, expect roughly:

- A top-level router (current screen).
- A `jobs` store keyed by `job_id`, holding `{ status, stage, percent, transcript: [...], error? }`. Populated from SSE.
- A `transcripts` store — keyed by transcript id, lazily populated from `GET /transcripts/{id}`. Updated optimistically on relabel.
- A `library` store — array of transcript metadata from `GET /transcripts`, refreshed on `complete` events.
- A `recording` store — `{ active, paused, elapsed, deviceId, jobId? }`.
- A `config` store — read once on launch, mutated via `PATCH /config`.

All UI state is local component state (open dropdowns, drag-over, input focus, etc.).

## Design Tokens

All defined as CSS custom properties on `:root` in `styles.css`.

**Colors:**

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0c0c0d` | Main panel background |
| `--bg-sidebar` | `#08080a` | Sidebar background |
| `--bg-elev` | `#131315` | Cards, drop zone, chips, option tiles |
| `--bg-elev-2` | `#1a1a1d` | Hover / focused input |
| `--bg-hover` | `#18181b` | Nav-item & icon-button hover |
| `--bg-active` | `#1f1f22` | Active nav item background |
| `--line` | `#1f1f22` | Default borders, dividers |
| `--line-strong` | `#2a2a2e` | Drop-zone dash, input border |
| `--line-faint` | `#161618` | List row dividers |
| `--ink` | `#ece9e1` | Primary text (warm off-white) |
| `--ink-muted` | `#a8a59b` | Secondary text |
| `--ink-dim` | `#65635c` | Tertiary text, mono captions |
| `--ink-faint` | `#3a3935` | Separators, very dim text |
| `--accent` | `#6fd99a` | Live / active / Apply / record waveform |
| `--accent-deep` | `#2faa66` | Reserved (hover for accent surfaces) |
| `--accent-faint` | `rgba(111,217,154,0.10)` | Accent chip bg, halos |
| `--accent-line` | `rgba(111,217,154,0.35)` | Accent borders |
| `--warn` | `#d97757` | Paused state |
| `--danger` | `#e0584b` | Record button dot, Discard text |

**Speaker accent palette** (`SPEAKER_COLORS` in `primitives.jsx`):
`#6fd99a` · `#e8b169` · `#7aa5e8` · `#d97e94` · `#c2a3e8` — five muted hues, used round-robin.

**Typography (all from Google Fonts):**

- **`--serif`**: `'Newsreader'` — display, headlines, transcript body, brand wordmark. Variable axes: optical size 6..72, weight 300..700, italic. Use weight 400 for headings; italic for the brand pron and speaker names.
- **`--sans`**: `'Geist'` — all UI body text, buttons, nav. Weights 300..700. Default 14px.
- **`--mono`**: `'Geist Mono'` — every label, timestamp, file path, technical chip. Weights 300..600.

Type scale used:
- Hero `<h1>`: 44px serif / 400 / -0.015em / 1.05 line-height
- Doc head `<h1>`: 36px serif / 400 / -0.012em / 1.1
- Section `<h2>`: 22–28px serif / 400
- Body large (transcript): 17px serif / 1.7
- Body: 13–14.5px sans / 1.55
- Mono labels: 10–11.5px / uppercase / 0.12–0.14em letter-spacing
- Timer: 56px mono / 300 / tabular-nums

**Spacing**: no formal scale — uses an ad-hoc 4/6/8/10/12/14/16/18/22/28/32/40/56px progression. The layout grid breathes at multiples of 4.

**Radii** (`--rad` 10px, `--rad-sm` 6px exist but most usages are explicit): nav items 6px, options 10px, drop zone 14px, chips 999px, window 12px, titlebar 0.

**Shadows**: window only — `0 0 0 0.5px rgba(255,255,255,0.06), 0 30px 80px rgba(0,0,0,0.5), 0 12px 30px rgba(0,0,0,0.4)`. No other elevation shadows; everything else uses borders.

## Assets

No bitmap or external image assets. All iconography is hand-drawn inline SVG in `primitives.jsx` (`<Icon name=... />`): plus, transcribe, mic, eye, folder, book, gear, upload, chev, copy, doc, braces, wave, shield, lock, sparkle, pause, check, search. They're a single weight-1.5 stroke style — keep the consistent look when adding more.

Logo: text-only wordmark in Newsreader. The user has indicated they'll provide a real mark later; leave space in the brand block.

## Files

- `LocalScribe.html` — entry: font imports, root mount, EDITMODE tweak defaults, script tags.
- `styles.css` — all visual tokens and component styles. Single file by design; split if you adopt CSS Modules / Tailwind / styled-components.
- `app.jsx` — top-level `<App>`: route state, window chrome, main header with chips, Tweaks panel wiring.
- `sidebar.jsx` — `<Sidebar>` and its data (nav list, mock recent transcripts).
- `screens.jsx` — `<IdleScreen>`, `<RecordScreen>` (incl. `<Waveform>`), `<CompleteScreen>` with `SAMPLE_TURNS`, plus `<StubScreen>` and the three stubbed screens.
- `primitives.jsx` — `<Icon>` and `SPEAKER_COLORS`.
- `tweaks-panel.jsx` — shared Tweaks shell (host protocol + form controls). Not part of the product; only used by the prototype environment.
- `LocalScribe-standalone.html` — pre-bundled, double-clickable copy of the prototype. Single file, runs offline.

For the original product spec (architecture, REST contract, error handling, build sequence), see `2026-05-15-stt-desktop-ui-design.md` in the project root.
