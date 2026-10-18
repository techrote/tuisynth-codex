"""Pure MIDI byte parsing and channel-aware note-id ownership."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import TypeAlias

from trio_kit.events import (
    ControlChange,
    Event,
    ModWheel,
    NoteIds,
    NoteOff,
    NoteOn,
    Panic,
    PitchBend,
    Sustain,
)
from trio_kit.input._ids import DEFAULT_INPUT_NOTE_IDS


@dataclass(frozen=True, slots=True)
class MidiNoteOn:
    """Parsed note-on command before it receives a process-local note id."""

    channel: int
    note: int
    velocity: float

    def __post_init__(self) -> None:
        if isinstance(self.channel, bool) or not isinstance(self.channel, int) or not 1 <= self.channel <= 16:
            raise ValueError("channel must be an integer in the range 1..16")
        if isinstance(self.note, bool) or not isinstance(self.note, int) or not 0 <= self.note <= 127:
            raise ValueError("note must be an integer in the range 0..127")
        if isinstance(self.velocity, bool) or not isinstance(self.velocity, Real):
            raise ValueError("velocity must be a finite number in the range 0..1")
        try:
            velocity = float(self.velocity)
        except (OverflowError, ValueError) as error:
            raise ValueError("velocity must be a finite number in the range 0..1") from error
        if not math.isfinite(velocity) or not 0 <= velocity <= 1:
            raise ValueError("velocity must be a finite number in the range 0..1")


@dataclass(frozen=True, slots=True)
class MidiNoteOff:
    """Parsed note-off command before note-id lookup."""

    channel: int
    note: int

    def __post_init__(self) -> None:
        if isinstance(self.channel, bool) or not isinstance(self.channel, int) or not 1 <= self.channel <= 16:
            raise ValueError("channel must be an integer in the range 1..16")
        if isinstance(self.note, bool) or not isinstance(self.note, int) or not 0 <= self.note <= 127:
            raise ValueError("note must be an integer in the range 0..127")


MidiCommand: TypeAlias = MidiNoteOn | MidiNoteOff | Sustain | ModWheel | PitchBend | ControlChange | Panic


def _channel_filter(channel: object | None) -> int | None:
    if channel is None:
        return None
    if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= 16:
        raise ValueError("channel must be None (omni) or an integer in the range 1..16")
    return channel


def _bend_range(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("bend_range must be a finite number in the range 1..12 semitones")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("bend_range must be a finite number in the range 1..12 semitones") from error
    if not math.isfinite(result) or not 1 <= result <= 12:
        raise ValueError("bend_range must be a finite number in the range 1..12 semitones")
    return result


def _normalize_message(message: object) -> tuple[int, ...] | None:
    if isinstance(message, (bytes, bytearray, memoryview)):
        values = tuple(message)
    elif isinstance(message, (list, tuple)):
        values = tuple(message)
    else:
        return None
    if not values:
        return None
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255 for value in values):
        return None
    return values


def _parse_message(
    message: object,
    *,
    channel: int | None,
    bend_range: float,
) -> tuple[list[MidiCommand], bool]:
    values = _normalize_message(message)
    if values is None:
        return [], True

    # System Exclusive messages and standalone real-time messages are ignored.
    if 0xF0 in values or values[0] == 0xF7:
        return [], False
    data = tuple(value for value in values if not 0xF8 <= value <= 0xFF)
    if not data:
        return [], False
    status = data[0]
    if status >= 0xF0:
        return [], False
    if status < 0x80:
        return [], True

    command = status & 0xF0
    expected_length = 2 if command in {0xC0, 0xD0} else 3
    if len(data) != expected_length or any(value >= 0x80 for value in data[1:]):
        return [], True
    midi_channel = (status & 0x0F) + 1
    if channel is not None and midi_channel != channel:
        return [], False

    first = data[1]
    second = data[2] if expected_length == 3 else 0
    if command == 0x80:
        return [MidiNoteOff(midi_channel, first)], False
    if command == 0x90:
        if second == 0:
            return [MidiNoteOff(midi_channel, first)], False
        return [MidiNoteOn(midi_channel, first, second / 127.0)], False
    if command == 0xB0:
        controller = ControlChange(first, second)
        if first == 64:
            return [controller, Sustain(second >= 64)], False
        if first == 1:
            return [controller, ModWheel(second / 127.0)], False
        if first in {120, 123}:
            return [controller, Panic()], False
        return [controller], False
    if command == 0xE0:
        bend_value = first | (second << 7)
        if bend_value < 8_192:
            semitones = (bend_value - 8_192) * bend_range / 8_192
        else:
            semitones = (bend_value - 8_192) * bend_range / 8_191
        return [PitchBend(semitones)], False
    # Other well-formed channel voice messages are unsupported and ignored.
    return [], False


def parse_midi(
    message: bytes | bytearray | list[int] | tuple[int, ...],
    *,
    channel: int | None = None,
    bend_range: float = 2.0,
) -> list[MidiCommand]:
    """Parse one MIDI message without touching devices or retaining state.

    `channel=None` accepts every channel. Malformed messages return an empty
    list; `MidiParser` adds a malformed-message counter for live input.
    """
    selected_channel = _channel_filter(channel)
    normalized_bend_range = _bend_range(bend_range)
    events, _malformed = _parse_message(
        message,
        channel=selected_channel,
        bend_range=normalized_bend_range,
    )
    return events


class MidiParser:
    """State-light parser configured for one input's channel and bend range."""

    def __init__(self, *, channel: int | None = None, bend_range: float = 2.0) -> None:
        self.channel = _channel_filter(channel)
        self.bend_range = _bend_range(bend_range)
        self.malformed_count = 0

    def parse(self, message: object) -> list[MidiCommand]:
        events, malformed = _parse_message(
            message,
            channel=self.channel,
            bend_range=self.bend_range,
        )
        if malformed:
            self.malformed_count += 1
        return events


class MidiNoteMap:
    """Translate channel/note pairs to stable engine note IDs."""

    def __init__(self, note_ids: NoteIds | None = None) -> None:
        if note_ids is not None and not isinstance(note_ids, NoteIds):
            raise ValueError("note_ids must be a NoteIds allocator")
        self._note_ids = DEFAULT_INPUT_NOTE_IDS if note_ids is None else note_ids
        self._active: dict[tuple[int, int], int] = {}

    @property
    def active_notes(self) -> Mapping[tuple[int, int], int]:
        return MappingProxyType(dict(self._active))

    def translate(self, commands: list[MidiCommand] | tuple[MidiCommand, ...]) -> list[Event]:
        """Convert parsed MIDI commands into engine events in arrival order."""
        events: list[Event] = []
        for command in commands:
            if isinstance(command, MidiNoteOn):
                key = (command.channel, command.note)
                previous = self._active.pop(key, None)
                if previous is not None:
                    events.append(NoteOff(previous))
                note_id = self._note_ids.next()
                self._active[key] = note_id
                events.append(NoteOn(note_id, float(command.note), command.velocity, "midi"))
            elif isinstance(command, MidiNoteOff):
                note_id = self._active.pop((command.channel, command.note), None)
                if note_id is not None:
                    events.append(NoteOff(note_id))
            elif isinstance(command, Panic):
                self._active.clear()
                events.append(command)
            else:
                events.append(command)
        return events

    def release_all(self) -> list[Event]:
        """Release every tracked MIDI note while retaining allocator state."""
        active = tuple(self._active.values())
        self._active.clear()
        return [NoteOff(note_id) for note_id in active]

    def panic(self) -> list[Event]:
        self._active.clear()
        return [Panic()]


__all__ = ["MidiCommand", "MidiNoteMap", "MidiNoteOff", "MidiNoteOn", "MidiParser", "parse_midi"]
