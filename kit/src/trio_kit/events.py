"""Validated immutable events shared by input, sequencing, and the engine."""

from __future__ import annotations

import math
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import TypeAlias

from trio_kit.constants import BLOCK, MAX_EVENT_QUEUE


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _frame(value: object) -> int:
    frame = _integer(value, "frame")
    if not 0 <= frame < BLOCK:
        raise ValueError(f"frame must be in the range 0..{BLOCK - 1}")
    return frame


def _freeze_json_value(value: object, *, active: set[int] | None = None, depth: int = 0) -> object:
    """Copy JSON-shaped event payloads into recursively immutable containers."""
    if depth > 16:
        raise ValueError("preset extras exceed 16 nested levels")
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Real):
        _finite_number(value, "preset extra")
        return value
    seen = set() if active is None else active
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            raise ValueError("preset extras cannot contain cycles")
        seen.add(identity)
        try:
            copied: dict[str, object] = {}
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("preset extra object keys must be strings")
                copied[key] = _freeze_json_value(child, active=seen, depth=depth + 1)
            return MappingProxyType(copied)
        finally:
            seen.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen:
            raise ValueError("preset extras cannot contain cycles")
        seen.add(identity)
        try:
            return tuple(_freeze_json_value(child, active=seen, depth=depth + 1) for child in value)
        finally:
            seen.remove(identity)
    raise ValueError("preset extras must contain JSON values")


@dataclass(frozen=True, slots=True)
class NoteOn:
    note_id: int
    pitch: float
    velocity: float
    source: str
    frame: int = 0

    def __post_init__(self) -> None:
        note_id = _integer(self.note_id, "note_id")
        if note_id <= 0:
            raise ValueError("note_id must be a positive integer")
        pitch = _finite_number(self.pitch, "pitch")
        if not 0.0 <= pitch <= 127.0:
            raise ValueError("pitch must be in the range 0..127")
        velocity = _finite_number(self.velocity, "velocity")
        if not 0.0 <= velocity <= 1.0:
            raise ValueError("velocity must be in the range 0..1")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        _frame(self.frame)


@dataclass(frozen=True, slots=True)
class NoteOff:
    note_id: int
    frame: int = 0

    def __post_init__(self) -> None:
        note_id = _integer(self.note_id, "note_id")
        if note_id <= 0:
            raise ValueError("note_id must be a positive integer")
        _frame(self.frame)


@dataclass(frozen=True, slots=True)
class Sustain:
    on: bool

    def __post_init__(self) -> None:
        if not isinstance(self.on, bool):
            raise ValueError("sustain state must be a boolean")


@dataclass(frozen=True, slots=True)
class PitchBend:
    semitones: float

    def __post_init__(self) -> None:
        bend = _finite_number(self.semitones, "pitch bend")
        if not -12.0 <= bend <= 12.0:
            raise ValueError("pitch bend must be in the range -12..12 semitones")


@dataclass(frozen=True, slots=True)
class ModWheel:
    value: float

    def __post_init__(self) -> None:
        value = _finite_number(self.value, "mod wheel")
        if not 0.0 <= value <= 1.0:
            raise ValueError("mod wheel must be in the range 0..1")


@dataclass(frozen=True, slots=True)
class ControlChange:
    cc: int
    value: int

    def __post_init__(self) -> None:
        cc = _integer(self.cc, "CC number")
        value = _integer(self.value, "CC value")
        if not 0 <= cc <= 127:
            raise ValueError("CC number must be in the range 0..127")
        if not 0 <= value <= 127:
            raise ValueError("CC value must be in the range 0..127")


@dataclass(frozen=True, slots=True)
class ParamSet:
    key: str
    value: int | float

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("parameter key must be a non-empty string")
        _finite_number(self.value, f"parameter {self.key}")


@dataclass(frozen=True, slots=True)
class PresetApply:
    """Apply a complete parameter map and instrument extras at a block boundary."""

    params: Mapping[str, int | float]
    extras: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.params, Mapping) or not isinstance(self.extras, Mapping):
            raise ValueError("preset parameters and extras must be mappings")
        params: dict[str, int | float] = {}
        for key, value in self.params.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("preset parameter keys must be non-empty strings")
            _finite_number(value, f"parameter {key}")
            params[key] = value
        extras = _freeze_json_value(self.extras)
        if not isinstance(extras, Mapping):
            raise ValueError("preset extras must be an object")
        object.__setattr__(self, "params", MappingProxyType(params))
        object.__setattr__(self, "extras", MappingProxyType(extras))


@dataclass(frozen=True, slots=True)
class RetargetNote:
    """Retarget one held note for an instrument with legato glide support."""

    note_id: int
    pitch: float
    frame: int = 0

    def __post_init__(self) -> None:
        note_id = _integer(self.note_id, "note_id")
        if note_id <= 0:
            raise ValueError("note_id must be a positive integer")
        pitch = _finite_number(self.pitch, "pitch")
        if not 0.0 <= pitch <= 127.0:
            raise ValueError("pitch must be in the range 0..127")
        _frame(self.frame)


@dataclass(frozen=True, slots=True)
class InstrumentEvent:
    name: str
    payload: tuple[float | int | str, ...]
    frame: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("instrument event name must be a non-empty string")
        if not isinstance(self.payload, tuple):
            raise ValueError("instrument event payload must be a tuple")
        for value in self.payload:
            if isinstance(value, str):
                continue
            _finite_number(value, "instrument event payload value")
        _frame(self.frame)


@dataclass(frozen=True, slots=True)
class Panic:
    """Release all voices and clear sustain."""


@dataclass(frozen=True, slots=True)
class Transport:
    tempo: float = 120.0
    swing: float = 0.0
    playing: bool = False
    frame: int = 0

    def __post_init__(self) -> None:
        tempo = _finite_number(self.tempo, "tempo")
        swing = _finite_number(self.swing, "swing")
        if not 40.0 <= tempo <= 240.0:
            raise ValueError("tempo must be in the range 40..240 BPM")
        if not 0.0 <= swing <= 0.6:
            raise ValueError("swing must be in the range 0..0.6")
        if not isinstance(self.playing, bool):
            raise ValueError("playing must be a boolean")
        _frame(self.frame)


Event: TypeAlias = NoteOn | NoteOff | Sustain | PitchBend | ModWheel | ControlChange | ParamSet | PresetApply | RetargetNote | InstrumentEvent | Panic | Transport


def is_release_critical(event: Event) -> bool:
    """Whether an overflow policy must preserve this event's release semantics."""
    return isinstance(event, (NoteOff, Panic)) or isinstance(event, Sustain) and not event.on


class EventQueue:
    """Bounded FIFO event queue with release-safe overflow handling.

    Queue insertion never waits for capacity. When full, the oldest parameter
    update is evicted first. A critical note-off/sustain-off then evicts the
    oldest non-critical event. If every queued event is release-critical, the
    queue collapses to one panic event: this discards individual releases only
    after replacing them with the stronger all-notes-off action.
    """

    def __init__(self, maxsize: int = MAX_EVENT_QUEUE) -> None:
        maxsize = _integer(maxsize, "maxsize")
        if maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self._maxsize = maxsize
        self._events: deque[Event] = deque()
        self._lock = threading.Lock()
        self._dropped_events = 0
        self._overflow_count = 0
        self._panic_fallbacks = 0

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def push(self, event: Event) -> bool:
        if not isinstance(event, (NoteOn, NoteOff, Sustain, PitchBend, ModWheel, ControlChange, ParamSet, PresetApply, RetargetNote, InstrumentEvent, Panic, Transport)):
            raise TypeError("event queue accepts only trio_kit event instances")
        with self._lock:
            if isinstance(event, Panic):
                self._dropped_events += len(self._events)
                self._events.clear()
                self._events.append(event)
                return True
            if len(self._events) < self._maxsize:
                self._events.append(event)
                return True

            self._overflow_count += 1
            parameter_index = next(
                (index for index, queued in enumerate(self._events) if isinstance(queued, (ParamSet, PresetApply))),
                None,
            )
            if parameter_index is not None:
                del self._events[parameter_index]
                self._dropped_events += 1
            elif is_release_critical(event):
                noncritical_index = next((index for index, queued in enumerate(self._events) if not is_release_critical(queued)), None)
                if noncritical_index is not None:
                    del self._events[noncritical_index]
                    self._dropped_events += 1
                else:
                    self._dropped_events += len(self._events)
                    self._events.clear()
                    self._events.append(Panic())
                    self._panic_fallbacks += 1
                    return True
            else:
                noncritical_index = next((index for index, queued in enumerate(self._events) if not is_release_critical(queued)), None)
                if noncritical_index is None:
                    self._dropped_events += 1
                    return False
                del self._events[noncritical_index]
                self._dropped_events += 1
            self._events.append(event)
            return True

    def drain(self) -> tuple[Event, ...]:
        with self._lock:
            drained = tuple(self._events)
            self._events.clear()
            return drained

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def dropped_events(self) -> int:
        with self._lock:
            return self._dropped_events

    @property
    def overflow_count(self) -> int:
        with self._lock:
            return self._overflow_count

    @property
    def panic_fallbacks(self) -> int:
        with self._lock:
            return self._panic_fallbacks


class NoteIds:
    """Allocate monotonic positive note ids safely from concurrent producers."""

    def __init__(self, start: int = 1) -> None:
        start = _integer(start, "start")
        if start <= 0:
            raise ValueError("start must be a positive integer")
        self._next_id = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            note_id = self._next_id
            self._next_id += 1
            return note_id


__all__ = [
    "ControlChange",
    "Event",
    "EventQueue",
    "InstrumentEvent",
    "ModWheel",
    "NoteIds",
    "NoteOff",
    "NoteOn",
    "Panic",
    "ParamSet",
    "PitchBend",
    "Sustain",
    "Transport",
    "is_release_critical",
]
