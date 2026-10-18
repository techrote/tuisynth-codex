"""Engine-independent keyboard and mouse controls for terminal layouts."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

from trio_kit.params import ParamSpec
from trio_kit.tui.canvas import Canvas, Rect
from trio_kit.tui.mouse import MouseInput


ChangeCallback = Callable[[str, int | float], object]


class Widget:
    """Base control with a stable hit tag and shared input vocabulary."""

    def __init__(self, tag: str, bounds: Rect, *, label: str = "", focusable: bool = True) -> None:
        if not isinstance(tag, str) or not tag:
            raise ValueError("widget tag must be a non-empty string")
        if not isinstance(bounds, Rect) or bounds.width < 1 or bounds.height < 1:
            raise ValueError("widget bounds must be a non-empty Rect")
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        self.tag = tag
        self.bounds = bounds
        self.label = label
        self.focusable = bool(focusable)

    @property
    def id(self) -> str:
        return self.tag

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        canvas.hit(self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height, self.tag, self)

    def handle_key(self, key: str, data: str = "") -> bool:
        if key in {"enter", "space"}:
            return self.activate()
        return False

    def handle_mouse(self, event: MouseInput) -> bool:
        return False

    def activate(self) -> bool:
        return False

    def reset(self) -> bool:
        return False


class ParamWidget(Widget):
    """A control bound to validated parameter metadata and a callback only."""

    def __init__(
        self,
        tag: str,
        bounds: Rect,
        spec: ParamSpec,
        value: object | None = None,
        *,
        label: str | None = None,
        on_change: ChangeCallback | None = None,
        default: object | None = None,
    ) -> None:
        if not isinstance(spec, ParamSpec):
            raise TypeError("spec must be a ParamSpec")
        super().__init__(tag, bounds, label=spec.label if label is None else label)
        self.spec = spec
        self.on_change = on_change
        self.default = spec.validate_value(spec.default if default is None else default)
        self.value = spec.validate_value(spec.default if value is None else value)

    @property
    def unit(self) -> float:
        return self.spec.to_unit(self.value)

    def set_value(self, value: object) -> bool:
        validated = self.spec.validate_value(value)
        if validated == self.value:
            return False
        self.value = validated
        if self.on_change is not None:
            self.on_change(self.spec.key, validated)
        return True

    def adjust(self, steps: int) -> bool:
        if isinstance(steps, bool) or not isinstance(steps, int):
            raise TypeError("steps must be an integer")
        if self.spec.kind in {"discrete", "choice"}:
            bounded = min(float(self.spec.maximum), max(float(self.spec.minimum), float(self.value) + steps))
            return self.set_value(bounded)
        return self.set_value(self.spec.from_unit(min(1.0, max(0.0, self.unit + steps / 100.0))))

    def reset(self) -> bool:
        return self.set_value(self.default)

    def handle_key(self, key: str, data: str = "") -> bool:
        if key in {"left", "down"}:
            return self.adjust(-1)
        if key in {"right", "up"}:
            return self.adjust(1)
        if key == "pagedown":
            return self.adjust(-10)
        if key == "pageup":
            return self.adjust(10)
        if key == "home":
            return self.set_value(self.spec.minimum)
        if key == "end":
            return self.set_value(self.spec.maximum)
        if key == "delete":
            return self.reset()
        return super().handle_key(key, data)

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            return self.reset()
        if event.kind == "wheel_up":
            return self.adjust(event.steps)
        if event.kind == "wheel_down":
            return self.adjust(-event.steps)
        if event.kind in {"down", "move"} and (event.kind == "down" or event.button == "left"):
            return self._point(event.x, event.y)
        return False

    def _point(self, x: int, y: int, *, vertical: bool = False, reverse_y: bool = False) -> bool:
        if vertical:
            span = max(1, self.bounds.height - 1)
            fraction = min(1.0, max(0.0, (y - self.bounds.y) / span))
            unit = 1.0 - fraction if reverse_y else fraction
        else:
            span = max(1, self.bounds.width - 1)
            unit = min(1.0, max(0.0, (x - self.bounds.x) / span))
        return self.set_value(self.spec.from_unit(unit))

    def _heading(self, canvas: Canvas, *, focused: bool, hovered: bool) -> str:
        role = "focused" if focused else "hover" if hovered else "heading"
        title = self.label[: self.bounds.width]
        canvas.text(self.bounds.x, self.bounds.y, title, role, max_width=self.bounds.width)
        return "focused" if focused else "accent"


class Fader(ParamWidget):
    """Horizontal or vertical continuous/discrete parameter fader."""

    def __init__(self, *args: object, orientation: str = "horizontal", **kwargs: object) -> None:
        if orientation not in {"horizontal", "vertical"}:
            raise ValueError("orientation must be 'horizontal' or 'vertical'")
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.orientation = orientation

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind in {"down", "move"} and self.orientation == "vertical" and (event.kind == "down" or event.button == "left"):
            return self._point(event.x, event.y, vertical=True, reverse_y=True)
        return super().handle_mouse(event)

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        value = f"{float(self.value):.2f}"
        if self.orientation == "horizontal":
            self._heading(canvas, focused=focused, hovered=hovered)
            if height > 1:
                canvas.text(x, y + height - 1, "-" * width, "muted")
                position = round(self.unit * max(0, width - 1))
                canvas.put(x + position, y + height - 1, "|", "focused" if focused else "accent")
            if height > 1 and width > len(value):
                canvas.text(x + width - len(value), y, value, "selected", max_width=len(value))
        else:
            role = "focused" if focused else "hover" if hovered else "heading"
            if width > len(value) + 1:
                canvas.fill(x, y, width, 1, role="background")
                canvas.text(x, y, self.label, role, max_width=width - len(value) - 1)
                canvas.text(x + width - len(value), y, value, "selected", max_width=len(value))
            else:
                self._heading(canvas, focused=focused, hovered=hovered)
            track_x = x + width // 2
            top = min(y + 1, y + height - 1)
            bottom = y + height - 1
            for row in range(top, bottom + 1):
                canvas.put(track_x, row, "|", "muted")
            position = bottom - round(self.unit * max(0, bottom - top))
            canvas.put(track_x, position, "#", "focused" if focused else "accent")


class Knob(ParamWidget):
    """Seven-position ASCII arc control, turned vertically or by keys/wheel."""

    _ARC = ("|", "/", "-", "\\", "_", ".", "o")

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind in {"down", "move"} and (event.kind == "down" or event.button == "left"):
            return self._point(event.x, event.y, vertical=True, reverse_y=True)
        return super().handle_mouse(event)

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        self._heading(canvas, focused=focused, hovered=hovered)
        if width >= 7 and height >= 2:
            index = min(6, max(0, round(self.unit * 6)))
            arc = ["/", "/", "-", "-", "\\", "\\", "|"]
            arc[index] = self._ARC[index]
            canvas.text(x + (width - 7) // 2, y + 1, "".join(arc), "focused" if focused else "accent")
        value = f"{float(self.value):.2f}"
        if height > 2:
            canvas.text(x + max(0, (width - len(value)) // 2), y + 2, value, "text", max_width=width)


class Toggle(ParamWidget):
    """Two-state parameter toggle; uses the parameter endpoints."""

    @property
    def is_on(self) -> bool:
        return self.unit >= 0.5

    def toggle(self) -> bool:
        return self.set_value(self.spec.maximum if not self.is_on else self.spec.minimum)

    def handle_key(self, key: str, data: str = "") -> bool:
        if key in {"left", "down", "right", "up", "enter", "space"}:
            return self.toggle()
        return super().handle_key(key, data)

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            return self.reset()
        if event.kind == "wheel_up":
            return self.set_value(self.spec.maximum)
        if event.kind == "wheel_down":
            return self.set_value(self.spec.minimum)
        if event.kind == "down" and event.button == "left":
            return self.toggle()
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        role = "focused" if focused else "selected" if self.is_on else "muted"
        state = "[ON]" if self.is_on else "[OFF]"
        canvas.text(self.bounds.x, self.bounds.y, f"{self.label} {state}", role, max_width=self.bounds.width)


class Choice(ParamWidget):
    """Discrete labelled choice bound to a choice `ParamSpec`."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        if self.spec.kind != "choice" or not self.spec.choices:
            raise ValueError("Choice requires a choice ParamSpec")

    def handle_key(self, key: str, data: str = "") -> bool:
        if key in {"left", "down"}:
            return self._cycle(-1)
        if key in {"right", "up", "enter"}:
            return self._cycle(1)
        if key == "pagedown":
            return self._cycle(-10)
        if key == "pageup":
            return self._cycle(10)
        return super().handle_key(key, data)

    def _cycle(self, steps: int) -> bool:
        count = len(self.spec.choices or ())
        if count < 1:
            return False
        return self.set_value((int(self.value) + steps) % count)

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            return self.reset()
        if event.kind == "wheel_up":
            return self._cycle(event.steps)
        if event.kind == "wheel_down":
            return self._cycle(-event.steps)
        if event.kind == "down" and event.button == "left":
            return self._cycle(1)
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        index = int(self.value)
        selected = self.spec.choices[index]
        role = "focused" if focused else "selected"
        canvas.text(self.bounds.x, self.bounds.y, f"{self.label}: < {selected} >", role, max_width=self.bounds.width)


class XYPad(Widget):
    """Two normalized parameters adjusted by pointer position and arrows."""

    def __init__(
        self,
        tag: str,
        bounds: Rect,
        x_spec: ParamSpec,
        y_spec: ParamSpec,
        x_value: object | None = None,
        y_value: object | None = None,
        *,
        label: str = "XY",
        on_change: ChangeCallback | None = None,
    ) -> None:
        super().__init__(tag, bounds, label=label)
        self.x_spec, self.y_spec = x_spec, y_spec
        self.on_change = on_change
        self.x_value = x_spec.validate_value(x_spec.default if x_value is None else x_value)
        self.y_value = y_spec.validate_value(y_spec.default if y_value is None else y_value)
        self.default_x, self.default_y = x_spec.default, y_spec.default

    def _set(self, x_value: object, y_value: object) -> bool:
        x_value = self.x_spec.validate_value(x_value)
        y_value = self.y_spec.validate_value(y_value)
        changed = False
        if x_value != self.x_value:
            self.x_value = x_value
            changed = True
            if self.on_change is not None:
                self.on_change(self.x_spec.key, x_value)
        if y_value != self.y_value:
            self.y_value = y_value
            changed = True
            if self.on_change is not None:
                self.on_change(self.y_spec.key, y_value)
        return changed

    def _at(self, x: int, y: int) -> bool:
        x_unit = min(1.0, max(0.0, (x - self.bounds.x) / max(1, self.bounds.width - 1)))
        y_unit = 1.0 - min(1.0, max(0.0, (y - self.bounds.y) / max(1, self.bounds.height - 1)))
        return self._set(self.x_spec.from_unit(x_unit), self.y_spec.from_unit(y_unit))

    def handle_key(self, key: str, data: str = "") -> bool:
        if key == "left":
            return self._set(self.x_spec.from_unit(max(0.0, self.x_spec.to_unit(self.x_value) - 0.01)), self.y_value)
        if key == "right":
            return self._set(self.x_spec.from_unit(min(1.0, self.x_spec.to_unit(self.x_value) + 0.01)), self.y_value)
        if key == "down":
            return self._set(self.x_value, self.y_spec.from_unit(max(0.0, self.y_spec.to_unit(self.y_value) - 0.01)))
        if key == "up":
            return self._set(self.x_value, self.y_spec.from_unit(min(1.0, self.y_spec.to_unit(self.y_value) + 0.01)))
        if key == "pagedown":
            return self._set(self.x_value, self.y_spec.from_unit(max(0.0, self.y_spec.to_unit(self.y_value) - 0.1)))
        if key == "pageup":
            return self._set(self.x_value, self.y_spec.from_unit(min(1.0, self.y_spec.to_unit(self.y_value) + 0.1)))
        if key == "home":
            return self._set(self.x_spec.minimum, self.y_spec.minimum)
        if key == "end":
            return self._set(self.x_spec.maximum, self.y_spec.maximum)
        if key == "delete":
            return self.reset()
        return False

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            return self.reset()
        if event.kind == "wheel_up":
            return self._set(self.x_spec.from_unit(min(1.0, self.x_spec.to_unit(self.x_value) + event.steps / 100.0)), self.y_value)
        if event.kind == "wheel_down":
            return self._set(self.x_spec.from_unit(max(0.0, self.x_spec.to_unit(self.x_value) - event.steps / 100.0)), self.y_value)
        if event.kind in {"down", "move"} and (event.kind == "down" or event.button == "left"):
            return self._at(event.x, event.y)
        return False

    def reset(self) -> bool:
        return self._set(self.default_x, self.default_y)

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        canvas.box(x, y, width, height, style="ascii", role="focused" if focused else "border")
        canvas.text(x + 2, y, self.label, "focused" if focused else "heading", max_width=max(0, width - 4))
        if width > 2 and height > 2:
            px = x + 1 + round(self.x_spec.to_unit(self.x_value) * max(0, width - 3))
            py = y + 1 + round((1.0 - self.y_spec.to_unit(self.y_value)) * max(0, height - 3))
            canvas.put(px, py, "+", "selected")


class Meter(Widget):
    """Read-only RMS meter with optional left/right peaks and stereo channel."""

    def __init__(
        self,
        tag: str,
        bounds: Rect,
        value: float = 0.0,
        *,
        label: str = "Meter",
        peak: float | None = None,
        right_value: float | None = None,
        right_peak: float | None = None,
    ) -> None:
        super().__init__(tag, bounds, label=label, focusable=True)
        self.set_level(value, peak=peak)
        self.right_value: float | None = None
        self.right_peak: float | None = None
        if right_value is not None:
            self.set_right_level(right_value, peak=right_peak)
        elif right_peak is not None:
            raise ValueError("right_peak requires right_value")

    def set_level(self, value: float, *, peak: float | None = None) -> None:
        for number in (value, peak):
            if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)):
                raise ValueError("meter values must be finite numbers")
        self.value = min(1.0, max(0.0, float(value)))
        self.peak = None if peak is None else min(1.0, max(0.0, float(peak)))

    def set_right_level(self, value: float, *, peak: float | None = None) -> None:
        for number in (value, peak):
            if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)):
                raise ValueError("meter values must be finite numbers")
        self.right_value = min(1.0, max(0.0, float(value)))
        self.right_peak = None if peak is None else min(1.0, max(0.0, float(peak)))

    def set_stereo_levels(
        self,
        left_rms: float,
        right_rms: float,
        *,
        left_peak: float | None = None,
        right_peak: float | None = None,
    ) -> None:
        """Update left/right RMS levels and optional peak holds."""
        self.set_level(left_rms, peak=left_peak)
        self.set_right_level(right_rms, peak=right_peak)

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        canvas.text(x, y, self.label, "heading", max_width=width)
        stereo = self.right_value is not None and height >= 3
        label_width = 2 if stereo else 0
        bar_width = max(0, width - label_width)
        levels = [(self.value, self.peak, "L " if stereo else "")]
        if stereo:
            levels.append((self.right_value or 0.0, self.right_peak, "R "))
        for index, (level, peak, prefix) in enumerate(levels):
            row = y + 1 + index
            if row >= y + height:
                break
            role = "meter_low" if level < 1 / 3 else "meter_mid" if level < 2 / 3 else "meter_high"
            canvas.text(x, row, prefix, "muted")
            filled = round(level * bar_width)
            canvas.text(x + label_width, row, "#" * filled + "-" * (bar_width - filled), role, max_width=bar_width)
            if peak is not None and bar_width:
                position = min(bar_width - 1, round(peak * max(0, bar_width - 1)))
                canvas.put(x + label_width + position, row, "|", "meter_high")


class Button(Widget):
    """Focusable action button with optional right-click action."""

    def __init__(self, tag: str, bounds: Rect, label: str, on_press: Callable[[], object] | None = None, *, on_right_click: Callable[[], object] | None = None) -> None:
        super().__init__(tag, bounds, label=label)
        self.on_press = on_press
        self.on_right_click = on_right_click
        self._armed = False

    def activate(self) -> bool:
        if self.on_press is None:
            return False
        self.on_press()
        return True

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            if self.on_right_click is None:
                return False
            self.on_right_click()
            return True
        if event.kind == "down" and event.button == "left":
            self._armed = True
            return True
        if event.kind == "move" and event.button == "left" and self._armed:
            return True
        if event.kind == "up" and event.button == "left":
            activate = self._armed and self.bounds.contains(event.x, event.y)
            self._armed = False
            return self.activate() if activate else True
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        role = "pressed" if self._armed else "focused" if focused else "hover" if hovered else "accent"
        text = f"[ {self.label} ]"
        if len(text) > self.bounds.width:
            text = text[: self.bounds.width]
        canvas.text(self.bounds.x + max(0, (self.bounds.width - len(text)) // 2), self.bounds.y, text, role, max_width=self.bounds.width)


class TextField(Widget):
    """Single-line preset/name editor with cursor and bounded visible text."""

    def __init__(self, tag: str, bounds: Rect, value: str = "", *, label: str = "Name", default: str = "", on_change: Callable[[str], object] | None = None, on_submit: Callable[[str], object] | None = None) -> None:
        super().__init__(tag, bounds, label=label)
        if not isinstance(value, str) or not isinstance(default, str):
            raise TypeError("text field values must be strings")
        self.value = value
        self.default = default
        self.cursor = len(value)
        self.on_change = on_change
        self.on_submit = on_submit

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change(self.value)

    def reset(self) -> bool:
        if self.value == self.default:
            return False
        self.value = self.default
        self.cursor = len(self.value)
        self._changed()
        return True

    def handle_key(self, key: str, data: str = "") -> bool:
        if key == "left":
            self.cursor = max(0, self.cursor - 1)
            return True
        if key == "right":
            self.cursor = min(len(self.value), self.cursor + 1)
            return True
        if key == "home":
            self.cursor = 0
            return True
        if key == "end":
            self.cursor = len(self.value)
            return True
        if key == "backspace":
            if self.cursor:
                self.value = self.value[: self.cursor - 1] + self.value[self.cursor :]
                self.cursor -= 1
                self._changed()
            return True
        if key == "delete":
            return self.reset()
        if key == "enter":
            if self.on_submit is not None:
                self.on_submit(self.value)
                return True
            return False
        if data and all(char.isprintable() and len(char) == 1 for char in data):
            self.value = self.value[: self.cursor] + data + self.value[self.cursor :]
            self.cursor += len(data)
            self._changed()
            return True
        return False

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            return self.reset()
        if event.kind == "down" and event.button == "left":
            self.cursor = min(len(self.value), max(0, event.x - self.bounds.x - len(self.label) - 2))
            return True
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        role = "focused" if focused else "text"
        prefix = f"{self.label}: "
        available = max(0, self.bounds.width - len(prefix))
        start = max(0, min(self.cursor - max(0, available - 1), len(self.value) - available)) if available else 0
        visible = self.value[start : start + available] if available else ""
        canvas.text(self.bounds.x, self.bounds.y, prefix + visible, role, max_width=self.bounds.width)
        if focused and available:
            cursor_cell = min(available - 1, max(0, self.cursor - start))
            canvas.put(self.bounds.x + len(prefix) + cursor_cell, self.bounds.y, "_", "focused")


class ListBox(Widget):
    """Focusable list with bounded viewport, keyboard selection and activation."""

    def __init__(self, tag: str, bounds: Rect, items: Iterable[str], *, selected: int = 0, label: str = "", on_change: Callable[[int, str], object] | None = None, on_activate: Callable[[int, str], object] | None = None) -> None:
        super().__init__(tag, bounds, label=label)
        self.items = tuple(str(item) for item in items)
        if not self.items:
            raise ValueError("ListBox requires at least one item")
        self.on_change = on_change
        self.on_activate = on_activate
        self.selected = min(len(self.items) - 1, max(0, int(selected)))

    def _select(self, index: int) -> bool:
        index = min(len(self.items) - 1, max(0, index))
        if index == self.selected:
            return False
        self.selected = index
        if self.on_change is not None:
            self.on_change(index, self.items[index])
        return True

    def handle_key(self, key: str, data: str = "") -> bool:
        if key in {"up", "left"}:
            return self._select(self.selected - 1)
        if key in {"down", "right"}:
            return self._select(self.selected + 1)
        if key == "home":
            return self._select(0)
        if key == "end":
            return self._select(len(self.items) - 1)
        if key == "pageup":
            return self._select(self.selected + 10)
        if key == "pagedown":
            return self._select(self.selected - 10)
        if key in {"enter", "space"}:
            if self.on_activate is not None:
                self.on_activate(self.selected, self.items[self.selected])
                return True
            return False
        if key == "delete":
            return self._select(0)
        return False

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            return self._select(0)
        if event.kind in {"wheel_up", "wheel_down"}:
            return self._select(self.selected + (event.steps if event.kind == "wheel_down" else -event.steps))
        if event.kind == "down" and event.button == "left":
            row = event.y - self.bounds.y - (1 if self.label else 0)
            return self._select(row)
        if event.kind == "up" and event.button == "left" and self.bounds.contains(event.x, event.y) and self.on_activate is not None:
            self.on_activate(self.selected, self.items[self.selected])
            return True
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width, height = self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height
        offset = 1 if self.label and height > 0 else 0
        if self.label:
            canvas.text(x, y, self.label, "focused" if focused else "heading", max_width=width)
        visible_rows = max(0, height - offset)
        start = min(max(0, self.selected - visible_rows + 1), max(0, len(self.items) - visible_rows))
        for row in range(visible_rows):
            index = start + row
            if index >= len(self.items):
                break
            selected = index == self.selected
            prefix = "> " if selected else "  "
            canvas.text(x, y + offset + row, prefix + self.items[index], "selected" if selected else "text", max_width=width)


class Tabs(Widget):
    """Focusable horizontal tab selector."""

    def __init__(self, tag: str, bounds: Rect, items: Sequence[str], *, selected: int = 0, on_change: Callable[[int, str], object] | None = None) -> None:
        super().__init__(tag, bounds, label="")
        if not items:
            raise ValueError("Tabs requires at least one item")
        self.items = tuple(str(item) for item in items)
        self.selected = min(len(self.items) - 1, max(0, int(selected)))
        self.on_change = on_change

    def _select(self, index: int) -> bool:
        index = min(len(self.items) - 1, max(0, index))
        if index == self.selected:
            return False
        self.selected = index
        if self.on_change is not None:
            self.on_change(index, self.items[index])
        return True

    def activate(self) -> bool:
        return self._select((self.selected + 1) % len(self.items))

    def handle_key(self, key: str, data: str = "") -> bool:
        if key in {"left", "down"}:
            return self._select(self.selected - 1)
        if key in {"right", "up", "enter"}:
            return self.activate()
        if key == "home":
            return self._select(0)
        if key == "end":
            return self._select(len(self.items) - 1)
        if key == "pageup":
            return self._select(self.selected + 10)
        if key == "pagedown":
            return self._select(self.selected - 10)
        if key == "delete":
            return self._select(0)
        return False

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "right":
            return self._select(0)
        if event.kind == "wheel_up":
            return self._select(self.selected - event.steps)
        if event.kind == "wheel_down":
            return self._select(self.selected + event.steps)
        if event.kind == "down" and event.button == "left":
            index = min(len(self.items) - 1, max(0, (event.x - self.bounds.x) * len(self.items) // self.bounds.width))
            return self._select(index)
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        x, y, width = self.bounds.x, self.bounds.y, self.bounds.width
        total = max(1, len(self.items))
        left = 0
        for index, item in enumerate(self.items):
            right = width * (index + 1) // total
            segment = right - left
            text = f"[{item}]" if index == self.selected else item
            role = "focused" if index == self.selected and focused else "selected" if index == self.selected else "text"
            canvas.text(x + left, y, text, role, max_width=segment)
            left = right


class FocusRing:
    """Stable Tab/Shift+Tab order and keyboard dispatch for reusable widgets."""

    def __init__(self, widgets: Iterable[Widget] = ()) -> None:
        self.widgets: list[Widget] = []
        self._index = -1
        for widget in widgets:
            self.add(widget)

    @property
    def focusables(self) -> tuple[Widget, ...]:
        return tuple(widget for widget in self.widgets if widget.focusable)

    @property
    def focused(self) -> Widget | None:
        focusables = self.focusables
        if not focusables:
            return None
        return focusables[self._index % len(focusables)] if self._index >= 0 else None

    @property
    def focused_tag(self) -> str | None:
        return self.focused.tag if self.focused is not None else None

    def add(self, widget: Widget) -> None:
        if not isinstance(widget, Widget):
            raise TypeError("focus ring entries must be Widget instances")
        if any(existing.tag == widget.tag for existing in self.widgets):
            raise ValueError(f"duplicate widget tag: {widget.tag}")
        self.widgets.append(widget)

    def focus(self, tag: str) -> bool:
        for index, widget in enumerate(self.focusables):
            if widget.tag == tag:
                self._index = index
                return True
        return False

    def move(self, direction: int = 1) -> bool:
        focusables = self.focusables
        if not focusables:
            self._index = -1
            return False
        if self._index < 0:
            self._index = 0 if direction >= 0 else len(focusables) - 1
            return True
        self._index = (self._index + (1 if direction >= 0 else -1)) % len(focusables)
        return True

    def handle_key(self, key: str, data: str = "") -> bool:
        if key == "tab":
            return self.move(1)
        if key == "s-tab":
            return self.move(-1)
        widget = self.focused
        return widget.handle_key(key, data) if widget is not None else False

    def handle_mouse(self, tag: str, event: MouseInput) -> bool:
        for widget in self.widgets:
            if widget.tag == tag:
                if widget.focusable:
                    self.focus(tag)
                return widget.handle_mouse(event)
        return False

    def draw(self, canvas: Canvas, *, hovered_tag: str | None = None) -> None:
        focused = self.focused_tag
        for widget in self.widgets:
            widget.draw(canvas, focused=widget.tag == focused, hovered=widget.tag == hovered_tag)
