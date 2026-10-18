"""DRIFT's weather-map surface and instrument-owned HUD screens."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Mapping
from weakref import WeakKeyDictionary

from trio_kit.events import InstrumentEvent
from trio_kit.params import ParamSpec
from trio_kit.shell import InstrumentSpec, Shell
from trio_kit.tui import Canvas, Rect, SequencerWidget
from trio_kit.tui.mouse import MouseInput
from trio_kit.tui.widgets import Widget

from trio_drift.instrument import DriftInstrument
from trio_drift.params import drift_registry


SCREEN_NAMES = ("map", "grain", "air", "library")
_VOWELS = ("A", "E", "I", "O", "U")
_GRAIN_KEYS = (
    "gr.density", "gr.size", "gr.size_jit", "gr.pos", "gr.pos_scatter",
    "gr.spread", "gr.pitch_scatter", "gr.window", "gr.max",
)
_AIR_KEYS = (
    "src.color", "src.tone", "src.breath", "fmt.vowel", "fmt.shift", "fmt.q",
    "fmt.mix", "field.amount", "wind.gust", "wind.howl", "wind.rate", "fx.reverb.mix",
)


def _clamp_unit(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _glyphs(skin: object, name: str, fallback: tuple[str, ...], *, ascii_only: bool) -> tuple[str, ...]:
    raw = None
    ascii_glyphs = getattr(skin, "ascii_glyphs", {})
    if ascii_only and isinstance(ascii_glyphs, Mapping):
        raw = ascii_glyphs.get(name)
    if raw is None:
        raw = getattr(skin, "glyphs", {}).get(name)
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, tuple) and raw:
        return tuple(raw)
    if isinstance(raw, list) and raw:
        return tuple(str(item) for item in raw)
    return fallback


def _short_name(key: str) -> str:
    return {
        "gr.density": "density", "gr.size": "size", "gr.size_jit": "size jitter",
        "gr.pos": "position", "gr.pos_scatter": "position scatter",
        "gr.pitch_scatter": "pitch scatter", "gr.window": "window",
        "gr.spread": "spread", "gr.max": "max grains",
        "src.color": "source colour", "src.tone": "tone", "src.breath": "breath",
        "fmt.vowel": "vowel", "fmt.shift": "formant shift", "fmt.q": "formant Q",
        "fmt.mix": "formant", "field.amount": "field mix",
        "wind.gust": "wind gust", "wind.howl": "howl", "wind.rate": "wind rate",
        "fx.reverb.mix": "reverb",
    }.get(key, key.rsplit(".", 1)[-1])


def _format_value(spec: ParamSpec, value: int | float) -> str:
    if spec.kind == "choice" and spec.choices:
        return spec.choices[min(len(spec.choices) - 1, max(0, int(value)))]
    numeric = float(value)
    if spec.key == "gr.density":
        return f"{numeric:.0f}/s"
    if spec.key == "gr.size":
        return f"{numeric:.0f}ms"
    if spec.key == "gr.max":
        return str(int(numeric))
    if spec.key == "gr.pitch_scatter":
        return f"{numeric:.0f}c"
    if spec.key == "wind.rate":
        return f"{numeric:.2f}Hz"
    if spec.key == "fmt.vowel":
        return _VOWELS[min(4, max(0, int(numeric)))]
    if spec.key.endswith(".color"):
        return f"{numeric:+.2f}"
    return f"{numeric:.2f}"


class WeatherMap(Widget):
    """Seeded isobars and cell-safe particles for the current active grains."""

    def __init__(self, shell: Shell, bounds: Rect, *, clock=time.monotonic) -> None:
        super().__init__("drift-weather-map", bounds, label="DRIFT weather map")
        self.shell = shell
        self.clock = clock
        self.started_at = clock()
        noise = random.Random(int(getattr(shell.engine, "seed", 0)) ^ 0xD71F7)
        self._lattice = tuple(tuple(noise.random() for _ in range(8)) for _ in range(12))
        self._mouse_gust = False
        self._keyboard_gust = False
        self._gust_active = False
        self.drawn_particle_count = 0
        self.particle_cells: tuple[tuple[int, int], ...] = ()
        self.cursor_cell: tuple[int, int] | None = None

    @property
    def plot(self) -> Rect:
        return Rect(self.bounds.x + 2, self.bounds.y + 1, max(1, self.bounds.width - 4), max(1, self.bounds.height - 2))

    def _noise_value(self, x: int, y: int, width: int, height: int, phase: float) -> float:
        gx = x / max(1, width - 1) * 6.0 + phase
        gy = y / max(1, height - 1) * 3.0 - phase * 0.31
        ix, iy = math.floor(gx), math.floor(gy)
        fx, fy = gx - ix, gy - iy
        fx = fx * fx * (3.0 - 2.0 * fx)
        fy = fy * fy * (3.0 - 2.0 * fy)
        columns, rows = len(self._lattice), len(self._lattice[0])
        a = self._lattice[ix % columns][iy % rows]
        b = self._lattice[(ix + 1) % columns][iy % rows]
        c = self._lattice[ix % columns][(iy + 1) % rows]
        d = self._lattice[(ix + 1) % columns][(iy + 1) % rows]
        top = a + (b - a) * fx
        bottom = c + (d - c) * fx
        return top + (bottom - top) * fy

    def _set_gust_source(self, source: str, enabled: bool) -> None:
        if source == "mouse":
            self._mouse_gust = enabled
        else:
            self._keyboard_gust = enabled
        active = self._mouse_gust or self._keyboard_gust
        if active != self._gust_active:
            self._gust_active = active
            name = "gust_on" if active else "gust_off"
            self.shell._push(InstrumentEvent(name, ()))

    def _set_cursor(self, x: float, y: float) -> None:
        self.shell.set_param("field.x", _clamp_unit(x), record_history=False)
        self.shell.set_param("field.y", _clamp_unit(y), record_history=False)

    def _point_to_cursor(self, x: int, y: int) -> None:
        plot = self.plot
        x_unit = 0.5 if plot.width <= 1 else (x - plot.x) / (plot.width - 1)
        # Screen rows grow downward; the top of the map is the storm end of field.y.
        y_unit = 0.5 if plot.height <= 1 else (plot.bottom - 1 - y) / (plot.height - 1)
        self._set_cursor(x_unit, y_unit)

    def _density_step(self, amount: int) -> None:
        spec = self.shell.registry["gr.density"]
        current = float(self.shell._known_params["gr.density"])
        self.shell.set_param("gr.density", spec.from_unit(_clamp_unit(spec.to_unit(current) + amount * 0.01)), record_history=False)

    def handle_key(self, key: str, data: str = "") -> bool:
        del data
        x = float(self.shell._known_params["field.x"])
        y = float(self.shell._known_params["field.y"])
        if key == "left":
            self._set_cursor(x - 0.02, y)
        elif key == "right":
            self._set_cursor(x + 0.02, y)
        elif key == "up":
            self._set_cursor(x, y + 0.02)
        elif key == "down":
            self._set_cursor(x, y - 0.02)
        elif key == "pageup":
            self._set_cursor(x, y + 0.10)
        elif key == "pagedown":
            self._set_cursor(x, y - 0.10)
        elif key == "enter":
            self._set_gust_source("keyboard", not self._keyboard_gust)
        elif key == "delete":
            self._set_cursor(0.5, 0.5)
        else:
            return False
        self.shell.invalidate()
        return True

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right" and event.button == "right":
            self._set_cursor(0.5, 0.5)
            self.shell.invalidate()
            return True
        if event.kind == "down" and event.button == "left":
            self._point_to_cursor(event.x, event.y)
            self._set_gust_source("mouse", True)
            self.shell.invalidate()
            return True
        if event.kind == "move" and self._mouse_gust:
            self._point_to_cursor(event.x, event.y)
            self.shell.invalidate()
            return True
        if event.kind == "up" and self._mouse_gust:
            self._set_gust_source("mouse", False)
            self.shell.invalidate()
            return True
        if event.kind == "wheel_up":
            self._density_step(event.steps)
            return True
        if event.kind == "wheel_down":
            self._density_step(-event.steps)
            return True
        return False

    @staticmethod
    def _particle_coordinate(value: float, minimum: float, maximum: float, start: int, end: int) -> int:
        if start == end or not math.isfinite(value):
            return start
        unit = _clamp_unit((value - minimum) / (maximum - minimum))
        return start + round(unit * (end - start))

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        if width < 5 or height < 3:
            return
        skin = self.shell.skins.current
        canvas.fill(x, y, width, height, " ", "background")
        plot = self.plot
        phase = 0.0 if self.shell.snapshot_mode else max(0.0, self.clock() - self.started_at) * 0.055
        isobars = _glyphs(skin, "isobar", (".", ":", "~"), ascii_only=canvas.ascii_only)
        isobar_ramp = skin.ramp("isobar")
        if not isobar_ramp:
            isobar_ramp = skin.ramp("mono")
        if skin.id == "mono":
            field_styles = ("muted", "border", "text", "heading")[:len(isobar_ramp)]
        else:
            field_styles = tuple(f"isobar_{index}" for index in range(len(isobar_ramp)))
        for row in range(plot.height):
            for column in range(plot.width):
                value = self._noise_value(column, row, plot.width, plot.height, phase)
                contour = value * 6.0
                distance = abs(contour - round(contour))
                if distance < 0.105:
                    glyph_index = min(len(isobars) - 1, max(0, round(value * (len(isobars) - 1))))
                    ramp_index = min(len(field_styles) - 1, max(0, round(value * (len(field_styles) - 1)))) if field_styles else 0
                    role = field_styles[ramp_index] if field_styles and field_styles[ramp_index] in skin.styles else "muted"
                    canvas.put(plot.x + column, plot.y + row, isobars[glyph_index], role)

        telemetry = self.shell.engine.telemetry().instrument
        pans = telemetry.get("grain_pan", ())
        ratios = telemetry.get("grain_ratio", ())
        amplitudes = telemetry.get("grain_amplitude", ())
        ages = telemetry.get("grain_age", ())
        if not isinstance(pans, tuple):
            pans = ()
        if not isinstance(ratios, tuple):
            ratios = ()
        if not isinstance(amplitudes, tuple):
            amplitudes = ()
        if not isinstance(ages, tuple):
            ages = ()
        count = min(len(pans), len(ratios), len(amplitudes), len(ages))
        grain_glyphs = _glyphs(skin, "grain", (".", ":", "o", "O", "@"), ascii_only=canvas.ascii_only)
        if skin.id == "mono" and "grain" not in skin.glyphs:
            density_glyphs = _glyphs(skin, "density", (" ", ".", ":", "+", "#"), ascii_only=canvas.ascii_only)
            grain_glyphs = tuple(glyph for glyph in density_glyphs if glyph.strip()) or (".", ":", "+", "#")
        age_ramp = skin.ramp("grain_age")
        if not age_ramp:
            age_ramp = skin.ramp("mono")
        if skin.id == "mono":
            age_roles = ("muted", "border", "text", "accent")[:len(age_ramp)]
        else:
            age_roles = tuple(f"grain_age_{index}" for index in range(len(age_ramp)))
        if not age_roles:
            age_roles = ("muted", "text", "accent")
        cells: list[tuple[int, int]] = []
        occupied_cells: set[tuple[int, int]] = set()
        for index in range(count):
            try:
                pan, ratio, amplitude, age = map(float, (pans[index], ratios[index], amplitudes[index], ages[index]))
            except (TypeError, ValueError, OverflowError):
                continue
            if not all(math.isfinite(value) for value in (pan, ratio, amplitude, age)) or ratio <= 0.0:
                continue
            px = self._particle_coordinate(pan, 0.0, 1.0, plot.x, plot.right - 1)
            log_pitch = math.log2(ratio)
            py = self._particle_coordinate(log_pitch, -4.0, 4.0, plot.bottom - 1, plot.y)
            amp_index = min(len(grain_glyphs) - 1, max(0, round(_clamp_unit(amplitude) * (len(grain_glyphs) - 1))))
            age_index = min(len(age_roles) - 1, max(0, round(_clamp_unit(age) * (len(age_roles) - 1))))
            role_name = age_roles[age_index]
            role = role_name if role_name in skin.styles else ("muted" if age_index == 0 else "accent")
            cell = (px, py)
            if canvas.put(px, py, grain_glyphs[amp_index], role):
                cells.append(cell)
                occupied_cells.add(cell)
        self.particle_cells = tuple(cells)
        self.drawn_particle_count = len(occupied_cells)

        field_x = float(self.shell._known_params["field.x"])
        field_y = float(self.shell._known_params["field.y"])
        cursor_x = plot.x if plot.width <= 1 else plot.x + round(_clamp_unit(field_x) * (plot.width - 1))
        cursor_y = plot.bottom - 1 if plot.height <= 1 else plot.bottom - 1 - round(_clamp_unit(field_y) * (plot.height - 1))
        cursor_glyphs = _glyphs(skin, "cursor", ("@",), ascii_only=canvas.ascii_only)
        cursor = cursor_glyphs[-1]
        if canvas.ascii_only and skin.id == "mono":
            cursor = "@"
        canvas.put(cursor_x, cursor_y, cursor, "selected" if self._gust_active else "accent")
        self.cursor_cell = (cursor_x, cursor_y)

        vowel_value = int(round(float(telemetry.get("vowel", 0.0))))
        vowel_value = min(4, max(0, vowel_value))
        canvas.text(x + 1, y, "STORM ^", "heading", max_width=9)
        canvas.text(x + 11, y, "  ".join(_VOWELS), "accent", max_width=min(15, width - 23))
        vowel_x = x + 11 + vowel_value * 3
        canvas.text(vowel_x, y, _VOWELS[vowel_value], "selected", max_width=1)
        gust = "GUST" if self._gust_active or float(telemetry.get("gust", 0.0)) > 0.01 else "CALM"
        canvas.text(x + 1, y + height - 1, f"CALM v  {count:02d} grains  {gust}", "muted", max_width=width - 2)


class ParameterDrawer(Widget):
    """A compact pop-over that edits one instrument-owned parameter at a time."""

    def __init__(
        self,
        shell: Shell,
        bounds: Rect,
        title: str,
        keys: tuple[str, ...],
        on_close: Callable[[], object],
    ) -> None:
        super().__init__(f"drift-{title.casefold()}-drawer", bounds, label=title)
        self.shell = shell
        self.keys = keys
        self.on_close = on_close
        self.selected = 0

    def _adjust(self, key: str, step: int) -> bool:
        spec = self.shell.registry[key]
        current = self.shell._known_params[key]
        if spec.kind in {"choice", "discrete"}:
            if spec.kind == "choice":
                value = (int(current) + step) % len(spec.choices or ())
            else:
                value = min(int(spec.maximum), max(int(spec.minimum), int(current) + step))
        else:
            value = spec.from_unit(_clamp_unit(spec.to_unit(current) + step * 0.02))
        return self.shell.set_param(key, value, record_history=False)

    def _select_at(self, x: int, y: int) -> tuple[int, int, int]:
        local_x = x - self.bounds.x - 1
        local_y = y - self.bounds.y - 1
        columns = 2
        col_width = max(1, (self.bounds.width - 2) // columns)
        column = min(columns - 1, max(0, local_x // col_width))
        row = min(max(0, self.bounds.height - 3), max(0, local_y))
        self.selected = min(len(self.keys) - 1, row * columns + column)
        return self.selected, local_x % col_width, col_width

    def handle_key(self, key: str, data: str = "") -> bool:
        del data
        if key == "escape":
            self.on_close()
            return True
        if key in {"up", "down"}:
            self.selected = (self.selected + (-1 if key == "up" else 1)) % len(self.keys)
            return True
        if key in {"left", "right", "pagedown", "pageup", "home", "end", "delete", "enter", "space"}:
            name = self.keys[self.selected]
            spec = self.shell.registry[name]
            if key in {"home", "delete"}:
                value = spec.minimum if key == "home" else spec.default
                self.shell.set_param(name, value, record_history=False)
            elif key == "end":
                self.shell.set_param(name, spec.maximum, record_history=False)
            else:
                steps = {"left": -1, "right": 1, "pagedown": -5, "pageup": 5, "enter": 1, "space": 1}[key]
                self._adjust(name, steps)
            return True
        return False

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            selected, _, _ = self._select_at(event.x, event.y)
            self.shell.set_param(self.keys[selected], self.shell.registry[self.keys[selected]].default, record_history=False)
            return True
        if event.kind in {"wheel_up", "wheel_down"}:
            selected, _, _ = self._select_at(event.x, event.y)
            direction = 1 if event.kind == "wheel_up" else -1
            self._adjust(self.keys[selected], direction * event.steps)
            return True
        if event.kind == "down" and event.button == "left":
            _, cell_x, col_width = self._select_at(event.x, event.y)
            # Clicking the right half of a control increments it; the left half selects it.
            if cell_x >= col_width // 2:
                self._adjust(self.keys[self.selected], 1)
            return True
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        del hovered
        super().draw(canvas, focused=focused)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        canvas.fill(x, y, width, height, " ", "background")
        canvas.box(x, y, width, height, role="border")
        canvas.text(x + 2, y, f"{self.label}  Up/Dn select | Left/Right adjust | Esc map", "focused" if focused else "heading", max_width=width - 4)
        columns = 2
        col_width = max(1, (width - 2) // columns)
        for index, key in enumerate(self.keys):
            row, column = divmod(index, columns)
            if row >= height - 2:
                break
            spec = self.shell.registry[key]
            value = self.shell._known_params[key]
            value_text = _format_value(spec, value)
            unit = _clamp_unit(spec.to_unit(value))
            bar_width = min(8, max(3, col_width - len(_short_name(key)) - len(value_text) - 5))
            filled = round(unit * bar_width)
            marker = "━" if not canvas.ascii_only else "="
            blank = "─" if not canvas.ascii_only else "-"
            if spec.kind in {"choice", "discrete"}:
                bar = ""
            else:
                bar = f" [{marker * filled}{blank * (bar_width - filled)}]"
            text = f"{_short_name(key)} {value_text}{bar}"
            role = "selected" if focused and index == self.selected else "text"
            canvas.text(x + 1 + column * col_width, y + 1 + row, ("> " if index == self.selected else "  ") + text, role, max_width=col_width)


class LibraryHUD(Widget):
    """Preset and colourway picker shown over the weather field."""

    def __init__(self, shell: Shell, bounds: Rect, on_close) -> None:
        super().__init__("drift-library", bounds, label="DRIFT library")
        self.shell = shell
        self.on_close = on_close
        self.side = 0
        self.preset_index = 0
        self.skin_index = max(0, self.shell.skins.ids.index(self.shell.skins.current_id)) if self.shell.skins.ids else 0
        current = self.shell.current_preset
        if current is not None:
            self.preset_index = next(
                (index for index, preset in enumerate(self._presets()) if preset.id == current.id),
                0,
            )

    def _presets(self):
        return self.shell.presets.list_presets()

    def _move(self, delta: int) -> None:
        if self.side == 0:
            presets = self._presets()
            self.preset_index = min(max(0, self.preset_index + delta), max(0, len(presets) - 1))
        else:
            self.skin_index = min(max(0, self.skin_index + delta), max(0, len(self.shell.skins.ids) - 1))

    def _activate(self) -> bool:
        if self.side == 0:
            presets = self._presets()
            if not presets:
                return False
            preset = presets[min(self.preset_index, len(presets) - 1)]
            try:
                self.shell.load_preset(preset.id)
            except Exception as error:
                self.shell.status_message = f"Preset unavailable: {error}"
                return False
            self.shell.status_message = f"Loaded {preset.name}"
        else:
            skins = self.shell.skins.ids
            if not skins:
                return False
            skin_id = skins[min(self.skin_index, len(skins) - 1)]
            self.shell._select_skin(skin_id)
            self.shell.status_message = f"Colourway {skin_id}"
        self.shell.invalidate()
        return True

    def handle_key(self, key: str, data: str = "") -> bool:
        del data
        if key == "escape":
            self.on_close()
        elif key in {"left", "right", "tab"}:
            self.side = 1 - self.side
        elif key in {"up", "down", "pageup", "pagedown"}:
            delta = {"up": -1, "down": 1, "pageup": -5, "pagedown": 5}[key]
            self._move(delta)
        elif key == "enter":
            self._activate()
        else:
            return False
        return True

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind != "down" or event.button != "left":
            return event.kind in {"up", "move"}
        column = 0 if event.x < self.bounds.x + self.bounds.width // 2 else 1
        self.side = column
        row = max(0, event.y - self.bounds.y - 2)
        if column == 0:
            self.preset_index = min(max(0, row), max(0, len(self._presets()) - 1))
        else:
            self.skin_index = min(max(0, row), max(0, len(self.shell.skins.ids) - 1))
        self._activate()
        return True

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        del hovered
        super().draw(canvas, focused=focused)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        canvas.fill(x, y, width, height, " ", "background")
        canvas.box(x, y, width, height, role="border")
        canvas.text(x + 2, y, "DRIFT LIBRARY  Left/Right choose | Up/Dn select | Enter apply | Esc map", "heading", max_width=width - 4)
        half = max(1, (width - 2) // 2)
        canvas.vline(x + 1 + half, y + 1, height - 2, "│" if not canvas.ascii_only else "|", "border")
        canvas.text(x + 2, y + 1, "SOUNDS", "focused" if focused and self.side == 0 else "accent", max_width=half - 2)
        canvas.text(x + 2 + half, y + 1, "COLOURWAYS", "focused" if focused and self.side == 1 else "accent", max_width=half - 2)
        presets = self._presets()
        for index, preset in enumerate(presets[: height - 3]):
            role = "selected" if focused and self.side == 0 and index == self.preset_index else "text"
            canvas.text(x + 2, y + 2 + index, ("> " if index == self.preset_index else "  ") + preset.name, role, max_width=half - 2)
        for index, skin_id in enumerate(self.shell.skins.ids[: height - 3]):
            role = "selected" if focused and self.side == 1 and index == self.skin_index else "text"
            marker = "* " if skin_id == self.shell.skins.current_id else "  "
            canvas.text(x + 2 + half, y + 2 + index, ("> " if index == self.skin_index else marker) + skin_id, role, max_width=half - 2)


class _View:
    def __init__(self, shell: Shell, clock) -> None:
        self.shell = shell
        self.clock = clock
        self.screen = "map"
        self.weather: WeatherMap | None = None
        self.grain: ParameterDrawer | None = None
        self.air: ParameterDrawer | None = None
        self.library: LibraryHUD | None = None
        self.sequencer: SequencerWidget | None = None

    def _close(self) -> None:
        self.screen = "map"
        self.shell.current_screen = "f2"
        self._visibility()
        self.shell.widgets.focus("drift-weather-map")
        self.shell.status_message = "Weather map"
        self.shell.invalidate()

    def _visibility(self) -> None:
        if self.weather is not None:
            self.weather.visible = True
        if self.grain is not None:
            self.grain.visible = self.screen == "grain"
        if self.air is not None:
            self.air.visible = self.screen == "air"
        if self.library is not None:
            self.library.visible = self.screen == "library"
        if self.sequencer is not None:
            self.sequencer.visible = self.screen == "sequencer"

    def widgets(self, width: int, height: int) -> tuple[Widget, ...]:
        compact = width < 100 or height < 30
        piano_height = 3 if compact else 4
        piano_y = max(4, height - piano_height - 3)
        map_height = max(6, piano_y - 6)
        map_bounds = Rect(2, 4, max(1, width - 4), map_height)
        self.weather = WeatherMap(self.shell, map_bounds, clock=self.clock)
        panel_width = max(1, min(map_bounds.width - 4, 74))
        panel_x = map_bounds.x + (map_bounds.width - panel_width) // 2
        grain_height = 7
        air_height = 8
        grain_y = max(map_bounds.y + 1, map_bounds.bottom - grain_height - 1)
        air_y = max(map_bounds.y + 1, map_bounds.bottom - air_height - 1)
        self.grain = ParameterDrawer(self.shell, Rect(panel_x, grain_y, panel_width, grain_height), "GRAIN", _GRAIN_KEYS, self._close)
        self.air = ParameterDrawer(self.shell, Rect(panel_x, air_y, panel_width, air_height), "AIR", _AIR_KEYS, self._close)
        library_height = min(11, map_bounds.height - 1)
        library_y = map_bounds.y + (map_bounds.height - library_height) // 2
        self.library = LibraryHUD(self.shell, Rect(panel_x, library_y, panel_width, library_height), self._close)
        seq_y = map_bounds.y + 1
        seq_height = max(4, min(8, map_bounds.height - 2))
        self.sequencer = SequencerWidget(self.shell, Rect(panel_x, seq_y, panel_width, seq_height), "pressure")
        self._visibility()
        return (self.weather, self.grain, self.air, self.library, self.sequencer)

    def on_screen(self, key: str) -> None:
        if key == "seq-return":
            previous = self.shell._screen_before_sequencer
            target = previous if previous in {"f2", "f3", "f4", "f5"} else "f2"
            self.shell.current_screen = target
            self.on_screen(target)
            return
        self.screen = {"f2": "map", "f3": "grain", "f4": "air", "f5": "library", "s-f3": "sequencer", "shift-f3": "sequencer"}.get(key, "map")
        self._visibility()
        tag = {
            "map": "drift-weather-map", "grain": "drift-grain-drawer",
            "air": "drift-air-drawer", "library": "drift-library",
            "sequencer": "sequencer-pressure",
        }[self.screen]
        self.shell.widgets.focus(tag)
        self.shell.invalidate()


class DriftUI:
    """Per-shell DRIFT presentation state; no other instrument is imported."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self.clock = clock
        self._views: WeakKeyDictionary[Shell, _View] = WeakKeyDictionary()

    def view(self, shell: Shell) -> _View:
        view = self._views.get(shell)
        if view is None:
            view = _View(shell, self.clock)
            self._views[shell] = view
        return view

    def widgets(self, shell: Shell, width: int, height: int) -> tuple[Widget, ...]:
        return self.view(shell).widgets(width, height)

    def draw(self, canvas: Canvas, shell: Shell) -> None:
        telemetry = shell.engine.telemetry()
        params = shell._known_params
        wind = float(telemetry.instrument.get("wind", 0.0))
        gust = float(telemetry.instrument.get("gust", 0.0))
        status = f"FIELD x {float(params['field.x']):.2f} | y {float(params['field.y']):.2f}   WIND {wind:+.2f}   GUST {gust:.2f}"
        canvas.text(2, 3, status, "muted", max_width=canvas.width - 4)

    def header(self, shell: Shell) -> str:
        skin = shell.skins.current
        logo_rows = skin.art_block("logo")
        logo = logo_rows[0].strip() if logo_rows else "DRIFT WEATHER"
        if skin.id == "mono" or not logo:
            logo = "DRIFT WEATHER"
        telemetry = shell.engine.telemetry()
        grains = telemetry.instrument.get("active_grains", 0)
        return f"DRIFT / {logo} / {shell.engine_preset_name} / {shell.skins.current_id} / grains {grains}"

    def footer(self, shell: Shell) -> str:
        screen = self.view(shell).screen
        if screen == "grain":
            return "GRAIN click select/+ wheel adjust; arrows select/adjust; Del reset; Esc map"
        if screen == "air":
            return "AIR click select/+ wheel adjust; arrows select/adjust; Del reset; Esc map"
        if screen == "library":
            return "LIB sounds/skins left/right switch up/dn select Enter apply Esc map F8 actions"
        if screen == "sequencer":
            return "SEQ arrows · Enter toggle · drag velocity · right-click chance · Space transport · A/M/O/R/L arp · Esc map"
        return "MAP drag/gust; right=centre; wheel=density; F2 map F3 grain Shift+F3 seq F4 air F5 lib"

    def on_screen(self, key: str, shell: Shell) -> None:
        self.view(shell).on_screen(key)

    def refresh_when(self, shell: Shell) -> bool:
        return not shell.snapshot_mode and self.view(shell).screen in {"map", "grain", "air", "library"}

    def help_rows(self, shell: Shell) -> tuple[str, ...]:
        del shell
        return (
            "DRIFT map: left-drag steers x/y and holds gust until release; right-click recentres",
            "Map keyboard twin: focus map; arrows move 2%, PageUp/Down move vertically 10%, Enter gust, Delete centre",
            "Mouse wheel changes grain density; particles show active grain pan, pitch, amplitude and age",
            "F3 grain controls · Shift+F3 sequencer ring · F4 air controls · F5 preset and skin library · Escape returns",
            "Grain/Air: click selects or increments; wheel adjusts; right-click resets the pointed control",
            "Drawer keys: Up/Down select; Left/Right adjust; PageUp/Down coarse; Home/End limits; Delete default",
            "F6 changes skin · F8 shared preset actions · F9 panic · Ctrl+Q quits",
        )


def drift_spec(*, clock=time.monotonic) -> InstrumentSpec:
    """Create DRIFT's shared-shell spec without importing AURORA or LOOM."""
    from pathlib import Path

    ui = DriftUI(clock=clock)
    root = Path(__file__).resolve().parent
    return InstrumentSpec(
        identifier="drift",
        name="DRIFT",
        instrument_factory=DriftInstrument,
        registry=drift_registry(),
        factory_package="trio_drift",
        factory_presets_dir=root / "data" / "presets",
        factory_skins_dir=root / "data" / "skins",
        max_voices=6,
        draw=ui.draw,
        widgets=ui.widgets,
        on_screen=ui.on_screen,
        screen_names=SCREEN_NAMES,
        piano_octaves=2,
        piano_height=4,
        compact_piano_height=3,
        refresh_hz=20,
        refresh_when=ui.refresh_when,
        header=ui.header,
        footer=ui.footer,
        help_rows=ui.help_rows,
    )


__all__ = ["DriftUI", "LibraryHUD", "ParameterDrawer", "SCREEN_NAMES", "WeatherMap", "drift_spec"]
