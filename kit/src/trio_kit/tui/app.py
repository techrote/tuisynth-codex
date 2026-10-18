"""prompt_toolkit full-screen application for a cell Canvas."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseButton, MouseEventType
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style as PromptStyle

from trio_kit.skins import Skin, mono_skin
from trio_kit.tui.canvas import Canvas, HitRegion
from trio_kit.tui.mouse import MouseInput, MouseRouter
from trio_kit.tui.widgets import FocusRing
from trio_kit.userdata import get_user_data_dir


@dataclass(frozen=True, slots=True)
class UIEvent:
    """Observable input evidence from the UI boundary, independent of the engine."""

    kind: str
    tag: str | None = None
    x: int | None = None
    y: int | None = None
    key: str | None = None


class CanvasApp:
    """Render a cell canvas in prompt_toolkit's full-screen application.

    `draw` runs only when an invalidation is rendered or terminal geometry
    changes. It may draw directly on the provided canvas. Focus-ring widgets
    are drawn afterward and contribute hit rectangles to the same frame.
    """

    def __init__(
        self,
        draw: Callable[[Canvas], object] | None = None,
        *,
        widgets: FocusRing | None = None,
        skin: Skin | None = None,
        output: Output | None = None,
        input: Any | None = None,
        quit_callback: Callable[[], object] | None = None,
        on_key: Callable[[str, str], object] | None = None,
        error_log: str | Path | None = None,
        animated: bool = False,
        ascii_only: bool = False,
    ) -> None:
        self.draw_callback = draw
        self.widgets = widgets or FocusRing()
        if not isinstance(ascii_only, bool):
            raise ValueError("ascii_only must be a boolean")
        self.skin = mono_skin() if skin is None or "NO_COLOR" in os.environ else skin
        self.ascii_only = ascii_only or self.skin.id == "mono"
        self.router = MouseRouter()
        self.quit_callback = quit_callback
        self.on_key_callback = on_key
        self.error_log = Path(error_log) if error_log is not None else None
        self.animated = bool(animated)
        self._provided_input = input
        self._provided_output = output
        self.canvas: Canvas | None = None
        self.error: Exception | None = None
        self.frames: list[str] = []
        self.event_log: list[UIEvent] = []
        self.input_count = 0
        self._dirty = True
        self._last_invalidation = 0.0
        self._scheduled = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending_handle: asyncio.TimerHandle | None = None

        self.control = FormattedTextControl(self._formatted_text, focusable=True, show_cursor=False)
        self.key_bindings = self._create_key_bindings()
        self.application: Application[None] | None = None
        if input is not None or output is not None:
            self._build_application()

    def _build_application(self) -> Application[None]:
        if self.application is not None:
            return self.application
        self.application = Application(
            layout=Layout(Window(self.control, wrap_lines=False, always_hide_cursor=True, style="class:background")),
            style=self._prompt_style(),
            key_bindings=self.key_bindings,
            full_screen=True,
            mouse_support=True,
            input=self._provided_input,
            output=self._provided_output,
            min_redraw_interval=1 / 30,
            max_render_postpone_time=1 / 30,
        )
        return self.application

    def attach_io(self, input: Any, output: Output) -> None:
        """Set input/output before running, used by the device-free test driver."""
        if self.application is not None and self.application.is_running:
            raise ValueError("cannot replace input/output while the CanvasApp is running")
        self._provided_input = input
        self._provided_output = output
        if self.application is not None:
            self.application.input = input
            self.application.output = output
            self.application.renderer.output = output

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def _prompt_style(self) -> PromptStyle:
        styles = {role: self.skin.style(role).as_prompt_toolkit() for role in self.skin.styles}
        styles.setdefault("background", self.skin.style("background").as_prompt_toolkit())
        return PromptStyle.from_dict(styles)

    def _create_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("c-q", eager=True)
        def _quit(event: Any) -> None:
            self.event_log.append(UIEvent("quit", key="c-q"))
            self.input_count += 1
            try:
                if self.quit_callback is not None:
                    self.quit_callback()
            finally:
                event.app.exit(result=None)

        @bindings.add(Keys.Any)
        def _dispatch(event: Any) -> None:
            key = self._normalize_key(event.key_sequence[-1].key)
            data = event.data if isinstance(event.data, str) else ""
            if key == "any" and data == " ":
                key, data = "space", ""
            self.event_log.append(UIEvent("key", key=key))
            self.input_count += 1
            handled = self.widgets.handle_key(key, data)
            if not handled and self.on_key_callback is not None:
                result = self.on_key_callback(key, data)
                handled = result is not False
            if handled or key:
                self.invalidate()

        return bindings

    @staticmethod
    def _normalize_key(key: object) -> str:
        value = getattr(key, "value", key)
        value = str(value)
        if value.startswith("Keys."):
            value = value[5:]
        lowered = value.lower()
        aliases = {
            "s-tab": "s-tab",
            "shift-tab": "s-tab",
            "pageup": "pageup",
            "pagedown": "pagedown",
            "escape": "escape",
            "enter": "enter",
            "backspace": "backspace",
            "delete": "delete",
            "space": "space",
            "any": "any",
            "controlq": "c-q",
            "c-i": "tab",
            "backtab": "s-tab",
            "c-h": "backspace",
        }
        return aliases.get(lowered, lowered.replace("_", "-"))

    def _size(self) -> tuple[int, int]:
        output = self.application.output if self.application is not None else self._provided_output
        if output is None:
            return 80, 24
        size = output.get_size()
        return max(1, size.columns), max(1, size.rows)

    def _ensure_frame(self) -> None:
        columns, rows = self._size()
        if self.canvas is not None and (self.canvas.width, self.canvas.height) != (columns, rows):
            self._dirty = True
        if not self._dirty:
            return
        canvas = Canvas(columns, rows, role="background", ascii_only=self.ascii_only)
        try:
            if self.draw_callback is not None:
                self.draw_callback(canvas)
            self.error = None
        except Exception as error:
            self.error = error
            self._log_render_error(error)
            canvas = self._error_canvas(columns, rows, error)
        if self.error is None:
            self.widgets.draw(canvas, hovered_tag=self.router.hovered_tag)
        self.canvas = canvas
        self.router.update(canvas.hit_map)
        self.frames.append(canvas.snapshot())
        del self.frames[:-64]
        self._dirty = False

    def _error_canvas(self, columns: int, rows: int, error: Exception) -> Canvas:
        canvas = Canvas(columns, rows, role="background", ascii_only=True)
        width = min(max(12, columns - 2), 64)
        height = min(max(5, rows - 2), 7)
        x = max(0, (columns - width) // 2)
        y = max(0, (rows - height) // 2)
        canvas.box(x, y, width, height, style="ascii", role="error")
        canvas.text(x + 2, y + 1, "Render error", "error", max_width=max(0, width - 4))
        message = str(error).replace("\n", " ") or type(error).__name__
        canvas.text(x + 2, y + 2, message, "text", max_width=max(0, width - 4))
        if height > 4:
            canvas.text(x + 2, y + height - 2, "F1 help  Ctrl+Q quit", "muted", max_width=max(0, width - 4))
        return canvas

    def _log_render_error(self, error: Exception) -> None:
        path = self.error_log or (get_user_data_dir("kit") / "tui-errors.log")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(f"{type(error).__name__}: {error}\n")
        except OSError:
            # A read-only home directory must not take down the terminal UI.
            pass

    def _formatted_text(self) -> list[tuple[str, str, Callable[[Any], None]]]:
        self._ensure_frame()
        assert self.canvas is not None
        output: list[tuple[str, str, Callable[[Any], None]]] = []
        for row_index, row in enumerate(self.canvas.cells):
            for cell in row:
                output.append((f"class:{cell.role}", cell.char, self._on_mouse))
            if row_index < len(self.canvas.cells) - 1:
                output.append(("", "\n", self._on_mouse))
        return output

    @staticmethod
    def _convert_mouse(event: Any) -> MouseInput | None:
        point = event.position
        x, y = point.x, point.y
        button = event.button
        button_name = {
            MouseButton.LEFT: "left",
            MouseButton.MIDDLE: "middle",
            MouseButton.RIGHT: "right",
        }.get(button, "none")
        event_type = event.event_type
        if event_type == MouseEventType.SCROLL_UP:
            kind = "wheel_up"
        elif event_type == MouseEventType.SCROLL_DOWN:
            kind = "wheel_down"
        elif event_type == MouseEventType.MOUSE_DOWN and button == MouseButton.RIGHT:
            kind = "right"
        elif event_type == MouseEventType.MOUSE_DOWN:
            kind = "down"
        elif event_type == MouseEventType.MOUSE_UP:
            kind = "up"
        elif event_type == MouseEventType.MOUSE_MOVE:
            kind = "move"
        else:
            return None
        modifiers = event.modifiers
        return MouseInput(
            x=x,
            y=y,
            kind=kind,
            button=button_name,
            control=any(getattr(modifier, "value", modifier) == "CONTROL" for modifier in modifiers),
            shift=any(getattr(modifier, "value", modifier) == "SHIFT" for modifier in modifiers),
            alt=any(getattr(modifier, "value", modifier) == "ALT" for modifier in modifiers),
        )

    def _on_mouse(self, event: Any) -> Any:
        mouse = self._convert_mouse(event)
        if mouse is None:
            return
        if mouse.shift and mouse.button == "left" and mouse.kind in {"down", "move", "up"}:
            # Shift-drag belongs to the terminal's text-selection behavior.
            self.input_count += 1
            return NotImplemented
        previous_hover = self.router.hovered_tag

        def dispatch(target: HitRegion, current: MouseInput) -> bool:
            self.event_log.append(UIEvent(current.kind, target.tag, current.x, current.y))
            if current.kind == "down" and target.payload is not None and self.widgets.focus(target.tag):
                pass
            elif current.kind == "right" and target.payload is not None and self.widgets.focus(target.tag):
                pass
            return self.widgets.handle_mouse(target.tag, current)

        changed = self.router.route(mouse, dispatch)
        self.input_count += 1
        if changed or previous_hover != self.router.hovered_tag or mouse.kind in {"up", "down", "right", "wheel_up", "wheel_down"}:
            self.invalidate()

    def invalidate(self, *, animated: bool | None = None) -> None:
        """Mark state dirty, coalescing updates at 4 fps idle or 30 fps animated."""
        self._dirty = True
        if self.application is None or not self.application.is_running:
            return
        now = time.monotonic()
        interval = 1 / 30 if (self.animated if animated is None else animated) else 0.25
        due = self._last_invalidation + interval
        if now >= due:
            self._last_invalidation = now
            self._scheduled = False
            if self._pending_handle is not None:
                self._pending_handle.cancel()
                self._pending_handle = None
            self.application.invalidate()
            return
        if self._scheduled:
            return
        self._scheduled = True
        delay = max(0.0, due - now)

        def flush() -> None:
            self._scheduled = False
            self._pending_handle = None
            self._last_invalidation = time.monotonic()
            if self.application is not None and self.application.is_running:
                self.application.invalidate()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
        if loop is not None and loop.is_running():
            if loop is self._loop:
                self._pending_handle = loop.call_later(delay, flush)
            else:
                loop.call_soon_threadsafe(lambda: setattr(self, "_pending_handle", loop.call_later(delay, flush)))

    async def run_async(self) -> None:
        self._loop = asyncio.get_running_loop()
        await self._build_application().run_async()

    def run(self) -> None:
        self._build_application().run()

    def quit(self) -> None:
        if self.application is not None and self.application.is_running:
            self.application.exit(result=None)

    def screen_text(self) -> str:
        self._ensure_frame()
        return self.canvas.snapshot() if self.canvas is not None else ""

    def events(self) -> tuple[UIEvent, ...]:
        return tuple(self.event_log)
