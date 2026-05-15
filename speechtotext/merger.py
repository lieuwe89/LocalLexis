from __future__ import annotations

from speechtotext.models import LabeledSegment, Segment, SpeakerTurn

_MIN_OVERLAP_SECONDS = 0.050  # 50ms


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def merge(
    segments: list[Segment], turns: list[SpeakerTurn]
) -> list[LabeledSegment]:
    out: list[LabeledSegment] = []
    for seg in segments:
        best_id = "UNKNOWN"
        best_overlap = 0.0
        for turn in turns:
            ov = _overlap(seg.start, seg.end, turn.start, turn.end)
            if ov > best_overlap:
                best_overlap = ov
                best_id = turn.speaker_id
        if best_overlap < _MIN_OVERLAP_SECONDS:
            best_id = "UNKNOWN"
        out.append(
            LabeledSegment(
                start=seg.start, end=seg.end, text=seg.text, speaker_id=best_id
            )
        )
    return out
