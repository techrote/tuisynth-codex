from __future__ import annotations

import pytest

from trio_kit.events import NoteOff, NoteOn, Panic
from trio_kit.input import KeyboardPiano, MidiNoteMap, parse_midi


@pytest.mark.parametrize(
    ("key", "pitch"),
    (
        ("z", 48), ("s", 49), ("x", 50), ("d", 51), ("c", 52), ("v", 53),
        ("g", 54), ("b", 55), ("h", 56), ("n", 57), ("j", 58), ("m", 59),
        ("q", 60), ("2", 61), ("w", 62), ("3", 63), ("e", 64), ("r", 65),
        ("5", 66), ("t", 67), ("6", 68), ("y", 69), ("7", 70), ("u", 71),
        ("i", 72), ("9", 73), ("o", 74), ("0", 75), ("p", 76),
    ),
)
def test_keyboard_layout_maps_every_key_to_its_contract_pitch(key: str, pitch: int) -> None:
    piano = KeyboardPiano()
    (event,) = piano.press(key, 1.0)

    assert isinstance(event, NoteOn)
    assert event.pitch == pitch
    assert event.velocity == pytest.approx(0.7)
    assert event.source == "keyboard"


def test_timed_gate_repeat_extends_deadline_and_releases_the_original_note_id() -> None:
    piano = KeyboardPiano(gate_ms=450)
    (started,) = piano.press("z", 10.0)
    assert isinstance(started, NoteOn)
    assert piano.press("z", 10.3) == []
    assert piano.tick(10.7) == []

    (released,) = piano.tick(10.751)
    assert released == NoteOff(started.note_id)


def test_octave_changes_only_affect_new_notes_and_limits_are_clamped() -> None:
    piano = KeyboardPiano()
    original, = piano.press("z", 1.0)
    assert isinstance(original, NoteOn)
    piano.press("=", 1.1)
    (old_release,) = piano.tick(1.451)
    assert old_release == NoteOff(original.note_id)
    (shifted,) = piano.press("z", 1.5)
    assert isinstance(shifted, NoteOn)
    assert shifted.pitch == 60

    limited = KeyboardPiano()
    for _ in range(5):
        limited.press("=", 2.0)
    assert limited.octave == 3
    (high,) = limited.press("z", 2.1)
    assert isinstance(high, NoteOn)
    assert high.pitch == 84

    for _ in range(6):
        limited.press("-", 2.2)
    assert limited.octave == -3
    limited.tick(2.551)
    (low,) = limited.press("z", 2.6)
    assert isinstance(low, NoteOn)
    assert low.pitch == 12


def test_velocity_steps_clamp_to_the_documented_six_values() -> None:
    piano = KeyboardPiano()
    assert piano.velocity == 0.7
    for _ in range(6):
        piano.press("]", 0)
    assert piano.velocity == 1.0
    for _ in range(6):
        piano.press("[", 0)
    assert piano.velocity == 0.25
    (event,) = piano.press("z", 0)
    assert isinstance(event, NoteOn)
    assert event.velocity == 0.25


def test_latch_toggles_notes_and_disabling_latch_releases_remaining_latches() -> None:
    piano = KeyboardPiano(gate_ms=150)
    assert piano.press("'", 0) == []
    (first,) = piano.press("q", 0)
    assert isinstance(first, NoteOn)
    assert piano.tick(5) == []
    assert piano.press("q", 5) == [NoteOff(first.note_id)]

    (second,) = piano.press("q", 6)
    assert isinstance(second, NoteOn)
    assert piano.press("'", 6) == [NoteOff(second.note_id)]
    assert not piano.latch
    assert piano.active_note_ids == {}


def test_f9_sends_panic_and_release_all_sends_noteoffs() -> None:
    piano = KeyboardPiano()
    first, second = piano.press("z", 0) + piano.press("q", 0)
    assert isinstance(first, NoteOn) and isinstance(second, NoteOn)
    assert piano.release_all() == [NoteOff(first.note_id), NoteOff(second.note_id)]
    assert piano.active_note_ids == {}

    piano.press("z", 1)
    assert piano.press("F9", 1.1) == [Panic()]
    assert piano.active_note_ids == {}


def test_keyboard_validation_and_unmapped_keys_are_safe() -> None:
    for gate_ms in (True, 149, 2_001, 450.0):
        with pytest.raises(ValueError, match="gate_ms"):
            KeyboardPiano(gate_ms=gate_ms)  # type: ignore[arg-type]
    piano = KeyboardPiano()
    with pytest.raises(ValueError, match="gate_ms"):
        piano.set_gate_ms(100)
    assert piano.press("a", 0) == []
    with pytest.raises(ValueError, match="now"):
        piano.press("z", float("nan"))


def test_default_keyboard_and_midi_note_ids_share_one_allocator() -> None:
    keyboard = KeyboardPiano()
    midi = MidiNoteMap()
    (keyboard_note,) = keyboard.press("z", 0)
    (midi_note,) = midi.translate(parse_midi([0x90, 60, 100]))

    assert isinstance(keyboard_note, NoteOn) and isinstance(midi_note, NoteOn)
    assert keyboard_note.note_id != midi_note.note_id
