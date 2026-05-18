# First-Launch Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the silent-broken-window feeling new users hit on first launch by (a) shortening the backend cold-start and (b) telling users what's happening while they wait.

**Architecture:**
- **Backend speedup:** defer `faster_whisper`, `torch`, `pyannote.audio`, and `soundfile` imports out of module-load time and into the first transcribe/diarize call. `/health`, `/devices`, `/config` only need stdlib + FastAPI, so the handshake JSON line + uvicorn ready-state fire seconds earlier.
- **UI overlay:** a single `useBackend` zustand store polls `baseUrl()` + `/health` and exposes `{ status, elapsedMs }`. A `BootOverlay` component renders full-window over `App` until `status === 'ready'`. On first ever launch (no `locallexis.firstLaunchDone` in localStorage) it shows extended copy explaining macOS Gatekeeper verification.
- **Status pill:** a small dot+label in `MainHeader` subscribed to the same store. Always visible — surfaces future slow restarts, not just first launch.

**Tech Stack:** React 18, Zustand, Tauri 2, FastAPI, PyInstaller sidecar, Vitest + React Testing Library, Pytest.

---

## File Structure

**Backend (Python):**
- Modify: `speechtotext/asr/faster_whisper.py` — move `from faster_whisper import WhisperModel` into method body.
- Modify: `speechtotext/diarize/pyannote.py` — move `import torch`, `import soundfile as sf`, `from pyannote.audio import Pipeline` into method body.
- Modify: `speechtotext/api/routes_jobs.py` — replace `from speechtotext.api import runner` with lazy local import inside handlers.
- Create: `tests/api/test_sidecar_cold_start.py` — asserts heavy ML modules absent from `sys.modules` after `create_app()` returns.

**Frontend (React/TS):**
- Create: `ui/src/stores/backend.ts` — zustand store, polls `/health`, exposes status + elapsed.
- Create: `ui/src/chrome/BootOverlay.tsx` — full-window splash.
- Create: `ui/src/chrome/BootOverlay.css` — overlay styles.
- Create: `ui/src/chrome/BackendStatus.tsx` — pill for header.
- Modify: `ui/src/App.tsx` — render `<BootOverlay />` at root, initialize `useBackend`.
- Modify: `ui/src/chrome/MainHeader.tsx` — add `<BackendStatus />` to chip row.
- Create: `ui/src/stores/backend.test.ts` — vitest unit tests for store.
- Create: `ui/src/chrome/BootOverlay.test.tsx` — vitest + RTL.
- Create: `ui/src/chrome/BackendStatus.test.tsx` — vitest + RTL.

---

## Task 1: Lazy ML imports in `faster_whisper.py`

**Files:**
- Modify: `speechtotext/asr/faster_whisper.py`
- Test: `tests/asr/test_faster_whisper_lazy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/asr/test_faster_whisper_lazy.py`:

```python
"""Lazy-import guard: importing the wrapper must not import faster_whisper."""
from __future__ import annotations

import importlib
import sys


def test_module_import_does_not_load_faster_whisper(monkeypatch):
    for mod in list(sys.modules):
        if mod == "faster_whisper" or mod.startswith("faster_whisper."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.delitem(sys.modules, "speechtotext.asr.faster_whisper", raising=False)

    importlib.import_module("speechtotext.asr.faster_whisper")

    assert "faster_whisper" not in sys.modules, (
        "speechtotext.asr.faster_whisper must defer `from faster_whisper import WhisperModel` "
        "until first use so sidecar cold-start stays fast"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/asr/test_faster_whisper_lazy.py -v`
Expected: FAIL — `faster_whisper` is in `sys.modules` because of the top-level import.

- [ ] **Step 3: Move the import into the method body**

Open `speechtotext/asr/faster_whisper.py`. Remove the top-level `from faster_whisper import WhisperModel`. Inside the class that constructs `WhisperModel` (the only consumer), add the import as the first line of the method that builds the model. Use this pattern — adapt to whichever method in the file currently calls `WhisperModel(...)`:

```python
def _load_model(self) -> "WhisperModel":  # type: ignore[name-defined]
    from faster_whisper import WhisperModel  # lazy: heavy import deferred to first transcribe
    return WhisperModel(...)
```

If `WhisperModel` is referenced as a type annotation anywhere at module level, switch to a string annotation (`"WhisperModel"`) or add `from typing import TYPE_CHECKING` guarded block:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from faster_whisper import WhisperModel
```

- [ ] **Step 4: Run lazy-import test**

Run: `pytest tests/asr/test_faster_whisper_lazy.py -v`
Expected: PASS.

- [ ] **Step 5: Run existing ASR tests to confirm no regression**

Run: `pytest tests/asr -v`
Expected: PASS (or skip on environments without the model bundle — same as before this change).

- [ ] **Step 6: Commit**

```bash
git add speechtotext/asr/faster_whisper.py tests/asr/test_faster_whisper_lazy.py
git commit -m "perf(sidecar): defer faster_whisper import until first transcribe"
```

---

## Task 2: Lazy ML imports in `pyannote.py`

**Files:**
- Modify: `speechtotext/diarize/pyannote.py`
- Test: `tests/diarize/test_pyannote_lazy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/diarize/test_pyannote_lazy.py`:

```python
"""Lazy-import guard: importing the diarizer wrapper must not pull torch/pyannote/soundfile."""
from __future__ import annotations

import importlib
import sys


def test_module_import_does_not_load_torch_or_pyannote(monkeypatch):
    forbidden_prefixes = ("torch", "pyannote", "soundfile")
    for mod in list(sys.modules):
        if any(mod == p or mod.startswith(p + ".") for p in forbidden_prefixes):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.delitem(sys.modules, "speechtotext.diarize.pyannote", raising=False)

    importlib.import_module("speechtotext.diarize.pyannote")

    for p in forbidden_prefixes:
        assert p not in sys.modules, (
            f"speechtotext.diarize.pyannote must defer `import {p}` until first diarize call "
            f"so sidecar cold-start stays fast"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/diarize/test_pyannote_lazy.py -v`
Expected: FAIL — `torch`, `pyannote`, and `soundfile` are all loaded by module import.

- [ ] **Step 3: Defer the imports**

In `speechtotext/diarize/pyannote.py`:

- Remove top-level `import soundfile as sf`, `import torch`, `from pyannote.audio import Pipeline`.
- Add a `TYPE_CHECKING` block for any type annotations that referenced them:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pyannote.audio import Pipeline
```

- Move each `import` to the first line of the method that actually uses it (likely `__init__` for `Pipeline` and `torch`, the audio-loading method for `soundfile`). Example:

```python
def __init__(self, hf_token: str, backend: Literal["cpu", "cuda", "mps"] = "cpu", model_id: str = _MODEL_ID) -> None:
    import torch  # lazy: heavy import deferred to first diarize
    from pyannote.audio import Pipeline
    ...
```

```python
def _load_audio(self, path: Path):
    import soundfile as sf  # lazy
    return sf.read(str(path))
```

- [ ] **Step 4: Run lazy-import test**

Run: `pytest tests/diarize/test_pyannote_lazy.py -v`
Expected: PASS.

- [ ] **Step 5: Run existing diarize tests**

Run: `pytest tests/diarize -v`
Expected: PASS (or same skip behavior as before — no regression).

- [ ] **Step 6: Commit**

```bash
git add speechtotext/diarize/pyannote.py tests/diarize/test_pyannote_lazy.py
git commit -m "perf(sidecar): defer torch/pyannote/soundfile imports until first diarize"
```

---

## Task 3: Lazy `runner` import in `routes_jobs.py` + cold-start smoke test

**Files:**
- Modify: `speechtotext/api/routes_jobs.py`
- Test: `tests/api/test_sidecar_cold_start.py`

- [ ] **Step 1: Write the failing cold-start test**

Create `tests/api/test_sidecar_cold_start.py`:

```python
"""Boot-time guard: creating the FastAPI app must not import heavy ML libs.

These are loaded lazily in the runner so /health, /devices, /config respond
seconds earlier on a cold sidecar start.
"""
from __future__ import annotations

import importlib
import sys


def test_create_app_does_not_import_ml_stack(monkeypatch):
    forbidden = ("faster_whisper", "torch", "pyannote", "soundfile")
    for mod in list(sys.modules):
        if any(mod == p or mod.startswith(p + ".") for p in forbidden):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    for mod in list(sys.modules):
        if mod.startswith("speechtotext."):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    app_mod = importlib.import_module("speechtotext.api.app")
    app = app_mod.create_app()
    assert app is not None

    for p in forbidden:
        assert p not in sys.modules, (
            f"create_app() must not transitively import {p}; "
            f"defer it inside the job runner"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_sidecar_cold_start.py -v`
Expected: FAIL — `routes_jobs.py` does `from speechtotext.api import runner`, which loads the full ML stack.

- [ ] **Step 3: Defer the runner import**

Open `speechtotext/api/routes_jobs.py`. Replace the top-level `from speechtotext.api import runner` with a lazy local import in every handler that uses it. Example for the transcribe handler:

```python
@router.post("/jobs/transcribe", status_code=202)
def post_transcribe(req: TranscribeRequest, request: Request) -> dict:
    from speechtotext.api import runner  # lazy: ML stack loads on first job, not at boot
    audio = Path(req.path)
    if not audio.exists() or audio.is_dir():
        raise HTTPException(status_code=404, detail=f"audio not found: {audio}")
    registry = request.app.state.jobs
    job_id = registry.create(kind="transcribe", audio_path=str(audio))
    runner.run_transcribe_job(
        registry, job_id, audio,
        language=req.language,
        num_speakers=req.num_speakers,
        backend=req.backend,
    )
    return {"job_id": job_id}
```

Repeat the same `from speechtotext.api import runner` lazy import inside every other handler in `routes_jobs.py` that references `runner.` (record, stop, cancel). Remove the top-level import entirely.

- [ ] **Step 4: Run cold-start test**

Run: `pytest tests/api/test_sidecar_cold_start.py -v`
Expected: PASS.

- [ ] **Step 5: Run all API tests**

Run: `pytest tests/api -v`
Expected: PASS.

- [ ] **Step 6: Manual smoke — confirm handshake fires earlier**

Run: `python -m speechtotext.api` and observe stdout. The `{"locallexis": {"host": ..., "port": ...}}` line should print within ~1s on a warm Python install (versus several seconds before this task). No code change here — just verify.

- [ ] **Step 7: Commit**

```bash
git add speechtotext/api/routes_jobs.py tests/api/test_sidecar_cold_start.py
git commit -m "perf(sidecar): defer runner import so /health/devices respond before ML load"
```

---

## Task 4: `useBackend` store with `/health` polling

**Files:**
- Create: `ui/src/stores/backend.ts`
- Test: `ui/src/stores/backend.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `ui/src/stores/backend.test.ts`:

```typescript
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('../api/client', () => ({
  baseUrl: vi.fn(),
}));

import { baseUrl } from '../api/client';
import { useBackend } from './backend';

describe('useBackend', () => {
  beforeEach(() => {
    useBackend.setState({ status: 'starting', elapsedMs: 0, error: null });
    vi.useFakeTimers();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('starts in "starting" state', () => {
    expect(useBackend.getState().status).toBe('starting');
  });

  it('transitions to "ready" once baseUrl resolves and /health returns ok', async () => {
    (baseUrl as ReturnType<typeof vi.fn>).mockResolvedValue('http://127.0.0.1:1234');
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true });

    useBackend.getState().start();
    await vi.runOnlyPendingTimersAsync();
    await vi.runOnlyPendingTimersAsync();

    expect(useBackend.getState().status).toBe('ready');
  });

  it('tracks elapsedMs while starting', async () => {
    (baseUrl as ReturnType<typeof vi.fn>).mockImplementation(
      () => new Promise(() => {}) // never resolves
    );

    useBackend.getState().start();
    await vi.advanceTimersByTimeAsync(2000);

    expect(useBackend.getState().elapsedMs).toBeGreaterThanOrEqual(2000);
    expect(useBackend.getState().status).toBe('starting');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && pnpm vitest run src/stores/backend.test.ts`
Expected: FAIL — `./backend` does not exist.

- [ ] **Step 3: Implement the store**

Create `ui/src/stores/backend.ts`:

```typescript
import { create } from 'zustand';
import { baseUrl } from '../api/client';

export type BackendStatus = 'starting' | 'ready' | 'failed';

interface State {
  status: BackendStatus;
  elapsedMs: number;
  error: string | null;
  start: () => void;
}

const TICK_MS = 250;

export const useBackend = create<State>((set, get) => {
  let started = false;
  let startTs = 0;
  let tickHandle: ReturnType<typeof setInterval> | null = null;

  const stopTicking = () => {
    if (tickHandle !== null) {
      clearInterval(tickHandle);
      tickHandle = null;
    }
  };

  return {
    status: 'starting',
    elapsedMs: 0,
    error: null,
    start: () => {
      if (started) return;
      started = true;
      startTs = Date.now();
      tickHandle = setInterval(() => {
        if (get().status === 'starting') {
          set({ elapsedMs: Date.now() - startTs });
        }
      }, TICK_MS);

      baseUrl()
        .then(async (url) => {
          const r = await fetch(url + '/health');
          if (!r.ok) throw new Error(`/health ${r.status}`);
          set({ status: 'ready', elapsedMs: Date.now() - startTs });
          stopTicking();
        })
        .catch((e) => {
          set({ status: 'failed', error: String(e), elapsedMs: Date.now() - startTs });
          stopTicking();
        });
    },
  };
});
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ui && pnpm vitest run src/stores/backend.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add ui/src/stores/backend.ts ui/src/stores/backend.test.ts
git commit -m "feat(ui): add useBackend store tracking sidecar readiness"
```

---

## Task 5: `BootOverlay` component

**Files:**
- Create: `ui/src/chrome/BootOverlay.tsx`
- Create: `ui/src/chrome/BootOverlay.css`
- Test: `ui/src/chrome/BootOverlay.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `ui/src/chrome/BootOverlay.test.tsx`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BootOverlay } from './BootOverlay';
import { useBackend } from '../stores/backend';

function setBackend(partial: Partial<ReturnType<typeof useBackend.getState>>) {
  useBackend.setState({ ...useBackend.getState(), ...partial });
}

describe('BootOverlay', () => {
  beforeEach(() => {
    useBackend.setState({ status: 'starting', elapsedMs: 0, error: null });
  });

  it('renders while status is "starting"', () => {
    render(<BootOverlay />);
    expect(screen.getByTestId('boot-overlay')).toBeInTheDocument();
    expect(screen.getByText(/starting/i)).toBeInTheDocument();
  });

  it('does not render when status is "ready"', () => {
    setBackend({ status: 'ready' });
    render(<BootOverlay />);
    expect(screen.queryByTestId('boot-overlay')).not.toBeInTheDocument();
  });

  it('shows extended message after 15 seconds', () => {
    setBackend({ elapsedMs: 16000 });
    render(<BootOverlay />);
    expect(screen.getByText(/taking longer than usual/i)).toBeInTheDocument();
  });

  it('shows error message when status is "failed"', () => {
    setBackend({ status: 'failed', error: 'boom' });
    render(<BootOverlay />);
    expect(screen.getByText(/couldn.?t start/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && pnpm vitest run src/chrome/BootOverlay.test.tsx`
Expected: FAIL — `./BootOverlay` does not exist.

- [ ] **Step 3: Implement the overlay**

Create `ui/src/chrome/BootOverlay.css`:

```css
.boot-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: var(--bg, #0d0d0f);
  color: var(--ink, #e9e9ea);
  font-family: inherit;
  -webkit-app-region: drag;
}

.boot-overlay__logo {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.boot-overlay__spinner {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid var(--ink-muted, #555);
  border-top-color: var(--ink, #e9e9ea);
  animation: boot-spin 0.9s linear infinite;
}

@keyframes boot-spin {
  to { transform: rotate(360deg); }
}

.boot-overlay__phase {
  font-size: 13px;
  color: var(--ink-muted, #999);
}

.boot-overlay__extended {
  max-width: 360px;
  text-align: center;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-muted, #999);
  margin-top: 8px;
}

.boot-overlay__error {
  color: #f87171;
  font-size: 13px;
}
```

Create `ui/src/chrome/BootOverlay.tsx`:

```typescript
import { useBackend } from '../stores/backend';
import './BootOverlay.css';

const EXTENDED_THRESHOLD_MS = 15_000;

export function BootOverlay() {
  const status = useBackend(s => s.status);
  const elapsedMs = useBackend(s => s.elapsedMs);
  const error = useBackend(s => s.error);

  if (status === 'ready') return null;

  const showExtended = elapsedMs >= EXTENDED_THRESHOLD_MS;

  return (
    <div className="boot-overlay" data-testid="boot-overlay" role="status" aria-live="polite">
      <div className="boot-overlay__logo">LocalLexis</div>
      {status === 'starting' && <div className="boot-overlay__spinner" aria-hidden="true" />}
      <div className="boot-overlay__phase">
        {status === 'starting' ? 'Starting audio engine…' : 'Engine failed to start'}
      </div>
      {status === 'starting' && showExtended && (
        <div className="boot-overlay__extended">
          Taking longer than usual. On first launch macOS verifies the app — this usually
          finishes within 30 seconds.
        </div>
      )}
      {status === 'failed' && (
        <div className="boot-overlay__error">
          Couldn't start the audio engine. {error ?? ''}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ui && pnpm vitest run src/chrome/BootOverlay.test.tsx`
Expected: PASS, 4 tests.

- [ ] **Step 5: Wire overlay into `App.tsx`**

Open `ui/src/App.tsx`. Add imports near the existing imports:

```typescript
import { BootOverlay } from './chrome/BootOverlay';
import { useBackend } from './stores/backend';
```

Inside `export default function App()`, near the other `useEffect`s, add (the `start()` method is idempotent, but useEffect cleanup not needed):

```typescript
useEffect(() => { useBackend.getState().start(); }, []);
```

Wrap the existing `<Window>...</Window>` JSX so the overlay sits at root. Replace the existing `return ( <Window ... /> )` block with:

```typescript
return (
  <>
    <BootOverlay />
    <Window screenLabel={route}>
      {/* …existing children unchanged… */}
    </Window>
  </>
);
```

- [ ] **Step 6: Manual sanity check**

Run: `cd ui && pnpm tauri dev`
Expected: overlay covers the window on launch, dismisses once `/health` returns. Existing screens render as before once dismissed.

- [ ] **Step 7: Commit**

```bash
git add ui/src/chrome/BootOverlay.tsx ui/src/chrome/BootOverlay.css ui/src/chrome/BootOverlay.test.tsx ui/src/App.tsx
git commit -m "feat(ui): add boot overlay covering app until sidecar is ready"
```

---

## Task 6: First-launch detection + extended copy

**Files:**
- Modify: `ui/src/stores/backend.ts`
- Modify: `ui/src/chrome/BootOverlay.tsx`
- Modify: `ui/src/stores/backend.test.ts`
- Modify: `ui/src/chrome/BootOverlay.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `ui/src/stores/backend.test.ts`:

```typescript
describe('useBackend first-launch flag', () => {
  beforeEach(() => {
    localStorage.clear();
    useBackend.setState({ status: 'starting', elapsedMs: 0, error: null });
  });

  it('isFirstLaunch is true when flag absent', () => {
    expect(useBackend.getState().isFirstLaunch()).toBe(true);
  });

  it('markFirstLaunchDone persists to localStorage', () => {
    useBackend.getState().markFirstLaunchDone();
    expect(localStorage.getItem('locallexis.firstLaunchDone')).toBe('1');
    expect(useBackend.getState().isFirstLaunch()).toBe(false);
  });
});
```

Append to `ui/src/chrome/BootOverlay.test.tsx`:

```typescript
describe('BootOverlay first-launch copy', () => {
  beforeEach(() => {
    localStorage.clear();
    useBackend.setState({ status: 'starting', elapsedMs: 0, error: null });
  });

  it('shows first-launch explainer when flag is absent', () => {
    render(<BootOverlay />);
    expect(screen.getByText(/first time you open LocalLexis/i)).toBeInTheDocument();
  });

  it('hides first-launch explainer on subsequent launches', () => {
    localStorage.setItem('locallexis.firstLaunchDone', '1');
    render(<BootOverlay />);
    expect(screen.queryByText(/first time you open LocalLexis/i)).not.toBeInTheDocument();
  });

  it('marks first-launch done when status flips to ready', async () => {
    const { rerender } = render(<BootOverlay />);
    useBackend.setState({ status: 'ready' });
    rerender(<BootOverlay />);
    expect(localStorage.getItem('locallexis.firstLaunchDone')).toBe('1');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && pnpm vitest run src/stores/backend.test.ts src/chrome/BootOverlay.test.tsx`
Expected: FAIL — `isFirstLaunch`, `markFirstLaunchDone`, and the explainer text don't exist yet.

- [ ] **Step 3: Extend the store**

Open `ui/src/stores/backend.ts`. Add a `FIRST_LAUNCH_KEY` constant and two methods to the store. Updated `State` and store body:

```typescript
const FIRST_LAUNCH_KEY = 'locallexis.firstLaunchDone';

interface State {
  status: BackendStatus;
  elapsedMs: number;
  error: string | null;
  start: () => void;
  isFirstLaunch: () => boolean;
  markFirstLaunchDone: () => void;
}
```

Add the two methods inside the `create<State>((set, get) => { ... return { ... } })` block, alongside `start`:

```typescript
isFirstLaunch: () => {
  try { return localStorage.getItem(FIRST_LAUNCH_KEY) !== '1'; } catch { return false; }
},
markFirstLaunchDone: () => {
  try { localStorage.setItem(FIRST_LAUNCH_KEY, '1'); } catch {}
},
```

- [ ] **Step 4: Extend the overlay**

Open `ui/src/chrome/BootOverlay.tsx`. Add a `useEffect` import and update the component:

```typescript
import { useEffect, useState } from 'react';
import { useBackend } from '../stores/backend';
import './BootOverlay.css';

const EXTENDED_THRESHOLD_MS = 15_000;

export function BootOverlay() {
  const status = useBackend(s => s.status);
  const elapsedMs = useBackend(s => s.elapsedMs);
  const error = useBackend(s => s.error);
  const [isFirstLaunch] = useState(() => useBackend.getState().isFirstLaunch());

  useEffect(() => {
    if (status === 'ready') {
      useBackend.getState().markFirstLaunchDone();
    }
  }, [status]);

  if (status === 'ready') return null;

  const showExtended = elapsedMs >= EXTENDED_THRESHOLD_MS;

  return (
    <div className="boot-overlay" data-testid="boot-overlay" role="status" aria-live="polite">
      <div className="boot-overlay__logo">LocalLexis</div>
      {status === 'starting' && <div className="boot-overlay__spinner" aria-hidden="true" />}
      <div className="boot-overlay__phase">
        {status === 'starting' ? 'Starting audio engine…' : 'Engine failed to start'}
      </div>
      {status === 'starting' && isFirstLaunch && (
        <div className="boot-overlay__extended">
          This is the first time you open LocalLexis. macOS is verifying the app — first launch
          usually takes 20-40 seconds. Subsequent launches start instantly.
        </div>
      )}
      {status === 'starting' && !isFirstLaunch && showExtended && (
        <div className="boot-overlay__extended">
          Taking longer than usual. Try quitting and relaunching if this persists.
        </div>
      )}
      {status === 'failed' && (
        <div className="boot-overlay__error">
          Couldn't start the audio engine. {error ?? ''}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run all touched tests**

Run: `cd ui && pnpm vitest run src/stores/backend.test.ts src/chrome/BootOverlay.test.tsx`
Expected: PASS, all tests including the new first-launch ones.

- [ ] **Step 6: Commit**

```bash
git add ui/src/stores/backend.ts ui/src/stores/backend.test.ts ui/src/chrome/BootOverlay.tsx ui/src/chrome/BootOverlay.test.tsx
git commit -m "feat(ui): explain macOS verification wait on first launch only"
```

---

## Task 7: `BackendStatus` pill in header

**Files:**
- Create: `ui/src/chrome/BackendStatus.tsx`
- Create: `ui/src/chrome/BackendStatus.test.tsx`
- Modify: `ui/src/chrome/MainHeader.tsx`
- Modify: `ui/src/styles/global.css` (one new selector — add at bottom of existing chip styles)

- [ ] **Step 1: Write the failing tests**

Create `ui/src/chrome/BackendStatus.test.tsx`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BackendStatus } from './BackendStatus';
import { useBackend } from '../stores/backend';

describe('BackendStatus', () => {
  beforeEach(() => {
    useBackend.setState({ status: 'starting', elapsedMs: 0, error: null });
  });

  it('renders "Starting" pill when status is "starting"', () => {
    render(<BackendStatus />);
    expect(screen.getByText(/starting/i)).toBeInTheDocument();
  });

  it('renders "Ready" pill when status is "ready"', () => {
    useBackend.setState({ status: 'ready' });
    render(<BackendStatus />);
    expect(screen.getByText(/ready/i)).toBeInTheDocument();
  });

  it('renders "Offline" pill when status is "failed"', () => {
    useBackend.setState({ status: 'failed', error: 'boom' });
    render(<BackendStatus />);
    expect(screen.getByText(/offline/i)).toBeInTheDocument();
  });

  it('exposes status via data attribute for styling', () => {
    useBackend.setState({ status: 'starting' });
    render(<BackendStatus />);
    expect(screen.getByTestId('backend-status').getAttribute('data-status')).toBe('starting');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && pnpm vitest run src/chrome/BackendStatus.test.tsx`
Expected: FAIL — `./BackendStatus` does not exist.

- [ ] **Step 3: Implement the pill**

Create `ui/src/chrome/BackendStatus.tsx`:

```typescript
import { useBackend, type BackendStatus as Status } from '../stores/backend';

const LABEL: Record<Status, string> = {
  starting: 'Starting',
  ready: 'Ready',
  failed: 'Offline',
};

export function BackendStatus() {
  const status = useBackend(s => s.status);
  const error = useBackend(s => s.error);
  return (
    <span
      className="chip backend-status"
      data-status={status}
      data-testid="backend-status"
      title={status === 'failed' ? (error ?? 'Engine offline') : `Engine ${LABEL[status]}`}
    >
      <span className="backend-status__dot" aria-hidden="true" />
      {LABEL[status]}
    </span>
  );
}
```

- [ ] **Step 4: Add styles**

Append to `ui/src/styles/global.css`:

```css
.backend-status { display: inline-flex; align-items: center; gap: 6px; }
.backend-status__dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--ink-muted, #888);
}
.backend-status[data-status="starting"] .backend-status__dot {
  background: #f59e0b;
  animation: backend-pulse 1.2s ease-in-out infinite;
}
.backend-status[data-status="ready"] .backend-status__dot { background: #22c55e; }
.backend-status[data-status="failed"] .backend-status__dot { background: #ef4444; }
@keyframes backend-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
```

- [ ] **Step 5: Wire the pill into `MainHeader`**

Open `ui/src/chrome/MainHeader.tsx`. Add import at the top with the other imports:

```typescript
import { BackendStatus } from './BackendStatus';
```

Inside the header JSX, add `<BackendStatus />` just before the existing `<span className="chip"><Icon name="lock" .../> On-device</span>`:

```typescript
<BackendStatus />
<span className="chip"><Icon name="lock" size={11} stroke={1.5} /> On-device</span>
```

- [ ] **Step 6: Run pill tests**

Run: `cd ui && pnpm vitest run src/chrome/BackendStatus.test.tsx`
Expected: PASS, 4 tests.

- [ ] **Step 7: Run full UI test suite to check no regressions**

Run: `cd ui && pnpm vitest run`
Expected: PASS, all tests (existing + new).

- [ ] **Step 8: Commit**

```bash
git add ui/src/chrome/BackendStatus.tsx ui/src/chrome/BackendStatus.test.tsx ui/src/chrome/MainHeader.tsx ui/src/styles/global.css
git commit -m "feat(ui): add backend status pill to main header"
```

---

## Task 8: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest`
Expected: PASS, no regressions.

- [ ] **Step 2: Run the full UI test suite**

Run: `cd ui && pnpm vitest run`
Expected: PASS, all tests including the new ones from tasks 4-7.

- [ ] **Step 3: Manual first-launch smoke (simulate fresh install)**

```bash
# Clear the first-launch flag and any cached sidecar URL state
# (in dev, this means clearing localStorage in the Tauri webview)
cd ui && pnpm tauri dev
```

In the dev window, open devtools and run `localStorage.removeItem('locallexis.firstLaunchDone')`, then reload.

Expected:
- Boot overlay covers the window with "Starting audio engine…" + spinner.
- First-launch explainer ("This is the first time you open LocalLexis…") is visible.
- Within a few seconds the overlay dismisses.
- Header shows green "Ready" pill.
- Settings and Record screens render device list / config without showing "Loading…" or "No devices" stuck states.

- [ ] **Step 4: Manual second-launch smoke**

Quit and relaunch (do **not** clear localStorage).

Expected:
- Overlay still appears but without the first-launch explainer.
- Dismiss is faster (no Gatekeeper rescan).
- Header pill behaves identically.

- [ ] **Step 5: Final commit (only if any tweaks were made during smoke)**

If smoke testing surfaced no issues, no commit needed. Otherwise:

```bash
git add -p
git commit -m "fix(ui): <smoke-test tweak>"
```

---

## Self-Review Notes

- **Spec coverage:** Option 1 (overlay) = Task 5. Option 3 (first-run copy) = Task 6. Option 4 (lazy imports) = Tasks 1-3. Option 5 (status pill) = Task 7. Foundation (`useBackend` store) = Task 4. Verification = Task 8.
- **No placeholders:** every code block is concrete; no "implement X", "add appropriate Y", or "similar to Task N" shortcuts.
- **Type consistency:** `BackendStatus` enum values (`'starting' | 'ready' | 'failed'`), store property names (`status`, `elapsedMs`, `error`, `start`, `isFirstLaunch`, `markFirstLaunchDone`), and localStorage key (`'locallexis.firstLaunchDone'`) are used identically across Tasks 4-7.
- **Test ordering caveat:** existing ASR/diarize tests in Tasks 1-2 may already have been written assuming top-level imports — if any test imports `WhisperModel` or `torch` directly from the wrapper module, update that test in the same task (no separate task needed).
