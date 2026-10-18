from __future__ import annotations

import pytest

from trio_kit.events import ControlChange, ModWheel, NoteOff, NoteOn, Panic, PitchBend, Sustain
from trio_kit.input import MidiNoteMap, MidiNoteOff, MidiNoteOn, MidiParser, parse_midi


def test_note_messages_and_zero_velocity_note_on_parse_to_channel_aware_commands() -> None:
    assert parse_midi(bytes((0x90, 60, 127))) == [MidiNoteOn(1, 60, 1.0)]
    assert parse_midi([0x92, 44, 64]) == [MidiNoteOn(3, 44, 64 / 127)]
    assert parse_midi([0x80, 60, 0]) == [MidiNoteOff(1, 60)]
    assert parse_midi([0x90, 60, 0]) == [MidiNoteOff(1, 60)]


def test_channel_filter_is_one_based_and_rejects_invalid_filters() -> None:
    message = [0x99, 60, 100]
    assert parse_midi(message, channel=10) == [MidiNoteOn(10, 60, 100 / 127)]
    assert parse_midi(message, channel=1) == []
    for channel in (0, 17, True, 1.5):
        with pytest.raises(ValueError, match="channel"):
            parse_midi(message, channel=channel)  # type: ignore[arg-type]


def test_pitch_bend_maps_center_and_both_extremes_to_configured_range() -> None:
    assert parse_midi([0xE0, 0, 0]) == [PitchBend(-2)]
    assert parse_midi([0xE0, 0, 64]) == [PitchBend(0)]
    assert parse_midi([0xE0, 127, 127]) == [PitchBend(2)]
    assert parse_midi([0xEF, 0, 0], bend_range=12) == [PitchBend(-12)]
    assert parse_midi([0xEF, 127, 127], bend_range=12) == [PitchBend(12)]
    with pytest.raises(ValueError, match="bend_range"):
        parse_midi([0xE0, 0, 64], bend_range=0.5)


def test_controller_bytes_produce_raw_cc_and_semantic_engine_events() -> None:
    assert parse_midi([0xB0, 64, 63]) == [ControlChange(64, 63), Sustain(False)]
    assert parse_midi([0xB0, 64, 64]) == [ControlChange(64, 64), Sustain(True)]
    assert parse_midi([0xB1, 1, 127]) == [ControlChange(1, 127), ModWheel(1)]
    assert parse_midi([0xB0, 74, 91]) == [ControlChange(74, 91)]
    assert parse_midi([0xB0, 120, 0]) == [ControlChange(120, 0), Panic()]
    assert parse_midi([0xB0, 123, 0]) == [ControlChange(123, 0), Panic()]


def test_realtime_and_system_exclusive_messages_are_ignored_including_interleaving() -> None:
    assert parse_midi([0xF8]) == []
    assert parse_midi([0xFE]) == []
    assert parse_midi([0xFF]) == []
    assert parse_midi([0xF0, 0x7D, 0x01, 0xF7]) == []
    assert parse_midi([0x90, 60, 0xF8, 100]) == [MidiNoteOn(1, 60, 100 / 127)]
    assert parse_midi([0x90, 60, 0xFF, 100]) == [MidiNoteOn(1, 60, 100 / 127)]


def test_malformed_messages_are_counted_and_do_not_raise() -> None:
    parser = MidiParser()
    for message in ([0x90, 60], [0x90, 60, 128], [0x10], "not bytes"):
        assert parser.parse(message) == []
    assert parser.malformed_count == 4
    assert parser.parse([0xF8]) == []
    assert parser.parse([0xF0, 0x7D, 0xF7]) == []
    assert parser.malformed_count == 4


def test_midi_note_map_releases_previous_same_channel_note_before_retrigger() -> None:
    note_map = MidiNoteMap()
    (first,) = note_map.translate(parse_midi([0x90, 60, 100]))
    assert isinstance(first, NoteOn)

    previous_off, retrigger = note_map.translate(parse_midi([0x90, 60, 80]))
    assert previous_off == NoteOff(first.note_id)
    assert isinstance(retrigger, NoteOn)
    assert retrigger.note_id != first.note_id
    assert note_map.translate(parse_midi([0x80, 60, 0])) == [NoteOff(retrigger.note_id)]
    assert note_map.active_notes == {}


def test_midi_note_ownership_is_separate_per_channel_and_panic_clears_all() -> None:
    note_map = MidiNoteMap()
    channel_one, = note_map.translate(parse_midi([0x90, 60, 100]))
    channel_two, = note_map.translate(parse_midi([0x91, 60, 100]))
    assert isinstance(channel_one, NoteOn) and isinstance(channel_two, NoteOn)
    assert note_map.translate(parse_midi([0x80, 60, 0])) == [NoteOff(channel_one.note_id)]
    assert note_map.active_notes == {(2, 60): channel_two.note_id}

    events = note_map.translate(parse_midi([0xB1, 123, 0]))
    assert events == [ControlChange(123, 0), Panic()]
    assert note_map.active_notes == {}


def test_midi_map_can_release_all_tracked_notes_on_disconnect() -> None:
    note_map = MidiNoteMap()
    first, second = (
        note_map.translate(parse_midi([0x90, 60, 100]))[0],
        note_map.translate(parse_midi([0x90, 61, 100]))[0],
    )
    assert isinstance(first, NoteOn) and isinstance(second, NoteOn)
    assert note_map.release_all() == [NoteOff(first.note_id), NoteOff(second.note_id)]
    assert note_map.active_notes == {}
