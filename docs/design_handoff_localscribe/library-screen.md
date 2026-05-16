# Library Screen — Design Handoff

## Purpose

Displays the full history of processed transcripts so the user can search, browse, and reopen any previous session.

## Layout

A vertically scrolling panel with two zones: a sticky search bar at the top, and the transcript list below.

**Search bar**: full-width input, `--bg-elev` background, `0.5px solid var(--line)` border, 6px border-radius, 8px 12px padding. A search icon prefixes the input (14px, `--ink-dim`). Font is `--sans` 13px. Placeholder text: `Search transcripts…` (mono style). Outer container: `max-width: 920px`, `margin: 0 auto`, `padding: 36px 40px 80px`.

**List rows**: each transcript renders as a CSS grid row.

Grid columns: `22px 1fr 60px 100px 40px 90px 22px 16px`  
Gap: 14px | Padding: 12px 6px | Bottom border: `0.5px solid var(--line-faint)`

Columns left-to-right: doc icon, filename (truncated), duration (`m:ss`), speaker count, language code, creation date, status badge (✓ / ⚠), chevron.

Secondary metadata columns (duration, speakers, language, date) use `--mono` 11.5px `--ink-dim`. Filename uses `--ink`, truncated with ellipsis.

## States

**Hover**: row background shifts to `--bg-hover`.

**Error row**: when `error` is set on the list item, filename dims to `--ink-muted` and the status badge renders in `--warn` amber rather than `--accent` green.

**Empty state**: no list rendered; instead a centered block with Newsreader (serif) italic 18px text: _"No transcripts yet — drop an audio file on the Transcribe tab."_ Padded 60px top/bottom.

**Sort**: most-recent-first (matches backend default; no client-side re-sort needed).

## Interaction

Click any row → `await load(id)` to fetch full transcript, then `setTid(id)` + `setRoute('complete')` to navigate to the CompleteScreen.

## ASCII Wireframe

```
┌──────────────────────────────────────────────────────────────┐
│  🔍  Search transcripts…                                      │
│──────────────────────────────────────────────────────────────│
│  📄  interview-2024-11-01.mp3   4:22  2 speakers  en  2024-11-01  ✓  › │
│  📄  standup-monday.wav         1:05  1 speakers  en  2024-10-28  ✓  › │
│  📄  call-broken.mp3            —     0 speakers  —   2024-10-15  ⚠  › │
│  📄  podcast-ep12.m4a           42:10 3 speakers  en  2024-10-01  ✓  › │
│                                                                │
│  (empty state)                                                 │
│       No transcripts yet — drop an audio file on the          │
│                   Transcribe tab.                             │
└──────────────────────────────────────────────────────────────┘
```
