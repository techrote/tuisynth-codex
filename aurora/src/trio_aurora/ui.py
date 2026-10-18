"""AURORA's tabbed terminal view, harmonic painter, and spectral waterfall."""

from __future__ import annotations

import math
import random
import time
from collections import deque
from collections.abc import Mapping, Sequence
from weakref import WeakKeyDictionary

from trio_kit.tui import Canvas, ModulationWidget, Rect, SequencerWidget
from trio_kit.tui.mouse import MouseInput
from trio_kit.tui.widgets import Choice, Fader, ListBox, Tabs, Widget

from trio_aurora.params import aurora_registry


SCREEN_NAMES = ("play", "shape", "space", "library")
_PLAY_KEYS = (
    "spec.count", "spec.bw", "flt.cut", "amp.r", "lfo.rate", "fx.reverb.mix",
    "master.level", "osc.octave", "osc.width",
)
_SHAPE_KEYS = (
    "spec.count", "spec.bw", "spec.bwscale", "spec.stretch", "spec.tilt", "spec.noise", "spec.seed",
    "amp.a", "amp.d", "amp.s", "amp.r", "amp.vel", "flt.mode", "flt.cut", "flt.res", "flt.env",
    "flt.key", "fenv.a", "fenv.d", "fenv.s", "fenv.r",
)
_SPACE_KEYS = (
    "lfo.rate", "lfo.depth", "lfo.wave", "lfo.tgt", "osc.octave", "osc.detune", "osc.width",
    "fx.chorus.mix", "fx.delay.time", "fx.delay.fb", "fx.delay.mix", "fx.reverb.size",
    "fx.reverb.damp", "fx.reverb.mix", "master.level", "master.drive",
)
_SHORT_LABELS = {
    "spec.count": "Partials", "spec.bw": "Bandwidth", "spec.bwscale": "BW scale",
    "spec.stretch": "Stretch", "spec.tilt": "Tilt", "spec.noise": "Noise",
    "spec.seed": "Phase seed", "osc.octave": "Octave", "osc.detune": "Detune",
    "osc.width": "Width", "amp.a": "Amp attack", "amp.d": "Amp decay",
    "amp.s": "Amp sustain", "amp.r": "Amp release", "amp.vel": "Velocity",
    "flt.mode": "Filter mode", "flt.cut": "Cutoff", "flt.res": "Resonance",
    "flt.env": "Filter env", "flt.key": "Key track", "fenv.a": "Filter attack",
    "fenv.d": "Filter decay", "fenv.s": "Filter sustain", "fenv.r": "Filter release",
    "lfo.rate": "LFO rate", "lfo.depth": "LFO depth", "lfo.wave": "LFO wave",
    "lfo.tgt": "LFO target", "fx.chorus.mix": "Chorus", "fx.delay.time": "Delay time",
    "fx.delay.fb": "Delay feedback", "fx.delay.mix": "Delay mix", "fx.reverb.size": "Room size",
    "fx.reverb.damp": "Damping", "fx.reverb.mix": "Reverb", "master.level": "Master",
    "master.drive": "Drive",
}
_COMPACT_LABELS = {
    "spec.count": "Parts", "spec.bw": "Band", "spec.bwscale": "BWscale",
    "spec.stretch": "Stretch", "spec.tilt": "Tilt", "spec.noise": "Noise",
    "spec.seed": "Phase", "amp.a": "A.attack", "amp.d": "A.decay",
    "amp.s": "A.sust", "amp.r": "A.rel", "amp.vel": "Velocity",
    "flt.cut": "Cutoff", "flt.res": "Reson", "flt.env": "F.env",
    "flt.key": "Keytrk", "fenv.a": "F.attack", "fenv.d": "F.decay",
    "fenv.s": "F.sust", "fenv.r": "F.rel",
}


def waterfall_column_levels(
    harmonics: Sequence[float],
    *,
    active_voices: int,
    voice_rms: float,
    columns: int,
    frozen: bool = False,
    envelope_level: float | None = None,
    lfo_level: float = 0.0,
) -> tuple[float, ...]:
    """Map the painted profile to logarithmic screen columns and voice energy."""
    if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1:
        raise ValueError("columns must be a positive integer")
    if isinstance(active_voices, bool) or not isinstance(active_voices, int) or active_voices < 0:
        raise ValueError("active_voices must be a non-negative integer")
    if isinstance(voice_rms, bool) or not isinstance(voice_rms, (int, float)) or not math.isfinite(float(voice_rms)):
        raise ValueError("voice_rms must be a finite number")
    values = tuple(float(value) for value in harmonics[:64])
    if not values:
        values = (0.0,)
    if envelope_level is not None and (not math.isfinite(float(envelope_level)) or envelope_level < 0.0):
        raise ValueError("envelope_level must be finite and non-negative")
    if isinstance(lfo_level, bool) or not isinstance(lfo_level, (int, float)) or not math.isfinite(float(lfo_level)):
        raise ValueError("lfo_level must be finite")
    if not frozen and (active_voices == 0 or voice_rms <= 1e-8):
        return (0.0,) * columns
    if frozen:
        level = 0.34
    elif envelope_level is None:
        level = max(0.0, min(1.0, float(voice_rms) * 6.0))
    else:
        level = max(0.0, min(1.0, float(envelope_level) / 8.0))
        level *= 0.75 + 0.25 * max(0.0, min(1.0, float(lfo_level)))
    highest = max(1, len(values) - 1)
    result: list[float] = []
    for column in range(columns):
        fraction = 0.0 if columns == 1 else column / (columns - 1)
        partial = (math.exp(fraction * math.log(highest + 1.0)) - 1.0) / highest
        position = min(len(values) - 1, max(0.0, partial * (len(values) - 1)))
        low = int(position)
        high = min(len(values) - 1, low + 1)
        weight = position - low
        profile = values[low] * (1.0 - weight) + values[high] * weight
        result.append(max(0.0, min(1.0, profile * level)))
    return tuple(result)


class HarmonicPainter(Widget):
    """64-bar harmonic profile with captured, interpolated mouse painting."""

    def __init__(
        self,
        bounds: Rect,
        harmonics: Sequence[float],
        on_change,
        *,
        visible_bars: int = 64,
    ) -> None:
        super().__init__("aurora-painter", bounds, label="Harmonic painter")
        if visible_bars not in {32, 64}:
            raise ValueError("visible_bars must be 32 or 64")
        if len(harmonics) != 64:
            raise ValueError("harmonics must contain 64 entries")
        self.harmonics = [max(0.0, min(1.0, float(value))) for value in harmonics]
        self.on_change = on_change
        self.visible_bars = visible_bars
        self.density: tuple[str, ...] = (" ", ".", ":", "-", "=", "+", "*", "#", "%", "@")
        self.selected = 0
        self._drag_mode: str | None = None
        self._last_point: tuple[int, float] | None = None
        self._random_round = 0

    @property
    def bar_count(self) -> int:
        return self.visible_bars

    def index_at(self, x: int) -> int:
        relative = min(self.bounds.width - 1, max(0, x - self.bounds.x))
        return min(self.visible_bars - 1, relative * self.visible_bars // max(1, self.bounds.width))

    def value_at(self, y: int) -> float:
        top = self.bounds.y + 1
        bottom = self.bounds.bottom - 2
        if bottom <= top:
            return 1.0 if y <= top else 0.0
        return max(0.0, min(1.0, 1.0 - (y - top) / (bottom - top)))

    def cell_for_index(self, index: int, *, height: float = 0.0) -> tuple[int, int]:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < self.visible_bars:
            raise ValueError("harmonic index is outside the visible painter")
        x = self.bounds.x + round(index * (self.bounds.width - 1) / max(1, self.visible_bars - 1))
        top = self.bounds.y + 1
        bottom = max(top, self.bounds.bottom - 2)
        y = round(bottom - max(0.0, min(1.0, height)) * (bottom - top))
        return x, y

    def _commit(self, values: Sequence[float]) -> bool:
        changed = any(abs(left - float(right)) > 1e-8 for left, right in zip(self.harmonics, values))
        if not changed:
            return False
        self.harmonics = [max(0.0, min(1.0, float(value))) for value in values]
        self.on_change(tuple(self.harmonics))
        return True

    def _set_span(self, index: int, value: float) -> bool:
        values = list(self.harmonics)
        current = self._last_point
        if current is None:
            values[index] = value
        else:
            previous_index, previous_value = current
            start, end = sorted((previous_index, index))
            for bar in range(start, end + 1):
                amount = (bar - previous_index) / (index - previous_index) if index != previous_index else 1.0
                values[bar] = previous_value + (value - previous_value) * amount
        self.selected = index
        self._last_point = (index, value)
        return self._commit(values)

    def _erase_span(self, index: int) -> bool:
        values = list(self.harmonics)
        previous = self._last_point
        if previous is None:
            values[index] = 0.0
        else:
            previous_index, _ = previous
            for bar in range(min(previous_index, index), max(previous_index, index) + 1):
                values[bar] = 0.0
        self.selected = index
        self._last_point = (index, 0.0)
        return self._commit(values)

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "wheel_up":
            index = self.index_at(event.x)
            self.selected = index
            values = list(self.harmonics)
            values[index] = min(1.0, values[index] + 0.05 * event.steps)
            return self._commit(values)
        if event.kind == "wheel_down":
            index = self.index_at(event.x)
            self.selected = index
            values = list(self.harmonics)
            values[index] = max(0.0, values[index] - 0.05 * event.steps)
            return self._commit(values)
        if event.kind == "right":
            self._drag_mode = "erase"
            self._last_point = None
            return self._erase_span(self.index_at(event.x))
        if event.kind == "down" and event.button == "left":
            self._drag_mode = "paint"
            self._last_point = None
            return self._set_span(self.index_at(event.x), self.value_at(event.y))
        if event.kind == "move" and self._drag_mode is not None:
            index = self.index_at(event.x)
            if self._drag_mode == "erase":
                return self._erase_span(index)
            return self._set_span(index, self.value_at(event.y))
        if event.kind == "up":
            self._drag_mode = None
            self._last_point = None
            return True
        return False

    def handle_key(self, key: str, data: str = "") -> bool:
        del data
        if key == "left":
            self.selected = max(0, self.selected - 1)
            return True
        if key == "right":
            self.selected = min(self.visible_bars - 1, self.selected + 1)
            return True
        if key in {"up", "down", "pageup", "pagedown", "delete"}:
            values = list(self.harmonics)
            if key == "delete":
                values[self.selected] = 0.0
            else:
                delta = 0.25 if key in {"pageup", "pagedown"} else 0.05
                if key in {"down", "pagedown"}:
                    delta = -delta
                values[self.selected] = max(0.0, min(1.0, values[self.selected] + delta))
            return self._commit(values)
        if key == "c-e":
            return self._commit([value if index % 2 == 0 else 0.0 for index, value in enumerate(self.harmonics)])
        if key == "c-o":
            return self._commit([value if index % 2 == 1 else 0.0 for index, value in enumerate(self.harmonics)])
        if key == "c-r":
            rng = random.Random(54821 + self._random_round)
            self._random_round += 1
            anchors = [rng.random() for _ in range(17)]
            values = [anchors[index // 4] * (1 - (index % 4) / 4) + anchors[min(16, index // 4 + 1)] * ((index % 4) / 4) for index in range(64)]
            return self._commit(values)
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        bars = self.visible_bars
        symbols = self.density or (" ", ".", ":", "+", "#")
        if canvas.ascii_only:
            symbols = tuple(char if ord(char) < 128 else "#" for char in symbols)
        symbols = tuple(symbols) or (" ", ".", "+", "#")
        canvas.hit(self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height, self.tag, self)
        role = "focused" if focused else "heading" if hovered else "accent"
        canvas.text(self.bounds.x, self.bounds.y, f"HARMONICS · {bars} bars · drag paint / right-drag erase", role, max_width=self.bounds.width)
        top = self.bounds.y + 1
        bottom = max(top, self.bounds.bottom - 2)
        plot_height = max(1, bottom - top + 1)
        ramp_roles = ("aurora_0", "aurora_1", "aurora_2", "aurora_3", "aurora_4")
        for index in range(bars):
            value = self.harmonics[index]
            x = self.bounds.x + round(index * (self.bounds.width - 1) / max(1, bars - 1))
            height = round(value * (plot_height - 1))
            density_index = min(len(symbols) - 1, max(1, round(value * (len(symbols) - 1))))
            glyph = symbols[density_index]
            for row in range(bottom - height, bottom + 1):
                depth = min(1.0, max(0.0, (bottom - row + 1) / plot_height))
                role_index = min(len(ramp_roles) - 1, int(depth * len(ramp_roles)))
                canvas.put(x, row, glyph, ramp_roles[role_index])
            if index == self.selected:
                canvas.put(x, bottom, "|" if not canvas.ascii_only else "!", "focused")
        canvas.text(self.bounds.x, self.bounds.bottom - 1, "1   8   16   24   32   40   48   56   64", "muted", max_width=self.bounds.width)


class AuroraFader(Fader):
    """Short single-line control used to keep compact SHAPE readable."""

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        if self.bounds.height != 1:
            super().draw(canvas, focused=focused, hovered=hovered)
            return
        Widget.draw(self, canvas, focused=focused, hovered=hovered)
        width = self.bounds.width
        value = _format_compact_value(self.spec.key, self.value, self.spec.unit)
        label_width = min(8, max(3, width // 3))
        value_width = min(len(value), max(1, width // 4))
        track_width = max(1, width - label_width - value_width - 2)
        role = "focused" if focused else "hover" if hovered else "heading"
        label = _COMPACT_LABELS.get(self.spec.key, self.label)
        canvas.text(self.bounds.x, self.bounds.y, label, role, max_width=label_width)
        track_x = self.bounds.x + label_width + 1
        track = ["-"] * track_width
        track[round(self.unit * max(0, track_width - 1))] = "|"
        canvas.text(track_x, self.bounds.y, "".join(track), "focused" if focused else "accent")
        canvas.text(self.bounds.right - value_width, self.bounds.y, value[-value_width:], "selected", max_width=value_width)


def _format_compact_value(key: str, value: int | float, unit: str) -> str:
    number = float(value)
    if key == "flt.cut":
        return f"{number / 1000:.1f}k" if number >= 1000 else f"{number:.0f}"
    if unit == "s":
        return f"{number:.2g}s"
    if unit == "Hz":
        return f"{number:.2g}Hz"
    if unit == "cents":
        return f"{number:.0f}c"
    return f"{number:.2g}"


class _AuroraView:
    def __init__(self, shell) -> None:
        self.shell = shell
        self.screen_index = 0
        self.tabs: Tabs | None = None
        self.painter: HarmonicPainter | None = None
        self.controls: dict[str, Widget] = {}
        self.library_presets: ListBox | None = None
        self.library_skins: ListBox | None = None
        self.sequencer: SequencerWidget | None = None
        self.modulation: ModulationWidget | None = None
        self.sequencer_open = False
        self.modulation_open = False
        self._waterfall: deque[tuple[float, ...]] = deque(maxlen=8)
        self._last_waterfall_row = 0.0

    @property
    def screen(self) -> str:
        return SCREEN_NAMES[self.screen_index]

    def on_screen(self, key: str, shell) -> None:
        if key == "mod-return":
            self.modulation_open = False
            previous = shell._screen_before_modulation
            target = previous if previous in {"f2", "f3", "f4", "f5"} else "f2"
            shell.current_screen = target
            self.on_screen(target, shell)
            return
        if key in {"s-f4", "shift-f4"}:
            self.modulation_open = True
            self.sequencer_open = False
            self._select_screen(self.screen_index, notify=False)
            if self.modulation is not None:
                self.modulation.visible = True
                shell.widgets.focus(self.modulation.tag)
            shell.invalidate()
            return
        if key == "seq-return":
            self.sequencer_open = False
            previous = shell._screen_before_sequencer
            target = previous if previous in {"f2", "f3", "f4", "f5"} else "f2"
            shell.current_screen = target
            self.on_screen(target, shell)
            return
        if key in {"s-f3", "shift-f3"}:
            self.modulation_open = False
            self.sequencer_open = True
            self._select_screen(2, notify=False)
            if self.sequencer is not None:
                shell.widgets.focus(self.sequencer.tag)
            shell.invalidate()
            return
        if key.startswith("f") and key[1:].isdigit():
            self.modulation_open = False
            self.sequencer_open = False
            index = min(3, max(0, int(key[1:]) - 2))
            self._select_screen(index, notify=False)
            shell.widgets.clear_focus()

    def _select_screen(self, index: int, *, notify: bool = True) -> None:
        if notify:
            self.sequencer_open = False
        self.screen_index = min(3, max(0, index))
        if self.tabs is not None:
            self.tabs.selected = self.screen_index
        visible = self.screen
        if self.painter is not None:
            self.painter.visible = not self.modulation_open and visible in {"play", "shape"}
        for tag, widget in self.controls.items():
            widget.visible = not self.modulation_open and tag.startswith(visible + ":")
        if self.library_presets is not None:
            self.library_presets.visible = not self.modulation_open and visible == "library"
        if self.library_skins is not None:
            self.library_skins.visible = not self.modulation_open and visible == "library"
        if self.sequencer is not None:
            self.sequencer.visible = not self.modulation_open and self.sequencer_open
        if self.modulation is not None:
            self.modulation.visible = self.modulation_open
        if notify:
            self.shell.current_screen = f"f{self.screen_index + 2}"
            self.shell.widgets.clear_focus()
            self.shell.invalidate()

    def _piano_y(self, width: int, height: int) -> int:
        compact = width < 100 or height < 30
        piano_height = min(3 if compact else 5, max(3, height - 7))
        return max(4, height - piano_height - 3)

    def _painter_rect(self, width: int, height: int) -> Rect:
        compact = width < 100 or height < 30
        if self.screen == "play":
            top = 8 if compact else 9
            height_rows = 5
        else:
            top = 5
            height_rows = 4 if compact else 7
        bottom = self._piano_y(width, height)
        height_rows = max(3, min(height_rows, bottom - top))
        return Rect(2, top, max(1, width - 4), height_rows)

    def _controls_layout(self, width: int, height: int, page: str, count: int) -> list[Rect]:
        compact = width < 100 or height < 30
        if page == "play":
            start_y = 15 if not compact else 13
            columns = 4 if not compact else 3
        elif page == "shape":
            start_y = 12 if not compact else 9
            columns = 7 if not compact else 3
        else:
            start_y = 13
            columns = 6 if not compact else 4
        row_height = 1 if compact and page in {"play", "shape"} else 2
        max_rows = max(1, (self._piano_y(width, height) - start_y) // row_height)
        columns = min(columns, max(1, math.ceil(count / max_rows)))
        columns = min(columns, max(1, width // 10))
        cell_width = max(8, (width - 4) // columns)
        bounds: list[Rect] = []
        for index in range(count):
            row, column = divmod(index, columns)
            bounds.append(Rect(2 + column * cell_width, start_y + row * row_height, max(1, cell_width - 1), row_height))
        return bounds

    def _on_params(self, key: str, value: int | float) -> None:
        self.shell.set_param(key, value)

    def _on_harmonics(self, values: Sequence[float]) -> None:
        extras = dict(self.shell._known_extras)
        extras["harmonics"] = list(values)
        self.shell.set_extras(extras)

    def _load_library_preset(self, index: int, item: str) -> None:
        presets = self.shell.presets.list_presets()
        candidate = presets[index] if 0 <= index < len(presets) else None
        if candidate is None or candidate.name != item:
            self.shell.status_message = f"Preset {item!r} is no longer available"
            return
        try:
            self.shell.load_preset(candidate.id)
            self._sync_controls()
        except Exception as error:
            self.shell.status_message = f"Preset could not be loaded: {error}"
        self.shell.invalidate()

    def _select_library_skin(self, index: int, item: str) -> None:
        del index
        self.shell._select_skin(item)

    def _sync_controls(self) -> None:
        for key, widget in self.controls.items():
            if key.split(":", 1)[1] in self.shell._known_params and hasattr(widget, "set_value"):
                widget.value = self.shell._known_params[key.split(":", 1)[1]]

    def widgets(self, shell, width: int, height: int) -> tuple[Widget, ...]:
        self.shell = shell
        self.controls.clear()
        self.tabs = Tabs(
            "aurora-tabs",
            Rect(2, 3, max(1, width - 4), 1),
            tuple(name.upper() for name in SCREEN_NAMES),
            selected=self.screen_index,
            on_change=lambda index, _name: self._select_screen(index),
        )
        extras = shell._known_extras
        harmonics = extras.get("harmonics", (1.0,) * 64)
        painter_bounds = self._painter_rect(width, height)
        self.painter = HarmonicPainter(
            painter_bounds,
            harmonics,
            self._on_harmonics,
            visible_bars=64 if width >= 90 else 32,
        )
        registry = shell.registry
        screen_keys = {"play": _PLAY_KEYS, "shape": _SHAPE_KEYS, "space": _SPACE_KEYS}
        widgets: list[Widget] = [self.tabs, self.painter]
        seq_bounds = Rect(2, 5, max(1, width - 4), max(4, min(8, self._piano_y(width, height) - 5)))
        self.sequencer = SequencerWidget(shell, seq_bounds, "spectral")
        self.sequencer.visible = self.screen == "space"
        widgets.append(self.sequencer)
        mod_bounds = Rect(2, 3, max(1, width - 4), max(10, height - 3))
        self.modulation = ModulationWidget(shell, mod_bounds, "spectral")
        self.modulation.visible = self.modulation_open
        widgets.append(self.modulation)
        for page, keys in screen_keys.items():
            bounds = self._controls_layout(width, height, page, len(keys))
            for index, (key, rect) in enumerate(zip(keys, bounds)):
                spec = registry[key]
                tag = f"{page}:{key}"
                value = shell._known_params[key]
                label = _SHORT_LABELS.get(key, spec.label)
                if spec.kind == "choice":
                    control = Choice(tag, rect, spec, value, label=label, on_change=self._on_params)
                elif rect.height == 1:
                    control = AuroraFader(tag, rect, spec, value, label=label, on_change=self._on_params)
                else:
                    control = Fader(tag, rect, spec, value, label=label, on_change=self._on_params)
                control.visible = page == self.screen
                self.controls[tag] = control
                widgets.append(control)
        presets = shell.presets.list_presets()
        skin_items = shell.skins.ids
        lib_top = 6
        piano_y = self._piano_y(width, height)
        list_height = max(2, piano_y - lib_top - 1)
        split = (width - 6) // 2
        self.library_presets = ListBox(
            "aurora-library-presets",
            Rect(2, lib_top, max(10, split), list_height),
            tuple(preset.name for preset in presets) or ("No presets",),
            on_change=self._load_library_preset,
            on_activate=self._load_library_preset,
            label="PRESETS · selection previews",
        )
        self.library_skins = ListBox(
            "aurora-library-skins",
            Rect(4 + split, lib_top, max(10, width - split - 6), list_height),
            tuple(skin_items) or ("mono",),
            selected=skin_items.index(shell.skins.current_id) if shell.skins.current_id in skin_items else 0,
            on_change=self._select_library_skin,
            on_activate=self._select_library_skin,
            label="SKINS · selection previews",
        )
        self.library_presets.visible = self.screen == "library"
        self.library_skins.visible = self.screen == "library"
        widgets.extend((self.library_presets, self.library_skins))
        self._select_screen(self.screen_index, notify=False)
        return tuple(widgets)

    def _current_harmonics(self) -> tuple[float, ...]:
        values = self.shell._known_extras.get("harmonics", (0.0,) * 64)
        if self.painter is not None:
            values = self.painter.harmonics
        return tuple(float(value) for value in values)

    def extras_changed(self, extras: Mapping[str, object], shell) -> None:
        del shell
        if self.painter is None:
            return
        harmonics = extras.get("harmonics")
        if isinstance(harmonics, (list, tuple)) and len(harmonics) == 64:
            self.painter.harmonics = [float(value) for value in harmonics]

    def _current_levels(self, columns: int) -> tuple[float, ...]:
        telemetry = self.shell.engine.telemetry()
        instrument = telemetry.instrument
        spectrum = self._current_harmonics() if self.shell.snapshot_mode else instrument.get("table_magnitude", (0.0,) * 64)
        return waterfall_column_levels(
            spectrum,
            active_voices=telemetry.active_voices,
            voice_rms=float(instrument.get("voice_rms", 0.0)),
            columns=columns,
            frozen=self.shell.snapshot_mode,
            envelope_level=float(instrument.get("voice_envelope_sum", 0.0)),
            lfo_level=float(instrument.get("voice_lfo_level", 0.0)),
        )

    def _draw_waterfall(self, canvas: Canvas, y: int, rows: int) -> None:
        width = max(1, canvas.width - 4)
        telemetry = self.shell.engine.telemetry()
        instrument = telemetry.instrument
        frozen = self.shell.snapshot_mode
        if frozen:
            levels = self._current_levels(width)
            history = [tuple(value * (0.82 + 0.18 * ((row + 1) / rows)) for value in levels) for row in range(rows)]
        else:
            now = time.monotonic()
            if telemetry.active_voices and now - self._last_waterfall_row >= 1 / 12:
                self._waterfall.append(self._current_levels(width))
                self._last_waterfall_row = now
            elif telemetry.active_voices == 0:
                self._waterfall.clear()
            history = list(self._waterfall)[-rows:]
            history = [(0.0,) * width] * (rows - len(history)) + history
        count = telemetry.active_voices
        ready = "frozen" if frozen else "ready" if instrument.get("tables_ready") else "building"
        canvas.text(2, y - 1, f"AURORA WATERFALL · {count} voices · tables {ready} · log partials", "heading", max_width=canvas.width - 4)
        skin = self.shell.skins.current
        density = skin.glyphs.get("density", (" ", ".", ":", "-", "=", "+", "*", "#", "%", "@"))
        if not isinstance(density, tuple) or not density:
            density = (" ", ".", ":", "+", "#")
        ramp_roles = tuple(f"aurora_{index}" for index in range(5))
        for row_index, levels in enumerate(history):
            for column, level in enumerate(levels[:width]):
                if level <= 0.015:
                    continue
                density_index = min(len(density) - 1, max(1, round(level * (len(density) - 1))))
                role_index = min(len(ramp_roles) - 1, int(level * len(ramp_roles)))
                canvas.put(2 + column, y + row_index, density[density_index], ramp_roles[role_index])

    def draw(self, canvas: Canvas, shell) -> None:
        del shell
        if self.modulation_open:
            canvas.text(2, 4, "AURORA MOD · spectral patch field and post-tone pedals", "muted", max_width=canvas.width - 4)
            return
        if self.screen == "play":
            compact = canvas.width < 100 or canvas.height < 30
            water_rows = 3 if compact else 4
            self._draw_waterfall(canvas, 5, water_rows)
            if self.painter is not None:
                self.painter.bounds = self._painter_rect(canvas.width, canvas.height)
                density = self.shell.skins.current.glyphs.get("density")
                if isinstance(density, tuple):
                    self.painter.density = density
            return
        if self.screen == "shape":
            canvas.text(2, 4, "SHAPE · draw a spectrum, then tune its partials and both envelopes", "muted", max_width=canvas.width - 4)
            if self.painter is not None:
                self.painter.bounds = self._painter_rect(canvas.width, canvas.height)
                density = self.shell.skins.current.glyphs.get("density")
                if isinstance(density, tuple):
                    self.painter.density = density
            return
        if self.screen == "space":
            canvas.text(2, 4, "SPACE · modulation changes the voice; chorus, delay and reverb shape the shared field", "muted", max_width=canvas.width - 4)
            levels = self._current_levels(max(1, canvas.width - 8))
            center = 6 if canvas.height < 30 else 7
            for index, level in enumerate(levels):
                if level <= 0.015:
                    continue
                height = round(level * 2)
                glyph = "*" if canvas.ascii_only else "✦"
                canvas.put(4 + index, center - height, glyph, f"aurora_{min(4, int(level * 5))}")
                canvas.put(4 + index, center + height, glyph, f"aurora_{min(4, int(level * 5))}")
            return
        if self.screen == "library":
            canvas.text(2, 4, "LIBRARY · select a sound or colourway; F8 opens save, rename and delete actions", "muted", max_width=canvas.width - 4)

    def header(self, shell) -> str:
        preset = shell.engine_preset_name + ("*" if shell.modified else "")
        logo_rows = shell.skins.current.art_block("logo")
        logo = logo_rows[0].strip() if logo_rows else "AURORA"
        if shell.skins.current.id == "mono" or not logo:
            logo = "AURORA"
        return f"{logo} | {preset} | {shell.skins.current_id} | {shell.midi_status}"

    def footer(self, shell) -> str:
        if shell.overlay:
            return shell._footer()
        if self.modulation_open:
            return "MOD · click route · wheel amount · drag pedals · R source · T target · +/- amount · B bypass · Del clear · Esc return"
        if self.screen == "play":
            return "PLAY · paint/R erase · wheel · Tab · F2-F5 · F6 skin · F8 presets · F9 · ^Q"
        if self.screen == "shape":
            return "SHAPE · ↑/↓ .05 · PgUp/Dn .25 · Del · ^R random · ^E/O even/odd · ^Q"
        if self.screen == "space":
            return "SPACE · Shift+F3 sequencer · Tab controls · F6 skin · F8 presets · F9 · ^Q"
        return "LIBRARY · Tab list · arrows preview · Enter apply · F8 actions · F2-F5 · ^Q"

    def refresh_when(self, shell) -> bool:
        return not self.modulation_open and self.screen == "play" and shell.engine.telemetry().active_voices > 0


class AuroraUI:
    """Per-shell view instances behind stateless InstrumentSpec callbacks."""

    def __init__(self) -> None:
        self._views: WeakKeyDictionary[object, _AuroraView] = WeakKeyDictionary()

    def _view(self, shell) -> _AuroraView:
        view = self._views.get(shell)
        if view is None:
            view = _AuroraView(shell)
            self._views[shell] = view
        return view

    def draw(self, canvas: Canvas, shell) -> None:
        self._view(shell).draw(canvas, shell)

    def widgets(self, shell, width: int, height: int) -> tuple[Widget, ...]:
        return self._view(shell).widgets(shell, width, height)

    def on_screen(self, key: str, shell) -> None:
        self._view(shell).on_screen(key, shell)

    def header(self, shell) -> str:
        return self._view(shell).header(shell)

    def footer(self, shell) -> str:
        return self._view(shell).footer(shell)

    def refresh_when(self, shell) -> bool:
        return self._view(shell).refresh_when(shell)

    def extras_changed(self, extras: Mapping[str, object], shell) -> None:
        self._view(shell).extras_changed(extras, shell)


__all__ = ["AuroraUI", "HarmonicPainter", "SCREEN_NAMES", "waterfall_column_levels"]
