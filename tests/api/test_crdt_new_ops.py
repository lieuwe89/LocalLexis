from __future__ import annotations

import pytest

from speechtotext.api.crdt import (
    Clock,
    OpRequest,
    TranscriptState,
    merge_op,
    replay_history,
)


def _doc():
    return {
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hello"},
            {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "world"},
        ],
        "title": None,
        "_clocks": {},
        "_history": [],
    }


def test_from_json_loads_title_and_segment_texts():
    doc = _doc()
    doc["title"] = "Standup"
    state = TranscriptState.from_json(doc)
    assert state.title == "Standup"
    assert state.segment_texts == {"0": "hello", "1": "world"}


def test_set_title_applies():
    state = TranscriptState.from_json(_doc())
    req = OpRequest(op="set_title", key="title", value="Weekly sync",
                    device="dev-a", lamport_observed=0)
    new_state, lamport, op = merge_op(state, req, 0)
    assert new_state.title == "Weekly sync"
    assert op.from_value is None
    assert lamport == 1


def test_edit_segment_applies_and_records_from_value():
    state = TranscriptState.from_json(_doc())
    req = OpRequest(op="edit_segment", key="segments.1.text", value="world!",
                    device="dev-a", lamport_observed=0)
    new_state, _, op = merge_op(state, req, 0)
    assert new_state.segment_texts["1"] == "world!"
    assert op.from_value == "world"


def test_edit_segment_out_of_range_rejected():
    state = TranscriptState.from_json(_doc())
    req = OpRequest(op="edit_segment", key="segments.9.text", value="x",
                    device="dev-a", lamport_observed=0)
    with pytest.raises(ValueError, match="segment index"):
        merge_op(state, req, 0)


def test_edit_segment_bad_key_shapes_rejected():
    state = TranscriptState.from_json(_doc())
    for key in ("segments.text", "segments.1", "segments.x.text", "title"):
        req = OpRequest(op="edit_segment", key=key, value="x",
                        device="dev-a", lamport_observed=0)
        with pytest.raises(ValueError):
            merge_op(state, req, 0)


def test_set_title_requires_title_key():
    state = TranscriptState.from_json(_doc())
    req = OpRequest(op="set_title", key="speakers.SPEAKER_00", value="x",
                    device="dev-a", lamport_observed=0)
    with pytest.raises(ValueError):
        merge_op(state, req, 0)


def test_lww_older_title_op_loses():
    state = TranscriptState.from_json(_doc())
    r1 = OpRequest(op="set_title", key="title", value="First",
                   device="dev-a", lamport_observed=5)
    state, lamport, _ = merge_op(state, r1, 5)  # assigned lamport 6
    r2 = OpRequest(op="set_title", key="title", value="Second",
                   device="dev-b", lamport_observed=0)
    # hub counter already at `lamport`; new op gets lamport 7 and wins
    state, _, _ = merge_op(state, r2, lamport)
    assert state.title == "Second"
    # both ops recorded in history
    assert [op.value for op in state.history] == ["First", "Second"]


def test_replay_history_rebuilds_title_and_segments():
    state = TranscriptState.from_json(_doc())
    for req in (
        OpRequest(op="set_title", key="title", value="T", device="a", lamport_observed=0),
        OpRequest(op="edit_segment", key="segments.0.text", value="hi", device="a", lamport_observed=0),
        OpRequest(op="relabel", key="speakers.SPEAKER_00", value="Bob", device="a", lamport_observed=0),
    ):
        state, lamport, _ = merge_op(state, req, len(state.history))
    replayed = replay_history(state.history)
    assert replayed.title == "T"
    assert replayed.segment_texts.get("0") == "hi"
    assert replayed.speakers.get("SPEAKER_00") == "Bob"
