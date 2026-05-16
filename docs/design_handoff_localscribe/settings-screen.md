# Settings Screen — Design Handoff

## Purpose

Provides a form interface for editing `config.toml` values at runtime via `GET /config` (load) and `PATCH /config` (save). Changes take effect immediately on save; no restart required.

## Layout

Narrow single-column form. Outer container: `max-width: 600px`, `margin: 0 auto`, `padding: 36px 40px 80px`, `gap: 16px`.

## Banner

When `hf_token_set: false` AND the user has not typed a new token into the draft, a warning banner appears at the very top of the form: amber/orange tint (`rgba(217,119,87,0.12)` bg, `var(--warn)` border and text, 8px radius). Text: "Hugging Face token not set — diarization will fail without it."

## Field Rows

Each setting is a `<label>` element rendered as a 2-column CSS grid: `160px 1fr`, gap 16px, items centered. No visible border between rows — spacing alone separates them.

**Label column** (left, 160px): `--mono`, 11px, `letter-spacing: 0.1em`, `text-transform: uppercase`, color `--ink-dim`.

**Input column** (right): `background: var(--bg)`, `border: 0.5px solid var(--line-strong)`, `color: var(--ink)`, `padding: 7px 10px`, `border-radius: 6px`, `--sans` 13px. Focus: `border-color: var(--accent-line)`, `background: var(--bg-elev-2)`.

### Fields (top to bottom)

| Label | Input type | Notes |
|---|---|---|
| Backend | `<select>` | Options: auto / cpu / cuda / mps |
| ASR model | text | e.g. `large-v3` |
| Hugging Face token | password | Placeholder `••••••••` when `hf_token_set: true`, otherwise `hf_…` |
| Model cache dir | text | Absolute path |
| Default out dir | text | Optional; empty string → `null` |
| Watch recursive | checkbox | Left-aligned, 16×16px |
| Watch debounce (s) | number | Min 0 |
| Watch extensions | text | Comma-separated, e.g. `mp3, wav, m4a` |

## Save Button

Bottom-right aligned. Single "Save" button (`btn-apply` class, disabled when not dirty or while saving). Button label cycles: "Save" (dirty) → "Saving…" (in-flight) → "Saved" (clean). Dirty state is cleared on successful patch.

## Validation

Client-side validation is minimal — the backend owns validation logic. Empty `default_out_dir` is coerced to `null` before submission.

## ASCII Wireframe

```
┌──────────────────────────────────────────────────────┐
│  ⚠  Hugging Face token not set — diarization will   │
│     fail without it.                                  │
│──────────────────────────────────────────────────────│
│  BACKEND             [auto ▾]                        │
│  ASR MODEL           [large-v3            ]          │
│  HUGGING FACE TOKEN  [••••••••            ]          │
│  MODEL CACHE DIR     [~/.cache/huggingface]          │
│  DEFAULT OUT DIR     [                    ]          │
│  WATCH RECURSIVE     [✓]                             │
│  WATCH DEBOUNCE (S)  [2                   ]          │
│  WATCH EXTENSIONS    [mp3, wav, m4a       ]          │
│                                                      │
│                                          [  Save  ]  │
└──────────────────────────────────────────────────────┘
```
