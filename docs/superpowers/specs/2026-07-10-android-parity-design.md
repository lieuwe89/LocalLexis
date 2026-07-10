# Android Read-Only Parity (v0.13.0 features) — Design

Date: 2026-07-10
Status: approved (pending user review of this document)
Scope: Android app only (`android/`). Follow-up to the webui enhancements batch
(`2026-07-07-webui-enhancements-design.md`, "Out of scope: Android parity").

## Context

The v0.13.0 webui/desktop batch added `title` (rename), per-segment text edits,
date+time display, and LLM `summary` / `summary_meta` to transcript docs. The hub's
`/sync/snapshot` and `/sync/since/{cursor}` endpoints serve **full transcript JSON
docs** (`routes_sync.py` `json.loads`es each file), so all of these fields already
arrive on the Android wire — the app currently ignores them.

The Android app is read-only with respect to hub transcripts: it syncs via
`SyncClient` → `SyncIngest` into Room, with replace-strategy segment ingest and
DAO-maintained FTS. There is no PATCH client. This design keeps it that way.

**Decided scope: read-only parity.** Display renames, edited segments, summaries,
and date+time synced from the hub. Renaming and segment editing *from* the phone
are explicitly out of scope (would need a CRDT PATCH client, offline queueing, and
conflict UX — separate effort if ever wanted).

## Features

### 1. Data layer (wire + Room)

- `WireTranscript` gains `title: String?`, `summary: String?`, and
  `@SerialName("summary_meta") summaryMeta: WireSummaryMeta?` where
  `WireSummaryMeta(model: String?, @SerialName("created_at") createdAt: String?)`.
  The `provider` field in `summary_meta` is not parsed (unused in UI).
  `ignoreUnknownKeys` means old hubs yield nulls; no version gating needed.
- `TranscriptEntity` gains four nullable columns: `title`, `summary`,
  `summaryModel`, `summaryCreatedAt`.
- Room migration **1 → 2**: additive `ALTER TABLE transcripts ADD COLUMN ...`
  only. Migration test follows the existing `MigrationTest` pattern. Existing
  rows get nulls and heal on the next sync (full-doc replace semantics).
- `SyncIngest.upsertOne` maps the new fields onto the entity.
- **Edited segments require no work**: replace-strategy ingest already overwrites
  `segments[i].text`, and the segment DAO rebuilds the FTS rows in the same
  transaction.

### 2. Title display

- New helper `displayTitle(title, audioBasename, id)` with fallback chain
  `title → audioBasename → id`, in `ui/format` alongside the other formatters.
- Used in exactly three places: library row, search-result title resolver
  (`rememberTitleResolver`), and the transcript-detail header.
- `TranscriptSummary` (library list projection) gains `title`.

### 3. Date + time display

- `ui/format/Formatting.kt` gains `formatDateTime(iso)` → "Jul 7, 2026, 14:32"
  (24h, same offset/local/date-only parse-fallback chain as `formatDate`;
  date-only input renders date-only). `formatDate` stays for any caller that
  wants date-only.
- Library rows and the detail header switch to `formatDateTime`.

### 4. Summary view

- In `TranscriptDetailScreen`, when `summary` is non-null: a card between the
  header and the segment list — "Summary" title, caption "`<model>` · `<date>`"
  (each part omitted when null), body rendered by a new `MarkdownText`
  composable.
- `MarkdownText` is a lightweight in-app renderer (no new dependency) covering
  the subset LLM summaries actually use: `#`–`###` headings, `**bold**`,
  `*italic*`, `-`/`*`/numbered list items. Unrecognised syntax renders as plain
  text lines.
- Card is collapsible, starts expanded. No summary → no card.
- Summaries are generated on the hub (web UI button); Android only displays the
  stored result. No summarize trigger on Android.

### 5. Reactivity

- `TranscriptDetailViewModel` keeps its snapshot-on-construct behavior. New data
  appears after a library sync + re-navigation, same as speaker relabels today.

## Error handling

- All new fields nullable end-to-end; absence degrades to current behavior
  (filename-stem title, no summary card).
- Malformed `summary_meta` → caption omitted, summary body still shown.
- Sync parsing failures stay inside the existing `SyncException` envelope; the
  new fields introduce no new failure modes.

## Testing

- Unit (`testDebugUnitTest`): wire parsing with fields present/absent/malformed
  meta; `SyncIngest` column mapping; Room migration 1→2; `formatDateTime` (offset,
  local, date-only, garbage); `displayTitle` fallback chain; `MarkdownText`
  parser cases (headings, bold, italic, lists, plain fallback).
- Build: `assembleDebug` via Android Studio JBR (system Java is 1.8).
- Device checks (sync against real hub, view renamed/edited/summarized
  transcript) deferred to the batched manual session, per working agreement.

## Out of scope

- Rename or segment editing from Android (CRDT PATCH client).
- Summarize trigger from Android.
- Audio playback/download on Android.
- Trash/delete operations on Android.
- Flow-based reactivity in the detail view.
