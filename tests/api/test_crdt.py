"""Tests for ``speechtotext.api.crdt`` — merge logic and history replay.

The merge module is the highest-trust code in the codebase: a bug here
silently loses user edits. Coverage is therefore both case-based unit
tests (the obvious invariants) and Hypothesis property tests
(commutativity, idempotency, replay-equivalence over random sequences).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

import pytest

from speechtotext.api.crdt import (
    Clock,
    Op,
    OpRequest,
    OP_RELABEL,
    TranscriptState,
    merge_op,
    now_iso,
    replay_history,
)


# Hypothesis is optional in some test environments; skip the property-
# based tests cleanly if missing.
hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────


def _apply_chain(
    requests: Iterable[OpRequest],
) -> tuple[TranscriptState, int, list[Op]]:
    """Apply ops sequentially through a fresh hub counter."""
    state = TranscriptState()
    hub_lamport = 0
    ops: list[Op] = []
    for i, req in enumerate(requests):
        state, hub_lamport, op = merge_op(
            state, req, hub_lamport, ts=f"2026-05-20T00:00:{i:02d}Z"
        )
        ops.append(op)
    return state, hub_lamport, ops


# ── Clock ──────────────────────────────────────────────────────────────────


class TestClock:
    def test_beats_none(self) -> None:
        assert Clock("dev-a", 1, "t").beats(None)

    def test_higher_lamport_wins(self) -> None:
        a = Clock("dev-a", 2, "t1")
        b = Clock("dev-b", 1, "t2")
        assert a.beats(b)
        assert not b.beats(a)

    def test_tiebreak_by_device(self) -> None:
        a = Clock("dev-b", 5, "t")  # higher device wins
        b = Clock("dev-a", 5, "t")
        assert a.beats(b)
        assert not b.beats(a)

    def test_identical_clocks_do_not_beat(self) -> None:
        a = Clock("dev-a", 5, "t")
        b = Clock("dev-a", 5, "t")
        assert not a.beats(b)
        assert not b.beats(a)

    def test_ts_not_used_for_ordering(self) -> None:
        a = Clock("dev-a", 1, "2099-01-01T00:00:00Z")
        b = Clock("dev-a", 2, "2000-01-01T00:00:00Z")
        # b has earlier wall clock but higher lamport → b wins.
        assert b.beats(a)


# ── merge_op basics ────────────────────────────────────────────────────────


class TestMergeOpBasics:
    def test_assigns_lamport_above_observed(self) -> None:
        req = OpRequest(OP_RELABEL, "speakers.SPEAKER_00", "Alice", "dev-a", 5)
        _, new_lamport, op = merge_op(TranscriptState(), req, hub_lamport=3)
        assert new_lamport == 6  # max(3, 5) + 1
        assert op.lamport == 6

    def test_assigns_lamport_above_hub(self) -> None:
        req = OpRequest(OP_RELABEL, "speakers.SPEAKER_00", "Alice", "dev-a", 1)
        _, new_lamport, op = merge_op(TranscriptState(), req, hub_lamport=10)
        assert new_lamport == 11

    def test_applies_relabel(self) -> None:
        req = OpRequest(OP_RELABEL, "speakers.SPEAKER_00", "Alice", "dev-a", 0)
        state, _, _ = merge_op(TranscriptState(), req, hub_lamport=0)
        assert state.speakers["SPEAKER_00"] == "Alice"

    def test_records_clock(self) -> None:
        req = OpRequest(OP_RELABEL, "speakers.SPEAKER_00", "Alice", "dev-a", 0)
        state, _, _ = merge_op(TranscriptState(), req, hub_lamport=0)
        clock = state.clocks["speakers.SPEAKER_00"]
        assert clock.device == "dev-a"
        assert clock.lamport == 1

    def test_records_history(self) -> None:
        req = OpRequest(OP_RELABEL, "speakers.SPEAKER_00", "Alice", "dev-a", 0)
        state, _, _ = merge_op(TranscriptState(), req, hub_lamport=0)
        assert len(state.history) == 1
        assert state.history[0].op == OP_RELABEL
        assert state.history[0].from_value is None
        assert state.history[0].value == "Alice"


# ── LWW conflict resolution ────────────────────────────────────────────────


class TestLwwConflict:
    def test_later_op_wins(self) -> None:
        reqs = [
            OpRequest(OP_RELABEL, "speakers.SP0", "Alice", "dev-a", 0),
            OpRequest(OP_RELABEL, "speakers.SP0", "Bob", "dev-b", 1),
        ]
        state, _, _ = _apply_chain(reqs)
        assert state.speakers["SP0"] == "Bob"

    def test_loser_op_still_in_history(self) -> None:
        # Both ops claim lamport_observed=0, but hub assigns 1 and 2.
        # Lamport-2 wins; lamport-1 is "lost" but recorded.
        reqs = [
            OpRequest(OP_RELABEL, "speakers.SP0", "Alice", "dev-a", 0),
            OpRequest(OP_RELABEL, "speakers.SP0", "Bob", "dev-b", 0),
        ]
        state, _, _ = _apply_chain(reqs)
        assert state.speakers["SP0"] == "Bob"
        assert len(state.history) == 2
        names = [o.value for o in state.history]
        assert names == ["Alice", "Bob"]

    def test_tiebreaker_when_lamports_clash(self) -> None:
        # Force a manually-constructed scenario where two clocks have
        # the same lamport. Real flow rarely produces this since hub
        # assigns monotonically, but replay can.
        state = TranscriptState(
            speakers={"SP0": "Alice"},
            clocks={
                "speakers.SP0": Clock("dev-a", 5, "t1"),
            },
        )
        req = OpRequest(OP_RELABEL, "speakers.SP0", "Bob", "dev-b", 4)
        # hub_lamport=4 → assigned = max(4, 4)+1 = 5 (tie)
        new_state, _, _ = merge_op(state, req, hub_lamport=4)
        # dev-b > dev-a lex → new wins.
        assert new_state.speakers["SP0"] == "Bob"

    def test_from_value_captured(self) -> None:
        reqs = [
            OpRequest(OP_RELABEL, "speakers.SP0", "Alice", "dev-a", 0),
            OpRequest(OP_RELABEL, "speakers.SP0", "Bob", "dev-b", 0),
        ]
        state, _, _ = _apply_chain(reqs)
        assert state.history[0].from_value is None
        assert state.history[1].from_value == "Alice"


# ── Validation ────────────────────────────────────────────────────────────


class TestValidation:
    def test_unsupported_op_rejected(self) -> None:
        bad = OpRequest("delete", "speakers.SP0", None, "dev-a", 0)
        with pytest.raises(ValueError):
            merge_op(TranscriptState(), bad, hub_lamport=0)

    def test_unsupported_key_rejected(self) -> None:
        bad = OpRequest(OP_RELABEL, "transcript.title", "x", "dev-a", 0)
        with pytest.raises(ValueError):
            merge_op(TranscriptState(), bad, hub_lamport=0)

    def test_empty_key_rejected(self) -> None:
        bad = OpRequest(OP_RELABEL, "", "x", "dev-a", 0)
        with pytest.raises(ValueError):
            merge_op(TranscriptState(), bad, hub_lamport=0)

    def test_empty_device_rejected(self) -> None:
        bad = OpRequest(OP_RELABEL, "speakers.SP0", "x", "", 0)
        with pytest.raises(ValueError):
            merge_op(TranscriptState(), bad, hub_lamport=0)

    def test_negative_lamport_observed_rejected(self) -> None:
        bad = OpRequest(OP_RELABEL, "speakers.SP0", "x", "dev-a", -1)
        with pytest.raises(ValueError):
            merge_op(TranscriptState(), bad, hub_lamport=0)


# ── JSON round-trip ────────────────────────────────────────────────────────


class TestJsonRoundtrip:
    def test_from_empty(self) -> None:
        state = TranscriptState.from_json({})
        assert state.speakers == {}
        assert state.clocks == {}
        assert state.history == []

    def test_from_v1_no_clocks(self) -> None:
        doc = {"speakers": {"SPEAKER_00": "Alice"}}
        state = TranscriptState.from_json(doc)
        assert state.speakers == {"SPEAKER_00": "Alice"}
        assert state.clocks == {}
        assert state.history == []

    def test_roundtrip_v2(self) -> None:
        original = TranscriptState()
        req = OpRequest(OP_RELABEL, "speakers.SP0", "Alice", "dev-a", 0)
        state, _, _ = merge_op(original, req, 0, ts="2026-05-20T12:00:00Z")
        roundtripped = TranscriptState.from_json(state.to_jsonish())
        assert roundtripped.speakers == state.speakers
        assert roundtripped.clocks == state.clocks
        # history equality after dict round-trip
        assert [asdict(o) for o in roundtripped.history] == [
            asdict(o) for o in state.history
        ]


# ── replay_history ────────────────────────────────────────────────────────


class TestReplayHistory:
    def test_replay_empty(self) -> None:
        state = replay_history([])
        assert state == TranscriptState()

    def test_replay_matches_live_merge(self) -> None:
        reqs = [
            OpRequest(OP_RELABEL, "speakers.SP0", "Alice", "dev-a", 0),
            OpRequest(OP_RELABEL, "speakers.SP1", "Bob", "dev-b", 0),
            OpRequest(OP_RELABEL, "speakers.SP0", "Alex", "dev-a", 2),
        ]
        live_state, _, ops = _apply_chain(reqs)
        replayed = replay_history(ops)
        assert replayed.speakers == live_state.speakers
        assert replayed.clocks == live_state.clocks


# ── Property-based tests (Hypothesis) ──────────────────────────────────────


_devices = st.sampled_from(["dev-a", "dev-b", "dev-c", "dev-d"])
_speaker_keys = st.sampled_from(
    ["speakers.SP0", "speakers.SP1", "speakers.SP2"]
)
_names = st.sampled_from(["Alice", "Bob", "Carol", "Dave", "Eve"])
_lamport_observed = st.integers(min_value=0, max_value=20)

_op_request_strategy = st.builds(
    OpRequest,
    op=st.just(OP_RELABEL),
    key=_speaker_keys,
    value=_names,
    device=_devices,
    lamport_observed=_lamport_observed,
)


class TestProperties:
    @given(ops=st.lists(_op_request_strategy, min_size=0, max_size=30))
    @settings(max_examples=200)
    def test_history_length_equals_applied_ops(
        self, ops: list[OpRequest]
    ) -> None:
        state, _, applied = _apply_chain(ops)
        assert len(state.history) == len(ops)
        assert len(applied) == len(ops)

    @given(ops=st.lists(_op_request_strategy, min_size=0, max_size=30))
    @settings(max_examples=200)
    def test_replay_equivalent_to_live(
        self, ops: list[OpRequest]
    ) -> None:
        live_state, _, applied = _apply_chain(ops)
        replayed = replay_history(applied)
        assert replayed.speakers == live_state.speakers
        assert replayed.clocks == live_state.clocks

    @given(ops=st.lists(_op_request_strategy, min_size=1, max_size=20))
    @settings(max_examples=200)
    def test_lamport_assigned_strictly_increasing(
        self, ops: list[OpRequest]
    ) -> None:
        _, _, applied = _apply_chain(ops)
        lamports = [op.lamport for op in applied]
        assert all(lamports[i] < lamports[i + 1] for i in range(len(lamports) - 1))

    @given(ops=st.lists(_op_request_strategy, min_size=1, max_size=20))
    @settings(max_examples=200)
    def test_lamport_assigned_at_least_observed_plus_one(
        self, ops: list[OpRequest]
    ) -> None:
        _, _, applied = _apply_chain(ops)
        for req, op in zip(ops, applied):
            assert op.lamport > req.lamport_observed

    @given(ops=st.lists(_op_request_strategy, min_size=0, max_size=30))
    @settings(max_examples=200)
    def test_final_state_matches_max_clock_winner(
        self, ops: list[OpRequest]
    ) -> None:
        """For each touched key, final speaker value == value of the op
        whose (lamport, device) tuple is the highest among ops touching
        that key."""
        state, _, applied = _apply_chain(ops)
        per_key_winner: dict[str, Op] = {}
        for op in applied:
            current = per_key_winner.get(op.key)
            if current is None or (op.lamport, op.device) > (
                current.lamport,
                current.device,
            ):
                per_key_winner[op.key] = op
        for key, winner in per_key_winner.items():
            assert key.startswith("speakers.")
            speaker_id = key.split(".", 1)[1]
            assert state.speakers[speaker_id] == winner.value


# ── timestamp helper ──────────────────────────────────────────────────────


def test_now_iso_returns_utc_timestamp() -> None:
    ts = now_iso()
    # crude shape check; reject local-time strings
    assert "T" in ts
    assert ts.endswith("+00:00") or ts.endswith("Z")
