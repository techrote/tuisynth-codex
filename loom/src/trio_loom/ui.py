"""LOOM's animated string surface and compact, single-screen instrument UI."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from trio_kit.events import Event, InstrumentEvent, NoteOff, NoteOn, Panic, ParamSet, RetargetNote
from trio_kit.params import ParamSpec
from trio_kit.shell import InstrumentSpec, Shell
from trio_kit.tui import Canvas, ModulationWidget, Rect, SequencerWidget
from trio_kit.tui.mouse import MouseInput
from trio_kit.tui.widgets import ParamWidget, Widget
from trio_loom.strum import DEFAULT_TUNING, StrumModel


SCREEN_NAMES = ("strings", "panels", "sympathy", "library")
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("EXCITE", ("exc.mode", "exc.hardness", "exc.pressure", "exc.speed", "exc.noise")),
    ("STRING", ("str.decay", "str.release", "str.bright", "str.pickpos")),
    ("BODY", ("body.type", "body.mix", "body.size")),
    ("SYMPATHY", ("sym.mix", "sym.couple", "sym.decay", "sym.tuning", "sym.scale", "sym.root")),
    ("PLAY", ("play.mode", "strum.strings", "strum.spread")),
)
_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_SHORT_LABELS = {
    "exc.mode": "mode", "exc.hardness": "hard", "exc.pressure": "press", "exc.speed": "speed",
    "exc.noise": "rosin", "str.decay": "decay", "str.release": "release", "str.bright": "bright",
    "str.pickpos": "pick", "body.type": "type", "body.mix": "mix", "body.size": "size",
    "sym.mix": "mix", "sym.couple": "couple", "sym.decay": "decay", "sym.tuning": "tuning",
    "sym.scale": "scale", "sym.root": "root", "play.mode": "mode", "strum.strings": "strings",
    "strum.spread": "spread", "fx.reverb.size": "room", "fx.reverb.damp": "damp",
    "fx.reverb.mix": "reverb", "master.level": "level", "master.drive": "drive",
}


def _note_name(pitch: float) -> str:
    value = int(round(float(pitch)))
    return f"{_NOTE_NAMES[value % 12]}{value // 12 - 1}"


def chord_label(pitches: Iterable[float]) -> str:
    """Name common triads and otherwise show the held pitches compactly."""
    notes = sorted({int(round(float(pitch))) for pitch in pitches if math.isfinite(float(pitch)) and 0 <= pitch <= 127})
    if not notes:
        return "default E2 A2 D3 G3 B3 E4 A4 D5"
    pcs = sorted({pitch % 12 for pitch in notes})
    root = notes[0] % 12
    intervals = tuple(sorted((pitch - root) % 12 for pitch in pcs))
    quality = {
        (0, 4, 7): "major", (0, 3, 7): "minor", (0, 3, 6): "diminished",
        (0, 4, 8): "augmented", (0, 2, 7): "sus2", (0, 5, 7): "sus4",
    }.get(intervals)
    names = " ".join(_NOTE_NAMES[pitch % 12] for pitch in notes[:5])
    return f"{_NOTE_NAMES[root]} {quality} ({names})" if quality else names


def _choice_label(spec: ParamSpec, value: int | float) -> str:
    if spec.kind == "choice" and spec.choices:
        index = min(len(spec.choices) - 1, max(0, int(value)))
        return spec.choices[index]
    if spec.key == "sym.root":
        return _NOTE_NAMES[int(value) % 12]
    if spec.key == "strum.strings":
        return str(int(value))
    numeric = float(value)
    if spec.key.endswith(".decay") or spec.key.endswith(".release"):
        return f"{numeric:.1f}s"
    if spec.key.endswith(".spread"):
        return f"{numeric:.0f}ms"
    if spec.key.endswith(".size") and spec.group == "Body":
        return f"{numeric:.2f}"
    return f"{numeric:.2f}"


class LoomParamWidget(ParamWidget):
    """Single-row parameter control suited to LOOM's docked panels."""

    def handle_key(self, key: str, data: str = "") -> bool:
        if self.spec.kind == "choice" and key in {"left", "down", "right", "up", "enter"}:
            count = len(self.spec.choices or ())
            step = -1 if key in {"left", "down"} else 1
            return self.set_value((int(self.value) + step) % count)
        return super().handle_key(key, data)

    def handle_mouse(self, event: MouseInput) -> bool:
        if self.spec.kind == "choice":
            if event.kind == "right":
                return self.reset()
            if event.kind in {"wheel_up", "wheel_down"}:
                delta = event.steps if event.kind == "wheel_up" else -event.steps
                return self.set_value((int(self.value) + delta) % len(self.spec.choices or ()))
            if event.kind == "down" and event.button == "left":
                return self.set_value((int(self.value) + 1) % len(self.spec.choices or ()))
            return False
        return super().handle_mouse(event)

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width = self.bounds.x, self.bounds.y, self.bounds.width
        label = _SHORT_LABELS.get(self.spec.key, self.label.casefold())
        role = "focused" if focused else "hover" if hovered else "heading"
        value = _choice_label(self.spec, self.value)
        if self.spec.kind in {"choice", "discrete"}:
            text = f"{label} <{value}>"
            canvas.text(x, y, text, "focused" if focused else "selected", max_width=width)
            return
        label_width = min(max(3, len(label)), max(3, width // 3))
        value_width = min(len(value), max(3, width // 3))
        track_width = max(1, width - label_width - value_width - 2)
        canvas.text(x, y, label, role, max_width=label_width)
        track_x = x + label_width + 1
        position = round(self.unit * max(0, track_width - 1))
        canvas.text(track_x, y, "-" * track_width, "muted", max_width=track_width)
        canvas.put(track_x + position, y, "#", "focused" if focused else "accent")
        canvas.text(track_x + track_width + 1, y, value, "selected", max_width=value_width)


class LoomPanelGroup(Widget):
    """Compact panel that exposes every group parameter through one cycling row."""

    def __init__(self, tag: str, bounds: Rect, title: str, specs: tuple[ParamSpec, ...], shell: Shell) -> None:
        super().__init__(tag, bounds, label=title)
        self.title = title
        self.specs = specs
        self.shell = shell
        self.selected = 0

    @property
    def current(self) -> ParamSpec:
        return self.specs[self.selected]

    def _adjust(self, steps: int) -> bool:
        spec = self.current
        value = self.shell._known_params[spec.key]
        if spec.kind == "choice":
            target = (int(value) + steps) % len(spec.choices or ())
        elif spec.kind == "discrete":
            target = min(int(spec.maximum), max(int(spec.minimum), int(value) + steps))
        else:
            target = spec.from_unit(min(1.0, max(0.0, spec.to_unit(value) + steps / 100.0)))
        return self.shell.set_param(spec.key, target)

    def handle_key(self, key: str, data: str = "") -> bool:
        del data
        if key in {"left", "right"}:
            self.selected = (self.selected + (-1 if key == "left" else 1)) % len(self.specs)
            return True
        if key in {"up", "pageup"}:
            return self._adjust(10 if key == "pageup" else 1)
        if key in {"down", "pagedown"}:
            return self._adjust(-10 if key == "pagedown" else -1)
        if key == "home":
            return self.shell.set_param(self.current.key, self.current.minimum)
        if key == "end":
            return self.shell.set_param(self.current.key, self.current.maximum)
        if key == "delete":
            return self.shell.set_param(self.current.key, self.current.default)
        if key in {"enter", "space"}:
            self.selected = (self.selected + 1) % len(self.specs)
            return True
        return False

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "wheel_up":
            return self._adjust(event.steps)
        if event.kind == "wheel_down":
            return self._adjust(-event.steps)
        if event.kind == "right":
            return self.shell.set_param(self.current.key, self.current.default)
        if event.kind == "down" and event.button == "left":
            self.selected = (self.selected + 1) % len(self.specs)
            return True
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        canvas.box(x, y, width, height, role="border")
        canvas.text(x + 1, y, self.title, "focused" if focused else "heading", max_width=width - 2)
        value = self.shell._known_params[self.current.key]
        label = _SHORT_LABELS.get(self.current.key, self.current.label.casefold())
        content = f"{label} {_choice_label(self.current, value)}"
        canvas.text(x + 1, y + 1, content, "selected" if focused else "text", max_width=width - 2)


@dataclass(slots=True)
class _View:
    shell: Shell
    width: int = 100
    height: int = 30
    surface: StringSurface | None = None
    sympathy: SympatheticColumn | None = None
    sequencer: SequencerWidget | None = None
    modulation: ModulationWidget | None = None
    sequencer_visible: bool = False
    modulation_visible: bool = False
    held: dict[int, float] = field(default_factory=dict)
    direct_ids: set[int] = field(default_factory=set)
    arp_ids: set[int] = field(default_factory=set)
    held_lock: threading.RLock = field(default_factory=threading.RLock)

    def held_pitches(self) -> tuple[float, ...]:
        with self.held_lock:
            return tuple(sorted(self.held.values()))[:12]


class StringSurface(Widget):
    """Captured, cell-safe string surface driven by LOOM engine telemetry."""

    def __init__(self, view: _View, bounds: Rect, *, clock=time.monotonic) -> None:
        super().__init__("loom-strings", bounds, label="LOOM strings")
        self.view = view
        self.clock = clock
        self.selected = 0
        self._gesture: str | None = None
        self._last_row: int | None = None
        self._last_index: int | None = None
        self._last_time: float | None = None
        self._bow_active: list[int] = []

    def _count(self) -> int:
        return int(self.view.shell._known_params.get("strum.strings", 8))

    def _model(self) -> StrumModel:
        return StrumModel(self._count())

    def _pitches(self) -> tuple[int, ...]:
        shell = self.view.shell
        mode = "chord" if int(shell._known_params.get("play.mode", 0)) else "direct"
        return self._model().pitches(mode, self.view.held_pitches())

    def _surface_rows(self) -> int:
        return min(max(1, self.bounds.height - 2), self._count())

    def _row_top(self) -> int:
        capacity = max(1, self.bounds.height - 2)
        return self.bounds.y + 1 + max(0, (capacity - self._surface_rows()) // 2)

    def _index_at(self, y: int) -> int:
        rows = self._surface_rows()
        row = min(rows - 1, max(0, y - self._row_top()))
        if rows == 1:
            return self._count() - 1
        return int(round((rows - 1 - row) * (self._count() - 1) / (rows - 1)))

    def _excitation_is_bow(self) -> bool:
        return int(self.view.shell._known_params.get("exc.mode", 0)) == 1

    def _send_index(self, index: int, velocity: float, *, bow: bool) -> None:
        pitches = self._pitches()
        if not pitches:
            return
        bounded = min(len(pitches) - 1, max(0, index))
        name = "bow_on" if bow else "pluck"
        self.view.shell._push(InstrumentEvent(name, (float(pitches[bounded]), float(velocity), bounded)))

    def _cross_to(self, index: int, row: int, when: float) -> bool:
        if self._last_index is None:
            indices = (index,)
            speed = 20.0
        else:
            step = 1 if index > self._last_index else -1
            indices = tuple(range(self._last_index + step, index + step, step)) if index != self._last_index else ()
            elapsed = max(0.001, when - (self._last_time if self._last_time is not None else when))
            row_distance = max(1, abs(row - (self._last_row if self._last_row is not None else row)))
            speed = row_distance / elapsed
        if not indices:
            self._last_row, self._last_index, self._last_time = row, index, when
            return False
        velocity = self._model().crossing_velocity(speed)
        # A captured gesture must keep the excitation mode it started with. The
        # user can still edit parameters through a second input source while the
        # mouse is held; switching the mode mid-capture must not create an
        # unpaired sustained bow or turn a bow gesture into one-shot plucks.
        bow = self._gesture == "bow" if self._gesture is not None else self._excitation_is_bow()
        for string_index in indices:
            self.selected = string_index
            if bow:
                if string_index not in self._bow_active:
                    self._send_index(string_index, velocity, bow=True)
                    self._bow_active.append(string_index)
            else:
                self._send_index(string_index, velocity, bow=False)
        self._last_row, self._last_index, self._last_time = row, index, when
        return True

    def _start_gesture(self, y: int) -> None:
        self._gesture = "bow" if self._excitation_is_bow() else "pluck"
        self._last_row = None
        self._last_index = None
        self._last_time = None
        self._bow_active.clear()
        when = float(self.clock())
        self._cross_to(self._index_at(y), y, when)

    def _finish_gesture(self) -> None:
        if self._gesture == "bow":
            for index in self._bow_active:
                self.view.shell._push(InstrumentEvent("bow_off", (index,)))
        self._gesture = None
        self._last_row = None
        self._last_index = None
        self._last_time = None
        self._bow_active.clear()

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            index = self._index_at(event.y)
            self.selected = index
            self.view.shell._push(InstrumentEvent("mute", (index,)))
            return True
        if event.kind == "down" and event.button == "left":
            self._start_gesture(event.y)
            return True
        if event.kind == "move" and self._gesture is not None:
            self._cross_to(self._index_at(event.y), event.y, float(self.clock()))
            return True
        if event.kind == "up" and self._gesture is not None:
            self._finish_gesture()
            return True
        return False

    def _trigger_selected(self, velocity: float = 0.7) -> bool:
        if self._excitation_is_bow():
            self._send_index(self.selected, velocity, bow=True)
            self.view.shell._push(InstrumentEvent("bow_off", (self.selected,)))
        else:
            self._send_index(self.selected, velocity, bow=False)
        return True

    def handle_key(self, key: str, data: str = "") -> bool:
        typed = data if key == "any" else key
        if key == "up":
            self.selected = min(self._count() - 1, self.selected + 1)
            return True
        if key == "down":
            self.selected = max(0, self.selected - 1)
            return True
        if key == "left":
            self.selected = max(0, self.selected - 1)
            return True
        if key == "right":
            self.selected = min(self._count() - 1, self.selected + 1)
            return True
        if key in {"enter", "space"}:
            return self._trigger_selected()
        if typed in {",", "."}:
            direction = 1 if typed == "," else -1
            self.view.shell._push(InstrumentEvent("strum", (direction, 20.0, *self.view.held_pitches())))
            return True
        if typed == "/":
            current = int(self.view.shell._known_params.get("play.mode", 0))
            self.view.shell.set_param("play.mode", 0 if current else 1)
            return True
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        shell = self.view.shell
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        canvas.box(x, y, width, height, role="border")
        mode = "CHORD" if int(shell._known_params.get("play.mode", 0)) else "DIRECT"
        excite = "BOW" if self._excitation_is_bow() else "PLUCK"
        canvas.text(x + 1, y, f"STRINGS · {mode}/{excite} · drag to play · right mute", "focused" if focused else "heading", max_width=width - 2)
        pitches = self._pitches()
        telemetry = shell.engine.telemetry().instrument
        levels = telemetry.get("string_levels", ())
        phases = telemetry.get("string_phases", ())
        bow_strings = set(telemetry.get("bow_strings", ()))
        skin = shell.skins.current
        glyphs = skin.glyphs.get("string", ("─", "·", "~", "≈", "∿"))
        if isinstance(glyphs, str):
            glyphs = tuple(glyphs)
        if canvas.ascii_only:
            glyphs = ("-", ".", ":", "=", "~")
        glyphs = tuple(glyphs) if isinstance(glyphs, (tuple, list)) else ("-", ".", "~", "=")
        ramp = skin.ramp("string")
        rows = self._surface_rows()
        line_start = x + 5
        line_width = max(1, width - 7)
        count = self._count()
        for row in range(rows):
            line_y = self._row_top() + row
            physical = self._index_at(line_y)
            pitch = pitches[min(physical, len(pitches) - 1)] if pitches else DEFAULT_TUNING[min(physical, len(DEFAULT_TUNING) - 1)]
            level = float(levels[physical]) if physical < len(levels) else 0.0
            phase = float(phases[physical]) if physical < len(phases) else physical * 0.137
            energy = min(1.0, max(0.0, level * 120.0))
            active = physical == self.selected and focused
            role = "focused" if active else "text"
            canvas.text(x + 1, line_y, _note_name(pitch), role, max_width=4)
            for cell in range(line_width):
                standing = math.sin(math.pi * (cell + 1) / (line_width + 1))
                displacement = abs(math.sin(phase * 2.0 * math.pi + cell * 0.45)) * standing * energy
                glyph_index = min(len(glyphs) - 1, int(round(displacement * (len(glyphs) - 1))))
                char = glyphs[glyph_index] if energy > 0.02 else ("-" if canvas.ascii_only else "─")
                color_index = min(4, max(0, len(ramp) - 1), int(displacement * max(1, len(ramp))))
                color_role = f"string_{color_index}" if ramp and f"string_{color_index}" in skin.styles else "accent"
                canvas.put(line_start + cell, line_y, char, color_role)
            if physical in bow_strings and line_width > 3:
                canvas.put(line_start + max(1, line_width // 3), line_y, "|" if canvas.ascii_only else "╫", "selected")
            if physical == self.selected:
                canvas.put(x + width - 2, line_y, ">", "focused" if focused else "accent")
        canvas.text(x + 1, y + height - 1, f"{count} tuned strings · arrows select · Enter pluck/bow · , . strum · / play mode", "muted", max_width=width - 2)


class SympatheticColumn(Widget):
    """Twelve one-way resonators rendered as two animated six-string columns."""

    def __init__(self, view: _View, bounds: Rect) -> None:
        super().__init__("loom-sympathy", bounds, label="Sympathetic resonators")
        self.view = view
        self.selected = 0

    def handle_key(self, key: str, data: str = "") -> bool:
        del data
        if key in {"up", "left"}:
            self.selected = (self.selected - 1) % 12
            return True
        if key in {"down", "right"}:
            self.selected = (self.selected + 1) % 12
            return True
        if key in {"enter", "space"}:
            telemetry = self.view.shell.engine.telemetry().instrument
            pitches = telemetry.get("sympathetic_pitches", ())
            if self.selected < len(pitches):
                self.view.shell.set_param("sym.root", int(round(float(pitches[self.selected]))) % 12)
            return True
        return False

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "down" and event.button == "left":
            row = min(5, max(0, event.y - self.bounds.y - 1))
            column = 1 if event.x >= self.bounds.x + self.bounds.width // 2 else 0
            self.selected = column * 6 + row
            self.handle_key("enter")
            return True
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        canvas.box(x, y, width, height, role="border")
        canvas.text(x + 1, y, "SYMPATHETIC · 12 resonators", "focused" if focused else "heading", max_width=width - 2)
        telemetry = self.view.shell.engine.telemetry().instrument
        pitches = telemetry.get("sympathetic_pitches", (0.0,) * 12)
        levels = telemetry.get("sympathetic_levels", (0.0,) * 12)
        skin = self.view.shell.skins.current
        glyphs = skin.glyphs.get("string", ("─", "·", "~", "≈", "∿"))
        ramp = skin.ramp("string")
        if isinstance(glyphs, str):
            glyphs = tuple(glyphs)
        if canvas.ascii_only:
            glyphs = ("-", ".", ":", "=", "~")
        glyphs = tuple(glyphs) if isinstance(glyphs, (tuple, list)) else ("-", ".", "~", "=")
        col_width = max(1, (width - 2) // 2)
        for index in range(12):
            col = index // 6
            row = index % 6
            px = x + 1 + col * col_width
            py = y + 1 + row
            pitch = float(pitches[index]) if index < len(pitches) else 60.0 + index
            energy = min(1.0, max(0.0, float(levels[index]) * 80.0)) if index < len(levels) else 0.0
            label = _note_name(pitch)
            role = "focused" if focused and index == self.selected else "text"
            canvas.text(px, py, label, role, max_width=4)
            bar_width = max(1, col_width - 6)
            fill = round(energy * bar_width)
            glyph = glyphs[min(len(glyphs) - 1, round(energy * (len(glyphs) - 1)))]
            color_index = min(4, max(0, len(ramp) - 1), int(energy * max(1, len(ramp))))
            if energy <= 0.05:
                role = "muted"
            elif ramp and f"string_{color_index}" in skin.styles:
                role = f"string_{color_index}"
            else:
                role = "accent"
            canvas.text(px + 5, py, glyph * fill + ("-" if canvas.ascii_only else "─") * (bar_width - fill), role, max_width=bar_width)
        canvas.text(x + 1, y + height - 1, "F4 focus · Enter sets root", "muted", max_width=width - 2)


class LoomUI:
    """Per-shell view state and shared-shell adapters for the LOOM instrument."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self.clock = clock
        self._views: WeakKeyDictionary[Shell, _View] = WeakKeyDictionary()
        self._lock = threading.RLock()

    def view(self, shell: Shell) -> _View:
        with self._lock:
            view = self._views.get(shell)
            if view is None:
                view = _View(shell)
                self._views[shell] = view
            return view

    def widgets(self, shell: Shell, width: int, height: int) -> tuple[Widget, ...]:
        view = self.view(shell)
        view.width, view.height = width, height
        compact = width < 100 or height < 30
        if compact:
            surface_bounds = Rect(2, 3, width - 32, 10)
            sympathy_bounds = Rect(width - 29, 3, 27, 10)
        else:
            surface_bounds = Rect(2, 3, width - 35, 10)
            sympathy_bounds = Rect(width - 31, 3, 29, 10)
        view.surface = StringSurface(view, surface_bounds, clock=self.clock)
        view.sympathy = SympatheticColumn(view, sympathy_bounds)
        seq_y = 13
        seq_height = max(4, min(9, height - (3 if compact else 4) - seq_y - 1))
        view.sequencer = SequencerWidget(shell, Rect(2, seq_y, width - 4, seq_height), "thread")
        view.sequencer.visible = view.sequencer_visible
        view.modulation = ModulationWidget(shell, Rect(2, 3, width - 4, max(10, height - 3)), "thread")
        view.modulation.visible = view.modulation_visible
        result: list[Widget] = [view.surface, view.sympathy, view.sequencer, view.modulation]
        if compact:
            panel_y = 13
            widths = [(width - 4) // 5] * 5
            widths[-1] += width - 4 - sum(widths)
            x = 2
            for (title, keys), panel_width in zip(_GROUPS, widths):
                specs = tuple(shell.registry[key] for key in keys if key in shell.registry.specs)
                result.append(LoomPanelGroup(f"loom-panel-{title.casefold()}", Rect(x, panel_y, panel_width, 4), title, specs, shell))
                x += panel_width
        else:
            panel_y = 13
            panel_height = 9
            widths = [max(16, (width - 4) // 5)] * 5
            widths[-1] += width - 4 - sum(widths)
            x = 2
            for (title, keys), panel_width in zip(_GROUPS, widths):
                panel = Rect(x, panel_y, panel_width, panel_height)
                specs = tuple(shell.registry[key] for key in keys if key in shell.registry.specs)
                for row, spec in enumerate(specs[: panel_height - 2]):
                    result.append(
                        LoomParamWidget(
                            f"loom-param-{spec.key.replace('.', '-')}",
                            Rect(x + 1, panel_y + 1 + row, panel_width - 2, 1),
                            spec,
                            shell._known_params[spec.key],
                            label=_SHORT_LABELS.get(spec.key, spec.label.casefold()),
                            on_change=shell.set_param,
                        )
                    )
                x += panel_width
        if view.sequencer_visible:
            for widget in result:
                if widget is not view.sequencer:
                    widget.visible = False
        if view.modulation_visible:
            for widget in result:
                if widget is not view.modulation:
                    widget.visible = False
        return tuple(result)

    def draw(self, canvas: Canvas, shell: Shell) -> None:
        view = self.view(shell)
        if view.modulation_visible:
            canvas.text(2, 2, "LOOM MOD · thread patch cords and ordered post-tone pedals", "muted", max_width=canvas.width - 4)
            return
        compact = canvas.width < 100 or canvas.height < 30
        if compact:
            panel_y, panel_h = 13, 4
            widths = [(canvas.width - 4) // 5] * 5
            widths[-1] += canvas.width - 4 - sum(widths)
        else:
            panel_y, panel_h = 13, 9
            widths = [max(16, (canvas.width - 4) // 5)] * 5
            widths[-1] += canvas.width - 4 - sum(widths)
        x = 2
        for (title, _keys), panel_width in zip(_GROUPS, widths):
            if not compact:
                canvas.box(x, panel_y, panel_width, panel_h, role="border")
                canvas.text(x + 1, panel_y, title, "heading", max_width=panel_width - 2)
            x += panel_width

        piano_height = 3 if compact else 4
        piano_y = max(4, canvas.height - piano_height - 3)
        mode = "CHORD" if int(shell._known_params.get("play.mode", 0)) else "DIRECT"
        held = view.held_pitches()
        label = chord_label(held) if mode == "CHORD" else chord_label(())
        suffix = "keyboard tunes strings" if mode == "CHORD" else "piano plays notes"
        canvas.text(2, piano_y - 1, f"PIANO · {mode} · {label} · {suffix}", "accent", max_width=canvas.width - 4)

    def on_screen(self, screen: str, shell: Shell) -> None:
        view = self.view(shell)
        if screen == "mod-return":
            view.modulation_visible = False
            previous = shell._screen_before_modulation
            target = previous if previous in {"f2", "f3", "f4", "f5"} else "f2"
            shell.current_screen = target
            self.on_screen(target, shell)
            return
        if screen in {"s-f4", "shift-f4"}:
            view.modulation_visible = True
            view.sequencer_visible = False
            if view.modulation is not None:
                view.modulation.visible = True
                shell.widgets.focus(view.modulation.tag)
            for widget in shell.widgets.widgets:
                widget.visible = widget is view.modulation
            shell.invalidate()
            return
        if screen == "seq-return":
            view.modulation_visible = False
            view.sequencer_visible = False
            if view.sequencer is not None:
                view.sequencer.visible = False
            previous = shell._screen_before_sequencer
            target = previous if previous in {"f2", "f3", "f4", "f5"} else "f3"
            shell.current_screen = target
            self.on_screen(target, shell)
            return
        if screen in {"s-f3", "shift-f3"}:
            view.modulation_visible = False
            view.sequencer_visible = True
            if view.sequencer is not None:
                view.sequencer.visible = True
                shell.widgets.focus(view.sequencer.tag)
            shell.invalidate()
            return
        view.sequencer_visible = False
        view.modulation_visible = False
        if view.sequencer is not None:
            view.sequencer.visible = False
        if view.modulation is not None:
            view.modulation.visible = False
        for widget in shell.widgets.widgets:
            if widget.tag.startswith("loom-"):
                widget.visible = True
        if screen == "f2" and view.surface is not None:
            shell.widgets.focus(view.surface.tag)
        elif screen == "f3":
            panel = next((widget for widget in shell.widgets.widgets if widget.tag.startswith("loom-panel-") or widget.tag.startswith("loom-param-")), None)
            if panel is not None:
                shell.widgets.focus(panel.tag)
        elif screen == "f4" and view.sympathy is not None:
            shell.widgets.focus(view.sympathy.tag)
        elif screen == "f5":
            shell.open_overlay("presets")
        shell.invalidate()

    def header(self, shell: Shell) -> str:
        telemetry = shell.engine.telemetry()
        logo = " ".join(shell.skins.current.art.get("logo", ("LOOM",)))
        if self.view(shell).modulation_visible:
            return f"≋ L O O M ≋  MODULATION · {shell.engine_preset_name} · {shell.skins.current_id}"
        return f"≋ L O O M ≋  {logo} · {shell.engine_preset_name} · {shell.skins.current_id} · {shell.midi_status} · {telemetry.active_voices}/{telemetry.max_voices}"

    def footer(self, shell: Shell) -> str:
        if self.view(shell).modulation_visible:
            return "MOD · click route · wheel amount · drag pedals · R source · T target · +/- amount · B bypass · Del clear · Esc return"
        return "F2 strings · F3 panels · Shift+F3 sequencer · F4 sympathy · F5 presets · F6 skin · F9 · ^Q"

    def help_rows(self, shell: Shell) -> tuple[str, ...]:
        del shell
        return (
            "LOOM strings: left-drag crosses and plays rows in order; bow mode sustains until release",
            "LOOM right-click mutes a string; Up/Down select; Enter plays; comma/period strum",
            "Slash toggles direct/chord piano mode; in chord mode held keys tune strings only",
            "Shift+F3 sequencer: click knots, drag velocity, right-click chance; A arp, M mode, O octaves, R rate, L latch",
            "Compact panels: Left/Right choose a parameter; Up/Down adjust; right-click resets",
        )

    def route_event(self, event: Event, shell: Shell) -> tuple[Event, ...] | None:
        view = self.view(shell)
        if isinstance(event, NoteOn):
            with view.held_lock:
                view.held[event.note_id] = event.pitch
                held = tuple(sorted(view.held.values()))[:12]
                direct = int(shell._known_params.get("play.mode", 0)) == 0
                arp_settings = shell._known_extras.get("sequencer", {}).get("arpeggiator", {})
                arp = isinstance(arp_settings, Mapping) and bool(arp_settings.get("enabled", False))
                if direct:
                    view.direct_ids.add(event.note_id)
                elif arp:
                    view.arp_ids.add(event.note_id)
            routed: list[Event] = [InstrumentEvent("held", held)]
            if direct or arp:
                routed.append(event)
            return tuple(routed)
        if isinstance(event, NoteOff):
            with view.held_lock:
                view.held.pop(event.note_id, None)
                direct = event.note_id in view.direct_ids
                view.direct_ids.discard(event.note_id)
                arp = event.note_id in view.arp_ids
                view.arp_ids.discard(event.note_id)
                held = tuple(sorted(view.held.values()))[:12]
            routed = [InstrumentEvent("held", held)]
            if direct or arp:
                routed.append(event)
            return tuple(routed)
        if isinstance(event, RetargetNote):
            with view.held_lock:
                direct = event.note_id in view.direct_ids
                arp = event.note_id in view.arp_ids
                if event.note_id in view.held:
                    view.held[event.note_id] = event.pitch
                held = tuple(sorted(view.held.values()))[:12]
            return (InstrumentEvent("held", held), event) if direct or arp else (InstrumentEvent("held", held),)
        if isinstance(event, Panic):
            with view.held_lock:
                view.held.clear()
                view.direct_ids.clear()
                view.arp_ids.clear()
            return (InstrumentEvent("held", ()), event)
        if isinstance(event, ParamSet) and event.key == "play.mode":
            with view.held_lock:
                held = tuple(sorted(view.held.values()))[:12]
            return (InstrumentEvent("held", held), event)
        return (event,)

    def refresh_when(self, shell: Shell) -> bool:
        if shell.snapshot_mode:
            return False
        telemetry = shell.engine.telemetry().instrument
        return any(float(level) > 1e-5 for level in (*telemetry.get("string_levels", ()), *telemetry.get("sympathetic_levels", ())))


def loom_spec(*, clock=time.monotonic) -> InstrumentSpec:
    """Create LOOM's instrument shell specification without importing other instruments."""
    from pathlib import Path

    from trio_loom.instrument import LoomInstrument
    from trio_loom.params import loom_registry

    ui = LoomUI(clock=clock)
    root = Path(__file__).resolve().parent
    return InstrumentSpec(
        identifier="loom",
        name="LOOM",
        instrument_factory=LoomInstrument,
        registry=loom_registry(),
        factory_package="trio_loom",
        factory_presets_dir=root / "data" / "presets",
        factory_skins_dir=root / "data" / "skins",
        max_voices=8,
        draw=ui.draw,
        widgets=ui.widgets,
        on_screen=ui.on_screen,
        screen_names=SCREEN_NAMES,
        piano_octaves=2,
        piano_height=4,
        compact_piano_height=3,
        refresh_hz=24,
        refresh_when=ui.refresh_when,
        header=ui.header,
        footer=ui.footer,
        event_router=ui.route_event,
        help_rows=ui.help_rows,
    )


__all__ = ["LoomParamWidget", "LoomPanelGroup", "LoomUI", "SCREEN_NAMES", "StringSurface", "SympatheticColumn", "chord_label", "loom_spec"]
