# In-Progress Screen — Design Note

## Overview

The Progress screen covers the window from job start to job completion. It reuses
the Complete view's container geometry (`max-width: 920px`, `padding: 36px 40px 80px`)
so the visual cut on completion is seamless — same margins, same reading width.
Internal vertical gap is `22px` between every major block.

## ASCII Wireframe

```
┌─────────────────────────────────────────────────────┐
│ SIDEBAR │          MAIN HEADER         [×]           │
├─────────┼───────────────────────────────────────────┤
│         │ meeting-05-15.mp3 · 42 MB · 1h 04m        │
│  nav    │ Transcribing…                             │
│         │ ─────────────────────────────────────────  │
│         │ [████████████████░░░░░░░░░░░░░░░░] 62%    │
│         │                                            │
│         │ [ingest ✓] [asr 62%] [diarize] [merge]    │
│         │            [write]                         │
│         │                                            │
│         │ 00:00:08  Speaker 1   Hello, welcome to…  │
│         │ 00:00:14  Speaker 2   Thanks for having…  │
│         │ 00:00:22  Speaker 1   Let's start with…   │
│         │           …streaming…                      │
└─────────┴───────────────────────────────────────────┘
```

## Layout

Container: `.progress` — `display: flex; flex-direction: column; gap: 22px`.
Same `max-width` and `padding` as Complete keeps transition invisible to the eye.

**Doc header** (`.doc-head`): stacked column, `gap: 8px`, bottom border `0.5px var(--line)`,
`padding-bottom: 22px`. Contains a file-meta line above the `<h1>`.

**Progress bar** (`.bar`): 4px tall pill, `background: var(--bg-elev)` track,
inner `<div>` filled with `var(--accent)`, `transition: width 0.3s`.
Width is `((stageIndex + stagePercent) / 5) * 100%`.

**Stage chips** (`.stages`): flex row, `gap: 8px`, wraps on narrow windows.

**Live transcript** (`.live-transcript`): scrolling; each row is a three-column grid.

## Header Typography

- File-meta: mono 10.5px, uppercase, `letter-spacing: 0.12em`, `--ink-dim`
- `<h1>`: Newsreader 28px, weight 400, `letter-spacing: -0.012em`, `--ink`

Copy pattern: `meeting-05-15.mp3 · 42 MB · 1h 04m` — file path, then interpunct-separated
size and duration pulled from the job record.

## Stage Chips

Five chips in order: `ingest` `asr` `diarize` `merge` `write` (backend SSE names).

| State   | Color        | Background       | Border           |
|---------|--------------|------------------|------------------|
| pending | `--ink-dim`  | `--bg-elev`      | `--line`         |
| active  | `--accent`   | `--accent-faint` | `--accent-line`  |
| done    | `--ink-muted`| `--bg-elev`      | `--line`         |

Active chip shows inline percent: `asr 62%`. Chip height 24px, `border-radius: 999px`,
mono 11.5px, `padding: 0 9px`.

## Live Transcript Typography

Reuses the Complete view's `.turn` three-column grid:
`grid-template-columns: 70px 110px 1fr; gap: 18px`.

- Timestamp (`.ts`): mono 11px, `--ink-dim`, right-aligned
- Speaker (`.spk`): Newsreader italic 14px, `--ink-muted`
- Body text: Newsreader 17px / 1.7, `--ink`

New lines append at the bottom; the container scrolls automatically via `overflow: auto`
on `.main-body`.

## Cancel Button

An X icon button in the top-right of `.main-header` lets the user abort the job.
**Marked future for v1** — the button slot exists in `MainHeader` but wiring the
cancel API call and cleanup is deferred until the backend exposes a `/jobs/:id/cancel`
endpoint.

## Error State

If `job.status === 'failed'`, a `.err` block renders below the live transcript in
`var(--danger)`, mono 13px, showing `job.error`.
