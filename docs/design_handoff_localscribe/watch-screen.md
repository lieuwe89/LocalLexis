# Watch Folder Screen — Design Handoff

## Purpose

Lets the user point LocalScribe at a directory and automatically transcribe any new audio files that appear there.

## Layout

Two vertical sections: a control bar at the top, and a scrolling event log below. Outer container: `max-width: 920px`, `margin: 0 auto`, `padding: 36px 40px 80px`, `gap: 22px`.

## Control Bar

**Idle state**: a "Choose folder…" ghost button on the left, and a "Recursive" checkbox+label to its right. Clicking the button opens a native directory picker (Tauri `open` dialog, `directory: true`). On selection the watcher starts via `POST /watch/start`.

**Running state**: replaces the button with a mono-font status line — "Watching `<path>`" where the path itself is dimmed (`--ink-muted`). A "Stop" button (secondary, danger tint) sits to the right and calls `POST /watch/stop`.

## Event Log

Polled from `GET /watch/status` every 1 second; interval cleaned up on unmount.

Each event renders as a single-row grid: `80px 60px 1fr`, gap 12px, 8px 6px padding, `0.5px solid var(--line-faint)` bottom border. Font: `--mono` 11.5px.

Columns: timestamp (HH:mm:ss, `--ink-dim`), kind badge (uppercase, 10px, letter-spacing 0.08em — green for `done`, red for `error`, default for `queued`), file path or message (truncated with ellipsis).

**Empty state**: when the events array is empty, centered italic serif 16px "Waiting for new files…" with 40px top/bottom padding.

## ASCII Wireframe

```
┌──────────────────────────────────────────────────────────────┐
│  [Choose folder…]  [✓ Recursive]                             │
│  — OR when running: —                                         │
│  Watching `/home/user/recordings`              [Stop]        │
│──────────────────────────────────────────────────────────────│
│  14:22:01  QUEUED   /recordings/standup.wav                  │
│  14:22:08  DONE     /recordings/standup.wav                  │
│  14:25:31  ERROR    /recordings/corrupt.mp3                  │
│                                                              │
│  (empty state)   Waiting for new files…                      │
└──────────────────────────────────────────────────────────────┘
```
