"""Device-free prompt_toolkit driver that sends literal terminal input bytes."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from trio_kit.tui.app import CanvasApp
from trio_kit.tui.canvas import Canvas
from trio_kit.tui.widgets import FocusRing


class _SizedDummyOutput(DummyOutput):
    def __init__(self, columns: int, rows: int) -> None:
        self.columns = columns
        self.rows = rows

    def get_size(self) -> Size:
        return Size(rows=self.rows, columns=self.columns)


class HeadlessApp:
    """Run the production `CanvasApp` with pipe input and a sized DummyOutput.

    Public coordinates are zero-based. `click`, `drag`, `release`, and `wheel`
    encode real xterm SGR sequences, whose terminal coordinates are 1-based.
    """

    _SPECIAL_KEYS = {
        "enter": "\r",
        "tab": "\t",
        "s-tab": "\x1b[Z",
        "escape": "\x1b",
        "backspace": "\x7f",
        "delete": "\x1b[3~",
        "left": "\x1b[D",
        "right": "\x1b[C",
        "up": "\x1b[A",
        "down": "\x1b[B",
        "pageup": "\x1b[5~",
        "pagedown": "\x1b[6~",
        "home": "\x1b[H",
        "end": "\x1b[F",
        "c-q": "\x11",
        "c-p": "\x10",
        "c-l": "\x0c",
        "c-z": "\x1a",
        "c-y": "\x19",
        "f1": "\x1bOP",
        "f2": "\x1bOQ",
        "f3": "\x1bOR",
        "f4": "\x1bOS",
        "f5": "\x1b[15~",
        "f6": "\x1b[17~",
        "s-f6": "\x1b[1;2;17~",
        "f7": "\x1b[18~",
        "f8": "\x1b[19~",
        "f9": "\x1b[20~",
    }

    def __init__(
        self,
        draw: Callable[[Canvas], object] | None = None,
        *,
        size: tuple[int, int] = (80, 24),
        widgets: FocusRing | None = None,
        app: CanvasApp | None = None,
        event_source: object | None = None,
        error_log: str | None = None,
    ) -> None:
        columns, rows = size
        if isinstance(columns, bool) or isinstance(rows, bool) or columns < 1 or rows < 1:
            raise ValueError("size must contain positive (columns, rows)")
        self._pipe_context = create_pipe_input()
        self.input = self._pipe_context.__enter__()
        self.output = _SizedDummyOutput(columns, rows)
        self.app = app or CanvasApp(draw, widgets=widgets, error_log=error_log)
        self.app.attach_io(self.input, self.output)
        self._event_source = event_source
        self._thread = threading.Thread(target=self._run, name="trio-headless-tui", daemon=True)
        self._done = threading.Event()
        self._started = False
        self._closed = False

    def _run(self) -> None:
        import asyncio

        async def runner() -> None:
            await self.app.run_async()

        try:
            asyncio.run(runner())
        finally:
            self._done.set()

    def start(self, timeout: float = 3.0) -> HeadlessApp:
        if not self._started:
            self._thread.start()
            self._started = True
        deadline = time.monotonic() + timeout
        while self.app.frame_count == 0 and time.monotonic() < deadline and not self._done.is_set():
            time.sleep(0.005)
        if self.app.frame_count == 0:
            raise TimeoutError("headless TUI did not render its first frame")
        return self

    def _send(self, data: bytes, *, events: int = 1, timeout: float = 2.0) -> None:
        self.start()
        before = self.app.input_count
        self.input.send_bytes(data)
        deadline = time.monotonic() + timeout
        target = before + events
        while self.app.input_count < target and time.monotonic() < deadline and not self._done.is_set():
            time.sleep(0.002)
        if self.app.input_count < target:
            raise TimeoutError(f"headless TUI processed {self.app.input_count - before} of {events} expected input events")

    def send_keys(self, text: str) -> None:
        """Send text through the VT100 parser and wait for each key event."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        expected = sum(1 for char in text if char not in "\x1b")
        if text:
            self._send(text.encode("utf-8"), events=max(1, expected))

    def press(self, key: str) -> None:
        """Send a named navigation or control key as a terminal byte sequence."""
        try:
            data = self._SPECIAL_KEYS[key.lower()]
        except KeyError as error:
            raise ValueError(f"unsupported key: {key}") from error
        events = 1 if key.lower() != "escape" else 1
        self._send(data.encode("utf-8"), events=events)

    @staticmethod
    def _coord(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative zero-based cell coordinate")
        return value + 1

    @classmethod
    def _sgr(cls, code: int, x: int, y: int, ending: str = "M") -> bytes:
        return f"\x1b[<{code};{cls._coord(x, 'x')};{cls._coord(y, 'y')}{ending}".encode("ascii")

    def click(self, x: int, y: int, button: str = "left", *, control: bool = False, shift: bool = False, alt: bool = False) -> None:
        buttons = {"left": 0, "middle": 1, "right": 2}
        if button not in buttons:
            raise ValueError("button must be left, middle, or right")
        modifiers = (4 if shift else 0) + (8 if alt else 0) + (16 if control else 0)
        code = buttons[button] + modifiers
        release_code = buttons[button] + modifiers
        self._send(self._sgr(code, x, y) + self._sgr(release_code, x, y, "m"), events=2)

    def drag(self, path: Iterable[tuple[int, int]], *, shift: bool = False, control: bool = False, alt: bool = False) -> None:
        points = tuple(path)
        if not points:
            raise ValueError("drag path must contain at least one point")
        modifiers = (4 if shift else 0) + (8 if alt else 0) + (16 if control else 0)
        chunks = [self._sgr(modifiers, *points[0])]
        chunks.extend(self._sgr(32 + modifiers, *point) for point in points[1:])
        chunks.append(self._sgr(modifiers, *points[-1], ending="m"))
        self._send(b"".join(chunks), events=len(points) + 1)

    def release(self, x: int, y: int, button: str = "left") -> None:
        buttons = {"left": 0, "middle": 1, "right": 2}
        if button not in buttons:
            raise ValueError("button must be left, middle, or right")
        self._send(self._sgr(buttons[button], x, y, "m"), events=1)

    def wheel(self, x: int, y: int, direction: str = "up", *, control: bool = False) -> None:
        if direction not in {"up", "down"}:
            raise ValueError("direction must be 'up' or 'down'")
        code = 64 if direction == "up" else 65
        if control:
            code += 16
        self._send(self._sgr(code, x, y), events=1)

    def resize(self, columns: int, rows: int, timeout: float = 2.0) -> None:
        """Change the virtual terminal dimensions and wait for a new frame."""
        if isinstance(columns, bool) or isinstance(rows, bool) or columns < 1 or rows < 1:
            raise ValueError("terminal dimensions must be positive integers")
        self.start()
        before = self.app.frame_count
        self.output.columns, self.output.rows = columns, rows
        self.app.invalidate()
        deadline = time.monotonic() + timeout
        while self.app.frame_count <= before and time.monotonic() < deadline and not self._done.is_set():
            time.sleep(0.005)
        if self.app.frame_count <= before:
            raise TimeoutError("headless TUI did not render after resize")

    def screen_text(self) -> str:
        return self.app.screen_text()

    def frames(self) -> tuple[str, ...]:
        return tuple(self.app.frames)

    def events(self) -> tuple[object, ...]:
        """Return fake-engine evidence when supplied, otherwise UI event evidence."""
        source = self._event_source
        if source is None:
            return self.app.events()
        events = getattr(source, "events", None)
        if callable(events):
            return tuple(events())
        if events is not None:
            return tuple(events)
        if callable(source):
            return tuple(source())
        raise TypeError("event_source must expose events or be callable")

    def stop(self, timeout: float = 3.0) -> None:
        if self._closed:
            return
        if self._started and not self._done.is_set():
            try:
                self.press("c-q")
            except (OSError, TimeoutError, ValueError):
                self.app.quit()
            self._thread.join(timeout)
        self._pipe_context.__exit__(None, None, None)
        self._closed = True

    def __enter__(self) -> HeadlessApp:
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()
