from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from trio_kit.events import (
    EventQueue,
    InstrumentEvent,
    ModWheel,
    NoteIds,
    NoteOff,
    NoteOn,
    Panic,
    ParamSet,
    PresetApply,
    PitchBend,
    RetargetNote,
    Sustain,
    Transport,
)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: NoteOn(0, 60, 1, "keyboard"),
        lambda: NoteOn(1, 128, 1, "keyboard"),
        lambda: NoteOn(1, 60, float("nan"), "keyboard"),
        lambda: NoteOn(1, 60, 1, " "),
        lambda: NoteOff(-1),
        lambda: Sustain(1),
        lambda: PitchBend(12.1),
        lambda: ModWheel(float("inf")),
        lambda: ParamSet("", 1),
        lambda: InstrumentEvent("pluck", [60]),
        lambda: InstrumentEvent("pluck", (True,)),
        lambda: Transport(tempo=39),
        lambda: Transport(swing=0.61),
        lambda: NoteOn(1, 60, 1, "keyboard", frame=256),
    ),
)
def test_invalid_events_are_rejected_at_construction(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()  # type: ignore[operator]


def test_events_are_immutable_and_accept_valid_ranges() -> None:
    event = NoteOn(1, 0, 0, "mouse", frame=255)
    assert event.pitch == 0
    assert event.velocity == 0
    assert Transport(tempo=240, swing=0.6, playing=True).playing
    assert InstrumentEvent("pluck", (60, 0.5, "soft"), frame=64).payload[-1] == "soft"
    with pytest.raises(FrozenInstanceError):
        event.pitch = 61  # type: ignore[misc]


def test_preset_apply_deep_freezes_json_extras_and_retarget_validates_note_range() -> None:
    extras = {"voices": [{"wave": "sine"}]}
    event = PresetApply({"amp.gain": 0.5}, extras)
    extras["voices"][0]["wave"] = "saw"
    assert event.extras["voices"][0]["wave"] == "sine"
    with pytest.raises(TypeError):
        event.extras["voices"][0]["wave"] = "triangle"  # type: ignore[index]
    with pytest.raises(ValueError, match="0..127"):
        RetargetNote(1, 128)


def test_note_ids_are_monotonic_and_unique_across_threads() -> None:
    ids = NoteIds()
    with ThreadPoolExecutor(max_workers=8) as executor:
        assigned = list(executor.map(lambda _: ids.next(), range(1_000)))

    assert len(set(assigned)) == 1_000
    assert sorted(assigned) == list(range(1, 1_001))
    assert NoteIds(start=9).next() == 9


def test_event_queue_accepts_concurrent_producers_without_losing_events() -> None:
    queue = EventQueue(maxsize=1_000)
    with ThreadPoolExecutor(max_workers=8) as executor:
        accepted = list(executor.map(lambda note_id: queue.push(NoteOn(note_id, 60, 1, "test")), range(1, 1_001)))

    assert all(accepted)
    assert len(queue) == 1_000
    assert len(queue.drain()) == 1_000
    assert EventQueue().maxsize == 4_096


def test_event_queue_evicts_parameter_changes_before_note_releases() -> None:
    queue = EventQueue(maxsize=2)
    assert queue.push(ParamSet("amp.level", 0.2))
    assert queue.push(NoteOn(1, 60, 1, "keyboard"))
    assert queue.push(NoteOff(1))

    assert queue.drain() == (NoteOn(1, 60, 1, "keyboard"), NoteOff(1))
    assert queue.maxsize == 2
    assert queue.dropped_events == 1
    assert queue.overflow_count == 1
    assert queue.panic_fallbacks == 0


def test_full_release_critical_queue_collapses_to_panic_instead_of_stranding_notes() -> None:
    queue = EventQueue(maxsize=2)
    queue.push(NoteOff(1))
    queue.push(Sustain(False))

    assert queue.push(NoteOff(2))
    assert queue.drain() == (Panic(),)
    assert queue.panic_fallbacks == 1
    assert queue.dropped_events == 2


def test_noncritical_event_cannot_displace_a_full_queue_of_releases() -> None:
    queue = EventQueue(maxsize=1)
    queue.push(NoteOff(1))

    assert not queue.push(NoteOn(2, 64, 1, "keyboard"))
    assert queue.drain() == (NoteOff(1),)
    assert queue.dropped_events == 1


def test_explicit_panic_clears_pending_events_and_is_always_accepted() -> None:
    queue = EventQueue(maxsize=1)
    queue.push(NoteOn(1, 60, 1, "keyboard"))

    assert queue.push(Panic())
    assert queue.drain() == (Panic(),)
    assert queue.dropped_events == 1


def test_event_queue_size_is_fixed_after_creation() -> None:
    queue = EventQueue(maxsize=2)
    with pytest.raises(AttributeError):
        queue.maxsize = 3  # type: ignore[misc]
