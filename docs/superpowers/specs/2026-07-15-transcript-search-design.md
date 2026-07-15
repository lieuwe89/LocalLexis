# Transcript Search: Segment-Level Hits, PDF-Style Find, Fuzzy/Phonetic Matching

**Date:** 2026-07-15
**Status:** Approved

## Goal

Three connected search improvements to the web UI (LocalLexis):

1. **Library search → jump to line.** Library search results show line-level (segment-level) hits; clicking a hit opens the transcript scrolled to that exact segment with the match highlighted.
2. **In-transcript find, PDF-style.** Search bar at top of the transcript view with match counter (`3/17`), prev/next buttons, all matches highlighted, current match centered.
3. **Fuzzy (phonetic + typo) matching**, toggleable, in both the library search and the in-transcript find. Library results sortable by relevance or date.

## Current State (v0.14.0)

- Library search: `GET /transcripts?q=` → SQLite FTS5 over `transcripts_fts` (joined content blob, filename, speakers, meta). Returns one `snippet_parts` per transcript. No segment index — a hit cannot be mapped to a line. (`speechtotext/api/library_db.py`, `routes_transcripts.py:119`)
- In-transcript find exists in `CompleteScreen.tsx` (`.doc-find`): case-insensitive substring, Enter/↑/↓ cycling, `<mark>` highlights, scrollIntoView. No counter, no buttons, no fuzzy.
- No fuzzy/phonetic matching anywhere in the repo.
- Android already has per-segment FTS4 (`SegmentFtsEntity(transcriptId, segmentIndex, text)`) — the web backend adopts the same granularity.
- Segments have no stable IDs; identity is array index. Accepted.

## Design

### 1. Backend — segment-level + phonetic index

**Schema** — bump `SCHEMA_VERSION` 1 → 2. DB is a throwaway index rebuilt from JSON sidecars, so upgrade = drop + reindex (existing reconcile path).

- `segments_fts` — FTS5 `(text, transcript_id UNINDEXED, segment_index UNINDEXED)`, tokenizer `porter unicode61 remove_diacritics 2` (same as `transcripts_fts`).
- `segments_phonetic` — FTS5 `(codes, transcript_id UNINDEXED, segment_index UNINDEXED)`, tokenizer `unicode61`. `codes` = segment text with each word replaced by its Double Metaphone **primary** code. Encoder: pure-Python `Metaphone` package (`doublemetaphone`), added to project deps. Tokens that produce an empty code (numbers, symbols) are kept verbatim.
- `transcripts_fts` unchanged (still serves filename/speaker/meta matching and Android compatibility).
- Indexing: wherever a transcript is (re)indexed today, also delete + insert its rows in both segment tables. Reconcile-on-mtime covers edits.

**API** — `GET /transcripts` extended:

| Param | Values | Behavior |
|---|---|---|
| `q` | string | as today |
| `fuzzy` | `0`/`1` (default 0) | 1 = also match `segments_phonetic` with metaphone-encoded query tokens |
| `sort` | `relevance`/`date` (default `relevance` when `q` set) | `date` = created_at desc |

- Query sanitization: reuse `_quote_fts` token approach (quoted tokens + prefix `*`) for both segment tables. Phonetic query: encode each query token to its primary code first, then quote. Prefix `*` applies to exact tokens only, not phonetic codes (codes are short; prefix would over-match).
- Response items gain:
  - `hits: [{segment_index: int, start: float, snippet_parts: [{text, match}], score: float}]` — top 5 segments per transcript, best first.
  - `total_hits: int`.
  - Existing top-level `snippet_parts` kept = first hit's snippet (back-compat for Android/hub clients).
- Ranking: bm25 per segment row. Transcript score = best segment score. In fuzzy mode, exact and phonetic result sets are merged per (transcript, segment); exact hits always rank above phonetic-only hits (constant score offset). `sort=date` overrides ordering; hit lists within a transcript stay relevance-ordered.
- Snippet generation: `snippet(segments_fts, ...)` with the existing private-use-area sentinel + `_parse_snippet`. Phonetic-only hits can't use FTS snippet on original text — build snippet server-side by locating the matched tokens in the segment text (token positions align 1:1 between text and codes by construction).

### 2. Frontend — library screen

- Search bar row gains a **Fuzzy** toggle pill and a **Relevance / Date** sort toggle. Sort toggle rendered only while a query is active. State (`fuzzy`, `sort`) lives in `useLibrary`; `search(q)` passes them as query params; changing either re-runs the current search.
- Result rows: under the existing row header, render up to 3 hit lines — `[mm:ss] …snippet with <mark>…`. If `total_hits > 3`, a "+N more" affordance expands the full `hits` list (server already returns max 5; "+N more" beyond 5 shows on open-transcript jump, not in the list).
- Clicking a hit line (not the row header): write `{query, fuzzy, segmentIndex}` to a new tiny `pendingFind` zustand store, then `load(id)`, `setTid(id)`, `setRoute('complete')`. Clicking the row header behaves as today (open transcript, no find state).

### 3. Frontend — in-transcript find (PDF-style)

Upgrade the existing `.doc-find` in `CompleteScreen.tsx`:

- Match counter `current/total` (e.g. `3/17`), clickable **∧ / ∨** prev/next buttons. Enter/↑/↓ keep working. `Esc` clears.
- **Fuzzy** toggle, same visual as library.
- On mount, if `pendingFind` is set (and matches `tid`): pre-fill query, set fuzzy, compute matches, set current match to the one at `segmentIndex` (first match in that segment; fall back to nearest segment if the index has no match), scroll it into view centered, then clear the store.
- Matching engine in new shared util `ui/src/lib/fuzzyMatch.ts`:
  - `findMatches(segments, query, {fuzzy}) → Match[]` where `Match = {segmentIndex, tokenRange | charRange}`.
  - Exact mode: current lowercase substring semantics (char ranges).
  - Fuzzy mode: tokenize query and segment text; a match is a consecutive token sequence where each transcript token matches the corresponding query token by (a) Double Metaphone primary-code equality (npm `double-metaphone`) OR (b) edit distance ≤ 1 for tokens ≥ 5 chars. Unencodable query tokens compare exact.
  - Highlight renderer maps matches to `<mark>` spans; current match gets a distinct class (e.g. `mark.current`).
- Python and TS encoders never cross-compare (library path is all server-side, find path is all client-side), so no cross-language parity requirement.

### 4. Error handling / edge cases

- Empty query → reset to full list; sort toggle hidden; find bar cleared.
- Fuzzy query where all tokens are unencodable → behaves as exact.
- Stale `segmentIndex` (transcript edited between search and click) → nearest-index fallback; no error.
- Schema upgrade: version mismatch → drop derived tables, full reindex from JSON (existing pattern).
- Performance: no virtualization change; `matches` memo stays O(total tokens) per query change. Library fuzzy = two FTS queries merged server-side.

### 5. Testing

- **Python (pytest):** metaphone encoding (incl. unencodable tokens), segment-table indexing + reconcile-on-edit, `/transcripts` response shapes for exact / fuzzy / sort, ranking (exact above phonetic), snippet alignment for phonetic-only hits.
- **Vitest:** `fuzzyMatch` util — phonetic pairs ("Kaitlyn"/"Catelin"), typo (edit distance 1, ≥5 chars), multi-word sequence, unencodable fallback; CompleteScreen — counter, prev/next wrap, pendingFind jump; LibraryScreen — hit-line rendering, click → pendingFind + route.
- Device/runtime verification deferred to a batched manual session (per workflow preference).

## Out of Scope

- Semantic/embedding search (the reserved `chunks`/`embeddings` tables stay unpopulated).
- Android app changes (its per-segment FTS already exists; API stays back-compatible).
- Stable segment IDs / durable match anchors across edits.
- Backend edit-distance matching (spellfix1/trigram); phonetic covers the ASR-mishearing case.
