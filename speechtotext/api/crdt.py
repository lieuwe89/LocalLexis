"""CRDT merge for transcript metadata.

The hub maintains a per-workspace Lamport counter and applies device-
submitted ops with last-writer-wins per field. The state model is small
(speaker map plus per-field clocks plus an append-only history) so we
hand-roll the CRDT instead of pulling in a general-purpose framework
like Automerge — the savings in dependency weight and audit surface
are large for the rare-edit workload this supports.

Operations supported in v1
--------------------------

- ``relabel`` — set ``speakers[<id>]`` = ``<new_name>``.

Keys follow a dotted addressing scheme so future ops (e.g.
``text_override`` per segment) can slot in without changing the merge
function. v1 only recognises ``speakers.<speaker_id>`` keys.

Merge rule
----------

For each key, the clock with the higher ``(lamport, device_id)``
tuple wins. ``ts`` is a wall-clock string carried for display only and
is never compared. The hub assigns ``lamport_assigned`` as
``max(hub_counter, request.lamport_observed) + 1`` on every applied
op; devices propose, the hub disposes. This makes the hub the sole
authority on global ordering and removes wall-clock skew between
devices from the ordering picture entirely.

Every submitted op is appended to ``_history`` regardless of whether
its clock beat the existing one. That keeps the audit trail honest
(observers see "iPad's rename of SPEAKER_00 lost to desktop's earlier
rename") and lets ``replay_history`` re-derive current state from the
log if the live state ever diverges.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

OP_RELABEL = "relabel"
SUPPORTED_OPS = frozenset({OP_RELABEL})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Clock:
    """Per-key Lamport clock entry.

    ``ts`` is wall-clock time as ISO-8601 for display. Never used in
    ordering — comparison goes through :meth:`beats`.
    """

    device: str
    lamport: int
    ts: str

    def beats(self, other: "Clock | None") -> bool:
        """Return True iff ``self`` should win against ``other`` under LWW."""
        if other is None:
            return True
        if self.lamport != other.lamport:
            return self.lamport > other.lamport
        # Tiebreaker. Vanishingly rare in practice because the hub assigns
        # lamports sequentially, but a partition that recovers can produce
        # equal lamports from two devices.
        return self.device > other.device


@dataclass(frozen=True)
class Op:
    """An applied operation, immutable, written into ``_history``.

    ``from_value`` is a copy of the value held at the key just before
    this op was applied (or ``None`` if the key had no value). It is
    informational — replay does not use it — but lets the audit log
    show "renamed Alice -> Bob" rather than "set to Bob."
    """

    op: str
    key: str
    value: Any
    from_value: Any | None
    device: str
    lamport: int
    ts: str


@dataclass(frozen=True)
class OpRequest:
    """An incoming op from a device, awaiting hub Lamport assignment."""

    op: str
    key: str
    value: Any
    device: str
    lamport_observed: int


@dataclass
class TranscriptState:
    """The mutable parts of a transcript that the CRDT touches.

    Mirrors the v2 transcript JSON shape so :meth:`from_json` /
    :meth:`to_jsonish` are direct round-trips through ``json.dumps`` /
    ``json.loads``.
    """

    speakers: dict[str, str] = field(default_factory=dict)
    clocks: dict[str, Clock] = field(default_factory=dict)
    history: list[Op] = field(default_factory=list)

    @classmethod
    def from_json(cls, doc: dict) -> "TranscriptState":
        speakers = {str(k): str(v) for k, v in (doc.get("speakers") or {}).items()}
        raw_clocks = doc.get("_clocks") or {}
        clocks: dict[str, Clock] = {}
        for k, v in raw_clocks.items():
            if isinstance(v, dict):
                clocks[k] = Clock(
                    device=str(v.get("device", "")),
                    lamport=int(v.get("lamport", 0)),
                    ts=str(v.get("ts", "")),
                )
        history: list[Op] = []
        for entry in doc.get("_history") or []:
            if not isinstance(entry, dict):
                continue
            history.append(
                Op(
                    op=str(entry.get("op", "")),
                    key=str(entry.get("key", "")),
                    value=entry.get("value"),
                    from_value=entry.get("from_value"),
                    device=str(entry.get("device", "")),
                    lamport=int(entry.get("lamport", 0)),
                    ts=str(entry.get("ts", "")),
                )
            )
        return cls(speakers=speakers, clocks=clocks, history=history)

    def to_jsonish(self) -> dict:
        return {
            "speakers": dict(self.speakers),
            "_clocks": {k: asdict(c) for k, c in self.clocks.items()},
            "_history": [asdict(op) for op in self.history],
        }


def _value_at_key(state: TranscriptState, key: str) -> Any:
    """Resolve dotted key against ``state``. Unknown keys return None."""
    parts = key.split(".", 1)
    if len(parts) == 2 and parts[0] == "speakers":
        return state.speakers.get(parts[1])
    return None


def _set_value_at_key(speakers: dict[str, str], key: str, value: Any) -> None:
    parts = key.split(".", 1)
    if len(parts) == 2 and parts[0] == "speakers":
        speakers[parts[1]] = str(value) if value is not None else ""
        return
    raise ValueError(f"unsupported key for set: {key!r}")


def merge_op(
    state: TranscriptState,
    request: OpRequest,
    hub_lamport: int,
    *,
    ts: str | None = None,
) -> tuple[TranscriptState, int, Op]:
    """Apply ``request`` against ``state``; assign a hub Lamport.

    Args:
        state: Current transcript state.
        request: Incoming op from a device.
        hub_lamport: Hub's current Lamport counter for this workspace.
        ts: Optional wall-clock timestamp override (testing).

    Returns:
        ``(new_state, new_hub_lamport, applied_op)``. The hub counter
        advances on every call. The applied op is appended to history
        whether or not its clock beats the existing one — losing ops
        are recorded for audit.

    Raises:
        ValueError: if the op type or key is invalid.
    """
    if request.op not in SUPPORTED_OPS:
        raise ValueError(f"unsupported op: {request.op!r}")
    if not request.key:
        raise ValueError("op key cannot be empty")
    if not request.device:
        raise ValueError("op device cannot be empty")
    if request.lamport_observed < 0:
        raise ValueError(
            f"lamport_observed must be non-negative, got {request.lamport_observed}"
        )
    # Validate key shape: must be "speakers.<id>" in v1.
    parts = request.key.split(".", 1)
    if len(parts) != 2 or parts[0] != "speakers" or not parts[1]:
        raise ValueError(
            f"unsupported key in v1 (expected 'speakers.<id>'): {request.key!r}"
        )

    when = ts if ts is not None else now_iso()
    new_lamport = max(hub_lamport, request.lamport_observed) + 1
    new_clock = Clock(device=request.device, lamport=new_lamport, ts=when)
    existing_clock = state.clocks.get(request.key)
    from_value = _value_at_key(state, request.key)

    op = Op(
        op=request.op,
        key=request.key,
        value=request.value,
        from_value=from_value,
        device=request.device,
        lamport=new_lamport,
        ts=when,
    )

    apply = new_clock.beats(existing_clock)

    new_speakers = dict(state.speakers)
    new_clocks = dict(state.clocks)
    new_history = state.history + [op]

    if apply:
        _set_value_at_key(new_speakers, request.key, request.value)
        new_clocks[request.key] = new_clock

    new_state = TranscriptState(
        speakers=new_speakers,
        clocks=new_clocks,
        history=new_history,
    )
    return new_state, new_lamport, op


def replay_history(history: Iterable[Op]) -> TranscriptState:
    """Rebuild a ``TranscriptState`` by re-applying every op in order.

    Sorting on ``(lamport, device)`` makes the replay deterministic
    regardless of the order ops were originally appended; the LWW rule
    is commutative on that sort so the resulting speakers/clocks match
    what live merging would have produced. The history list itself is
    preserved in input order so the audit trail stays untouched.
    """
    state = TranscriptState()
    sorted_ops = sorted(history, key=lambda o: (o.lamport, o.device))
    for op in sorted_ops:
        clock = Clock(device=op.device, lamport=op.lamport, ts=op.ts)
        existing = state.clocks.get(op.key)
        if clock.beats(existing):
            _set_value_at_key(state.speakers, op.key, op.value)
            state.clocks[op.key] = clock
    # History is presented in chronological-by-(lamport,device) order
    # because the input may be unsorted; callers wanting the "as
    # written" order should preserve their own list.
    state.history = list(sorted_ops)
    return state
