"""Cell-accurate clickable piano keyboard for terminal layouts."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable
from numbers import Real

from trio_kit.events import Event, NoteIds, NoteOff, NoteOn, RetargetNote
from trio_kit.input._ids import DEFAULT_INPUT_NOTE_IDS
from trio_kit.tui.canvas import Canvas, Rect
from trio_kit.tui.mouse import MouseInput
from trio_kit.tui.widgets import Widget


_WHITE = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}
_BLACK = {1: 0, 3: 1, 6: 3, 8: 4, 10: 5}
_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


class PianoWidget(Widget):
    """A two-octave default piano whose draw and hit rectangles share geometry."""

    def __init__(
        self,
        tag: str,
        bounds: Rect,
        on_event: Callable[[Event], object] | None = None,
        *,
        start_note: int = 48,
        octaves: int = 2,
        black_height: int | None = None,
        gate_ms: int = 450,
        note_ids: NoteIds | None = None,
        legato_glide: bool = False,
    ) -> None:
        super().__init__(tag, bounds, label="On-screen keyboard")
        if bounds.height < 3:
            raise ValueError("piano bounds must be at least three cells high")
        if isinstance(start_note, bool) or not isinstance(start_note, int) or not 0 <= start_note <= 95:
            raise ValueError("start_note must be an integer C pitch in the range 0..95")
        if start_note % 12 != 0:
            raise ValueError("start_note must be a C note")
        if isinstance(octaves, bool) or not isinstance(octaves, int) or not 1 <= octaves <= 4:
            raise ValueError("octaves must be an integer in the range 1..4")
        needed_width = octaves * 7 * 3
        if bounds.width < needed_width:
            raise ValueError(f"piano bounds must be at least {needed_width} cells wide")
        height = max(1, bounds.height // 2) if black_height is None else black_height
        if isinstance(height, bool) or not isinstance(height, int) or not 1 <= height < bounds.height:
            raise ValueError("black_height must be an integer within the key area")
        if isinstance(gate_ms, bool) or not isinstance(gate_ms, int) or not 150 <= gate_ms <= 2_000:
            raise ValueError("gate_ms must be an integer in the range 150..2000")
        if note_ids is not None and not isinstance(note_ids, NoteIds):
            raise ValueError("note_ids must be a NoteIds allocator")
        if not isinstance(legato_glide, bool):
            raise ValueError("legato_glide must be a boolean")
        self.start_note = start_note
        self.octaves = octaves
        self.black_height = height
        self.gate_ms = gate_ms
        self.legato_glide = legato_glide
        self.on_event = on_event
        self._note_ids = DEFAULT_INPUT_NOTE_IDS if note_ids is None else note_ids
        self._octave = 0
        self._cursor = 0
        self._latches: set[int] = set()
        self._latched_notes: dict[int, int] = {}
        self._external_sounding: set[int] = set()
        self._mouse_down = False
        self._mouse_last_pitch: int | None = None
        self._mouse_note: tuple[int, int, float] | None = None
        self._twin_note: tuple[int, int, float] | None = None
        self._twin_deadline: float | None = None
        self._events: list[Event] = []

    @property
    def octave(self) -> int:
        return self._octave

    @property
    def cursor_pitch(self) -> int:
        return self._base_pitch + self._cursor

    @property
    def _base_pitch(self) -> int:
        return self.start_note + 12 * self._octave

    @property
    def pitches(self) -> tuple[int, ...]:
        return tuple(self._base_pitch + offset for offset in range(self.octaves * 12))

    @property
    def latched_pitches(self) -> frozenset[int]:
        return frozenset(self._latches)

    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def drain_events(self) -> tuple[Event, ...]:
        result = tuple(self._events)
        self._events.clear()
        return result

    def _emit(self, event: Event) -> None:
        self._events.append(event)
        if self.on_event is not None:
            self.on_event(event)

    def key_bounds(self, pitch: int) -> Rect:
        """Return the visible half-open rectangle, with black keys above whites."""
        if isinstance(pitch, bool) or not isinstance(pitch, int) or pitch not in self.pitches:
            raise ValueError("pitch is outside the visible piano range")
        offset = pitch - self._base_pitch
        octave, pitch_class = divmod(offset, 12)
        if pitch_class in _WHITE:
            index = octave * 7 + _WHITE[pitch_class]
            return Rect(self.bounds.x + index * 3, self.bounds.y, 3, self.bounds.height)
        natural_index = octave * 7 + _BLACK[pitch_class]
        return Rect(self.bounds.x + natural_index * 3 + 2, self.bounds.y, 2, self.black_height)

    def pitch_at(self, x: int, y: int) -> int | None:
        """Map the exact visible cell to the key drawn at that cell."""
        if not self.bounds.contains(x, y):
            return None
        for pitch in reversed(self.pitches):
            if pitch % 12 in _BLACK:
                if self.key_bounds(pitch).contains(x, y):
                    return pitch
        white_index = (x - self.bounds.x) // 3
        if not 0 <= white_index < self.octaves * 7:
            return None
        octave, natural_index = divmod(white_index, 7)
        pitch_class = next(key for key, index in _WHITE.items() if index == natural_index)
        pitch = self._base_pitch + octave * 12 + pitch_class
        return pitch if self.bounds.y <= y < self.bounds.bottom else None

    def set_sounding(self, pitches: Iterable[int]) -> None:
        selected: set[int] = set()
        for pitch in pitches:
            if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127:
                raise ValueError("sounding pitches must be integer MIDI notes in the range 0..127")
            selected.add(pitch)
        self._external_sounding = selected

    def _active_pitches(self) -> set[int]:
        active = set(self._latched_notes)
        if self._mouse_note is not None:
            active.add(self._mouse_note[1])
        if self._twin_note is not None:
            active.add(self._twin_note[1])
        return active | self._external_sounding

    @staticmethod
    def _velocity(y: int, bounds: Rect) -> float:
        depth = max(0, min(bounds.height - 1, y - bounds.y))
        return 0.35 if bounds.height == 1 else 0.35 + 0.65 * depth / (bounds.height - 1)

    def _start(self, pitch: int, velocity: float, source: str) -> int:
        note_id = self._note_ids.next()
        self._emit(NoteOn(note_id, pitch, velocity, source))
        return note_id

    def _release(self, note_id: int) -> None:
        self._emit(NoteOff(note_id))

    def _toggle_latched(self, pitch: int, velocity: float) -> None:
        note_id = self._latched_notes.pop(pitch, None)
        if note_id is not None:
            self._release(note_id)
        else:
            self._latched_notes[pitch] = self._start(pitch, velocity, "onscreen")

    def _enter_mouse_pitch(self, pitch: int | None, x: int, y: int) -> None:
        if pitch == self._mouse_last_pitch:
            return
        velocity = self._velocity(y, self.key_bounds(pitch).intersect(self.bounds)) if pitch is not None else 0.7
        if self._mouse_note is not None:
            note_id, old_pitch, old_velocity = self._mouse_note
            if pitch is not None and pitch not in self._latches and self.legato_glide:
                self._emit(RetargetNote(note_id, pitch))
                self._mouse_note = (note_id, pitch, old_velocity)
                self._mouse_last_pitch = pitch
                return
            self._release(note_id)
            self._mouse_note = None
        if pitch is not None:
            if pitch in self._latches:
                if pitch != self._mouse_last_pitch:
                    self._toggle_latched(pitch, velocity)
            else:
                self._mouse_note = (self._start(pitch, velocity, "onscreen"), pitch, velocity)
        self._mouse_last_pitch = pitch

    def handle_mouse(self, event: MouseInput) -> bool:
        pitch = self.pitch_at(event.x, event.y)
        if event.kind == "wheel_up":
            self._set_octave(self._octave + event.steps)
            return True
        if event.kind == "wheel_down":
            self._set_octave(self._octave - event.steps)
            return True
        if event.kind == "right":
            if pitch is None:
                return False
            if pitch in self._latches:
                self._latches.remove(pitch)
                note_id = self._latched_notes.pop(pitch, None)
                if note_id is not None:
                    self._release(note_id)
            else:
                self._latches.add(pitch)
            return True
        if event.kind == "down" and event.button == "left":
            if pitch is None:
                return False
            self._mouse_down = True
            self._mouse_last_pitch = None
            self._enter_mouse_pitch(pitch, event.x, event.y)
            return True
        if event.kind == "move" and self._mouse_down:
            self._enter_mouse_pitch(pitch, event.x, event.y)
            return True
        if event.kind == "up" and self._mouse_down:
            if pitch != self._mouse_last_pitch:
                self._enter_mouse_pitch(pitch, event.x, event.y)
            if self._mouse_note is not None:
                self._release(self._mouse_note[0])
                self._mouse_note = None
            self._mouse_down = False
            self._mouse_last_pitch = None
            return True
        return False

    def _set_octave(self, octave: int) -> bool:
        bounded = max(-3, min(3, octave))
        if self.start_note + 12 * bounded + self.octaves * 12 - 1 > 127:
            bounded = (127 - (self.start_note + self.octaves * 12 - 1)) // 12
        if self.start_note + 12 * bounded < 0:
            bounded = -self.start_note // 12
        changed = bounded != self._octave
        self._octave = bounded
        return changed

    def handle_key(self, key: str, data: str = "") -> bool:
        if key == "left":
            self._cursor = max(0, self._cursor - 1)
            return True
        if key == "right":
            self._cursor = min(self.octaves * 12 - 1, self._cursor + 1)
            return True
        if key == "up":
            self._set_octave(self._octave + 1)
            return True
        if key == "down":
            self._set_octave(self._octave - 1)
            return True
        if key in {"enter", "space"}:
            now = time.monotonic()
            if self._twin_note is None:
                note_id = self._start(self.cursor_pitch, 0.7, "onscreen-keyboard")
                self._twin_note = (note_id, self.cursor_pitch, 0.7)
            self._twin_deadline = now + self.gate_ms / 1_000.0
            return True
        return False

    def tick(self, now: float | None = None) -> bool:
        if now is None:
            timestamp = time.monotonic()
        elif isinstance(now, bool) or not isinstance(now, Real) or not math.isfinite(float(now)):
            raise ValueError("now must be a finite time in seconds")
        else:
            timestamp = float(now)
        if self._twin_note is None or self._twin_deadline is None or self._twin_deadline > timestamp:
            return False
        self._release(self._twin_note[0])
        self._twin_note = None
        self._twin_deadline = None
        return True

    def release_all(self) -> None:
        ids = [note_id for note_id in self._latched_notes.values()]
        if self._mouse_note is not None:
            ids.append(self._mouse_note[0])
        if self._twin_note is not None:
            ids.append(self._twin_note[0])
        for note_id in dict.fromkeys(ids):
            self._release(note_id)
        self._latched_notes.clear()
        self._mouse_note = None
        self._twin_note = None
        self._twin_deadline = None
        self._mouse_down = False
        self._mouse_last_pitch = None

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        active = self._active_pitches()
        cursor_pitch = self.cursor_pitch
        for pitch in self.pitches:
            if pitch % 12 not in _WHITE:
                continue
            rect = self.key_bounds(pitch)
            role = "pressed" if pitch in active else "selected" if focused and pitch == cursor_pitch else "text"
            canvas.hit(rect.x, rect.y, rect.width, rect.height, self.tag, pitch)
            canvas.fill(rect.x, rect.y, rect.width, rect.height, " ", role)
            canvas.box(rect.x, rect.y, rect.width, rect.height, style="ascii" if canvas.ascii_only else "square", role=role)
            name = f"{_NAMES[pitch % 12]}{pitch // 12 - 1}"
            canvas.text(rect.x, rect.bottom - 2, name, "pressed" if pitch in active else "muted", max_width=rect.width - 1)
        for pitch in self.pitches:
            if pitch % 12 not in _BLACK:
                continue
            rect = self.key_bounds(pitch)
            role = "pressed" if pitch in active else "selected" if focused and pitch == cursor_pitch else "accent"
            char = "#" if canvas.ascii_only else "█"
            canvas.hit(rect.x, rect.y, rect.width, rect.height, self.tag, pitch)
            canvas.fill(rect.x, rect.y, rect.width, rect.height, char, role)
        if focused and self.bounds.y > 0:
            canvas.text(self.bounds.x, self.bounds.y - 1, "Piano  ←/→ key  ↑/↓ octave  Enter play  right-click latch  wheel octave", "muted", max_width=self.bounds.width)


__all__ = ["PianoWidget"]
