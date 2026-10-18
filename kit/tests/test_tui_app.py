from pathlib import Path
from threading import Event, Thread

import pytest

from trio_kit.events import ParamSet
from trio_kit.params import ParamSpec
from trio_kit.tui.app import CanvasApp
from trio_kit.tui.canvas import Canvas, Rect
from trio_kit.tui.testing import HeadlessApp
from trio_kit.tui.widgets import Button, Fader, FocusRing
from trio_kit.skins import load_skin


class FakeEventQueue:
    def __init__(self) -> None:
        self._events: list[ParamSet] = []

    def push(self, event: ParamSet) -> None:
        self._events.append(event)

    def events(self) -> tuple[ParamSet, ...]:
        return tuple(self._events)


def test_actual_sgr_clicks_use_zero_based_cell_hit_maps(tmp_path: Path) -> None:
    hits: list[str] = []
    buttons = [
        Button("one", Rect(1, 1, 5, 2), "One", lambda: hits.append("one")),
        Button("two", Rect(8, 1, 5, 2), "Two", lambda: hits.append("two")),
        Button("three", Rect(15, 1, 6, 2), "Three", lambda: hits.append("three")),
    ]
    with HeadlessApp(size=(24, 6), widgets=FocusRing(buttons), error_log=str(tmp_path / "errors.log")) as app:
        app.click(2, 1)
        app.click(9, 2)
        app.click(18, 1)
        assert hits == ["one", "two", "three"]
        events = app.events()
        assert [(event.kind, event.tag, event.x, event.y) for event in events] == [
            ("down", "one", 2, 1), ("up", "one", 2, 1),
            ("down", "two", 9, 2), ("up", "two", 9, 2),
            ("down", "three", 18, 1), ("up", "three", 18, 1),
        ]


def test_shift_mouse_selection_is_left_to_terminal(tmp_path: Path) -> None:
    hits: list[str] = []
    button = Button("select", Rect(2, 2, 10, 1), "Select", lambda: hits.append("clicked"))
    with HeadlessApp(size=(20, 6), widgets=FocusRing((button,)), error_log=str(tmp_path / "errors.log")) as app:
        app.click(4, 2, shift=True)
        assert hits == []
        assert app.app.router.captured_tag is None


def test_button_drag_outside_does_not_activate_after_captured_release(tmp_path: Path) -> None:
    hits: list[str] = []
    button = Button("action", Rect(2, 2, 8, 1), "Run", lambda: hits.append("run"))
    with HeadlessApp(size=(20, 7), widgets=FocusRing((button,)), error_log=str(tmp_path / "errors.log")) as app:
        app.drag(((3, 2), (15, 5)))
        assert hits == []
        assert app.app.router.captured_tag is None
        app.click(3, 2)
        assert hits == ["run"]


def test_sgr_drag_capture_wheel_ctrl_and_right_reset_feed_fake_queue(tmp_path: Path) -> None:
    queue = FakeEventQueue()
    spec = ParamSpec("amp.level", "Level", "", 0, 100, 40)
    fader = Fader("level", Rect(2, 2, 10, 3), spec, on_change=lambda key, value: queue.push(ParamSet(key, value)))
    ring = FocusRing((fader,))
    with HeadlessApp(size=(22, 8), widgets=ring, event_source=queue, error_log=str(tmp_path / "errors.log")) as app:
        app.drag(((2, 3), (8, 3), (15, 3)))
        drag_values = [event.value for event in app.events()]
        assert drag_values == sorted(drag_values)
        assert fader.value == 100
        assert app.app.router.captured_tag is None

        app.wheel(4, 3, "down", control=True)
        assert fader.value == 90
        app.click(4, 3, button="right")
        assert fader.value == 40
        assert all(isinstance(event, ParamSet) and event.key == "amp.level" for event in app.events())


def test_real_pipe_keys_match_widget_keyboard_path(tmp_path: Path) -> None:
    fader = Fader("level", Rect(1, 1, 10, 3), ParamSpec("amp.level", "Level", "", 0, 100, 50))
    ring = FocusRing((fader,))
    with HeadlessApp(size=(20, 6), widgets=ring, error_log=str(tmp_path / "errors.log")) as app:
        app.press("tab")
        app.press("right")
        assert ring.focused_tag == "level"
        assert fader.value == 51
        app.press("delete")
        assert fader.value == 50


def test_headless_key_press_waits_for_handler_completion(tmp_path: Path) -> None:
    callback_started = Event()
    callback_release = Event()
    press_returned = Event()
    press_errors: list[BaseException] = []

    def on_key(key: str, data: str) -> bool:
        del data
        if key == "delete":
            callback_started.set()
            if not callback_release.wait(2):
                raise TimeoutError("test did not release the key callback")
            return True
        return False

    app = CanvasApp(on_key=on_key)
    with HeadlessApp(app=app, size=(20, 6), error_log=str(tmp_path / "errors.log")) as headless:
        def send_key() -> None:
            try:
                headless.press("delete")
            except BaseException as error:
                press_errors.append(error)
            finally:
                press_returned.set()

        sender = Thread(target=send_key, daemon=True)
        sender.start()
        try:
            assert callback_started.wait(1)
            assert not press_returned.wait(0.05), "headless press returned before its handler finished"
        finally:
            callback_release.set()
            sender.join(timeout=1)
        assert not sender.is_alive()
        assert press_returned.is_set()
        assert not press_errors


def test_headless_quit_press_waits_for_callback_completion(tmp_path: Path) -> None:
    callback_started = Event()
    callback_release = Event()
    press_returned = Event()
    press_errors: list[BaseException] = []

    def on_quit() -> None:
        callback_started.set()
        if not callback_release.wait(2):
            raise TimeoutError("test did not release the quit callback")

    app = CanvasApp(quit_callback=on_quit)
    with HeadlessApp(app=app, size=(20, 6), error_log=str(tmp_path / "errors.log")) as headless:
        def send_key() -> None:
            try:
                headless.press("c-q")
            except BaseException as error:
                press_errors.append(error)
            finally:
                press_returned.set()

        sender = Thread(target=send_key, daemon=True)
        sender.start()
        try:
            assert callback_started.wait(1)
            assert not press_returned.wait(0.05), "headless quit returned before its callback finished"
        finally:
            callback_release.set()
            sender.join(timeout=1)
        assert not sender.is_alive()
        assert press_returned.is_set()
        assert not press_errors


def test_resize_recreates_canvas_at_new_terminal_geometry(tmp_path: Path) -> None:
    draws: list[tuple[int, int]] = []

    def draw(canvas: Canvas) -> None:
        draws.append((canvas.width, canvas.height))
        canvas.text(0, 0, f"{canvas.width}x{canvas.height}")

    with HeadlessApp(draw, size=(20, 6), error_log=str(tmp_path / "errors.log")) as app:
        assert app.screen_text().splitlines()[0].startswith("20x6")
        app.screen_text()
        assert draws == [(20, 6)]
        app.resize(30, 9)
        frame = app.screen_text()
        assert len(frame.splitlines()) == 9
        assert all(len(line) == 30 for line in frame.splitlines())
        assert frame.splitlines()[0].startswith("30x9")
        assert draws[-1] == (30, 9)


def test_render_error_panel_keeps_quit_binding_alive(tmp_path: Path) -> None:
    errors = tmp_path / "tui-errors.log"
    quit_called: list[bool] = []

    def broken(_: Canvas) -> None:
        raise RuntimeError("expected render failure")

    app = CanvasApp(broken, quit_callback=lambda: quit_called.append(True), error_log=errors)
    with HeadlessApp(app=app, size=(30, 10), error_log=str(errors)) as headless:
        screen = headless.screen_text()
        assert "Render error" in screen
        assert "expected render failure" in screen
        assert "Ctrl+Q quit" in screen
        assert errors.read_text(encoding="utf-8").count("expected render failure") == 1
        headless.press("c-q")
        assert quit_called == [True]
    assert any(event.kind == "quit" for event in app.events())


def test_headless_rejects_invalid_sizes_and_coordinates() -> None:
    with pytest.raises(ValueError):
        HeadlessApp(size=(0, 24))
    with HeadlessApp(size=(10, 4), widgets=FocusRing()) as app:
        with pytest.raises(ValueError):
            app.click(-1, 0)


def test_no_color_forces_the_ascii_safe_mono_skin(monkeypatch: pytest.MonkeyPatch) -> None:
    custom, warnings = load_skin(
        '''schema = "md-editor-theme/1.1"\nid = "color-test"\nname = "COLOR"\ninstrument = "any"\n[styles]\ntext = { fg = "#ffffff" }\n'''
    )
    assert custom.id == "color-test"
    assert any("missing role" in warning for warning in warnings)
    monkeypatch.setenv("NO_COLOR", "")
    app = CanvasApp(skin=custom)
    assert app.skin.id == "mono"
    assert app.ascii_only is True
