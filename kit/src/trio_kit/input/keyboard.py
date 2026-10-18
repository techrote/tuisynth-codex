"""Pure timed-gate computer-keyboard piano input."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from numbers import Real

from trio_kit.events import Event, NoteIds, NoteOff, NoteOn, Panic
from trio_kit.input._ids import DEFAULT_INPUT_NOTE_IDS


_KEY_OFFSETS = {
    "z": 0,
    "s": 1,
    "x": 2,
    "d": 3,
    "c": 4,
    "v": 5,
    "g": 6,
    "b": 7,
    "h": 8,
    "n": 9,
    "j": 10,
    "m": 11,
    "q": 12,
    "2": 13,
    "w": 14,
    "3": 15,
    "e": 16,
    "r": 17,
    "5": 18,
    "t": 19,
    "6": 20,
    "y": 21,
    "7": 22,
    "u": 23,
    "i": 24,
    "9": 25,
    "o": 26,
    "0": 27,
    "p": 28,
}
_VELOCITIES = (0.25, 0.4, 0.55, 0.7, 0.85, 1.0)


def _time_value(value: object | None) -> float:
    if value is None:
        return time.monotonic()
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("now must be a finite time in seconds")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("now must be a finite time in seconds") from error
    if not math.isfinite(result):
        raise ValueError("now must be a finite time in seconds")
    return result


@dataclass(slots=True)
class _ActiveKey:
    note_id: int
    pitch: int
    expires_at: float | None
    latched: bool


class KeyboardPiano:
    """Tracker-style two-row piano whose notes release when repeats stop.

    `now` values are monotonic seconds. Passing times explicitly makes gate
    behavior deterministic in tests and applications with their own clock.
    """

    def __init__(self, *, gate_ms: int = 450, note_ids: NoteIds | None = None) -> None:
        if isinstance(gate_ms, bool) or not isinstance(gate_ms, int) or not 150 <= gate_ms <= 2_000:
            raise ValueError("gate_ms must be an integer in the range 150..2000")
        if note_ids is not None and not isinstance(note_ids, NoteIds):
            raise ValueError("note_ids must be a NoteIds allocator")
        self._gate_ms = gate_ms
        self._note_ids = DEFAULT_INPUT_NOTE_IDS if note_ids is None else note_ids
        self._active: dict[str, _ActiveKey] = {}
        self._octave = 0
        self._velocity_index = 3
        self._latch = False

    @property
    def octave(self) -> int:
        return self._octave

    @property
    def velocity(self) -> float:
        return _VELOCITIES[self._velocity_index]

    @property
    def latch(self) -> bool:
        return self._latch

    @property
    def gate_ms(self) -> int:
        return self._gate_ms

    def set_gate_ms(self, gate_ms: int) -> None:
        if isinstance(gate_ms, bool) or not isinstance(gate_ms, int) or not 150 <= gate_ms <= 2_000:
            raise ValueError("gate_ms must be an integer in the range 150..2000")
        self._gate_ms = gate_ms

    @property
    def active_note_ids(self) -> dict[str, int]:
        return {key: note.note_id for key, note in self._active.items()}

    def _release(self, key: str) -> NoteOff:
        active = self._active.pop(key)
        return NoteOff(active.note_id)

    def tick(self, now: float | None = None) -> list[Event]:
        """Release timed notes whose repeat gate has expired."""
        timestamp = _time_value(now)
        expired = [
            key
            for key, active in self._active.items()
            if active.expires_at is not None and active.expires_at <= timestamp
        ]
        return [self._release(key) for key in expired]

    def release_all(self, *, panic: bool = False) -> list[Event]:
        """Release tracked keys, or send a global panic when requested."""
        if not isinstance(panic, bool):
            raise ValueError("panic must be a boolean")
        if panic:
            self._active.clear()
            return [Panic()]
        return [self._release(key) for key in tuple(self._active)]

    def press(self, key: str, now: float | None = None) -> list[Event]:
        """Handle one terminal key press and return any engine events."""
        timestamp = _time_value(now)
        events = self.tick(timestamp)
        if not isinstance(key, str):
            return events
        normalized = key.casefold()

        if normalized == "f9":
            return events + self.release_all(panic=True)
        if normalized == "-":
            self._octave = max(-3, self._octave - 1)
            return events
        if normalized == "=":
            self._octave = min(3, self._octave + 1)
            return events
        if normalized == "[":
            self._velocity_index = max(0, self._velocity_index - 1)
            return events
        if normalized == "]":
            self._velocity_index = min(len(_VELOCITIES) - 1, self._velocity_index + 1)
            return events
        if normalized == "'":
            self._latch = not self._latch
            if not self._latch:
                latched_keys = [key for key, active in self._active.items() if active.latched]
                events.extend(self._release(key) for key in latched_keys)
            return events

        offset = _KEY_OFFSETS.get(normalized)
        if offset is None:
            return events

        active = self._active.get(normalized)
        if active is not None:
            if self._latch:
                events.append(self._release(normalized))
            else:
                active.expires_at = timestamp + self._gate_ms / 1_000.0
            return events

        pitch = 48 + offset + 12 * self._octave
        note_id = self._note_ids.next()
        self._active[normalized] = _ActiveKey(
            note_id=note_id,
            pitch=pitch,
            expires_at=None if self._latch else timestamp + self._gate_ms / 1_000.0,
            latched=self._latch,
        )
        events.append(NoteOn(note_id, pitch, self.velocity, "keyboard"))
        return events


__all__ = ["KeyboardPiano"]
