"""Release audit regressions for real terminal input, without hardware."""

from __future__ import annotations

import pytest

from trio_kit.demo import demo_spec
from trio_kit.events import ControlChange, InstrumentEvent, NoteOff, NoteOn, Panic, RetargetNote
from trio_kit.input import FakeMidiBackend, MidiInput
from trio_kit.shell import Shell
from trio_kit.tui.testing import HeadlessApp


@pytest.mark.parametrize("dismiss", ("escape", "close", "replace", "shutdown"))
def test_dismissed_midi_learn_cannot_bind_the_next_controller(tmp_path, dismiss) -> None:
    shell = Shell(demo_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.press("c-l")
            control = shell.cc_learn.armed_control
            assert control is not None
            if dismiss == "escape":
                app.press("escape")
            elif dismiss == "close":
                shell.close_overlay()
            elif dismiss == "replace":
                shell.open_overlay("presets")
            else:
                shell.shutdown()
            assert shell.cc_learn.armed_control is None
            assert not shell.cc_learn.feed(74, 100)
            assert shell.cc_learn.lookup(control) is None
            assert not shell.cc_learn.path.exists()
    finally:
        shell.shutdown()


def click_text(app, text) -> None:
    rows = app.screen_text().splitlines()
    y = next(index for index, row in enumerate(rows) if text in row)
    app.click(rows[y].index(text), y)


def test_sgr_clicks_load_presets_and_connect_the_selected_fake_midi_port(tmp_path) -> None:
    shell = Shell(demo_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    shell.midi = MidiInput(shell._on_midi_event, backend=FakeMidiBackend(("Port A", "Port B")), cc_learn=shell.cc_learn)
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.press("f8")
            click_text(app, "Soft Glass (soft-glass)")
            assert shell.current_preset.id == "soft-glass"
            assert shell.overlay is None
            app.press("f7")
            click_text(app, "Port B")
            assert shell.midi.connected_port == "Port B"
            assert shell.overlay is None
            app.press("c-p")
            click_text(app, "Help")
            assert shell.overlay == "help"
    finally:
        shell.shutdown()


def test_modal_tab_cannot_play_a_hidden_widget_and_panic_remains_available(tmp_path) -> None:
    shell = Shell(demo_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            shell.widgets.focus("piano")
            app.press("f1")
            shell.engine.event_queue.drain()
            app.press("tab")
            app.press("enter")
            assert shell.widgets.focused_tag == "__overlay__"
            assert not any(isinstance(event, NoteOn) for event in shell.engine.event_queue.drain())
            app.press("f9")
            assert any(isinstance(event, Panic) for event in shell.engine.event_queue.drain())
            app.press("escape")
            assert shell.widgets.focused_tag == "piano"
    finally:
        shell.shutdown()


def test_long_preset_list_scrolls_to_the_real_keyboard_selection_then_mouse_loads_it(tmp_path) -> None:
    shell = Shell(demo_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    try:
        for index in range(24):
            shell.save_preset(f"ZZ test {index:02d}")
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as app:
            app.press("f8")
            for _ in range(25):
                app.press("down")
            assert "ZZ test 23" in app.screen_text()
            assert shell._overlay_scroll > 0
            click_text(app, "ZZ test 23")
            assert shell.current_preset.name == "ZZ test 23"
    finally:
        shell.shutdown()


@pytest.mark.parametrize("transition", ("none", "hidden", "modulation"))
def test_opening_modal_releases_captured_piano_without_hidden_glissando(tmp_path, transition) -> None:
    from trio_drift.ui import drift_spec

    shell = Shell(drift_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.screen_text()
            piano = shell.piano
            x, y = piano.bounds.x + 1, piano.bounds.bottom - 1
            app._send(app._sgr(0, x, y), events=1)
            started = [event for event in shell.engine.event_queue.drain() if isinstance(event, NoteOn)]
            assert len(started) == 1
            if transition == "hidden":
                piano.visible = False
            elif transition == "modulation":
                app.press("s-f4")
            app.press("f1")
            released = shell.engine.event_queue.drain()
            assert NoteOff(started[0].note_id) in released
            assert piano._mouse_note is None
            assert shell.app.router.capture is None
            app._send(app._sgr(32, x + 3, y), events=1)
            assert not any(isinstance(event, (NoteOn, RetargetNote)) for event in shell.engine.event_queue.drain())
            app.release(x + 3, y)
    finally:
        shell.shutdown()


def test_opening_modal_releases_weather_gust_and_blocks_background_movement(tmp_path) -> None:
    from trio_drift.ui import WeatherMap, drift_spec

    shell = Shell(drift_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.screen_text()
            field = next(widget for widget in shell.widgets.widgets if isinstance(widget, WeatherMap))
            x, y = field.plot.x + 3, field.plot.y + 3
            app._send(app._sgr(0, x, y), events=1)
            assert any(isinstance(event, InstrumentEvent) and event.name == "gust_on" for event in shell.engine.event_queue.drain())
            app.press("f1")
            assert any(isinstance(event, InstrumentEvent) and event.name == "gust_off" for event in shell.engine.event_queue.drain())
            position = (shell._known_params["field.x"], shell._known_params["field.y"])
            app._send(app._sgr(32, x + 10, y + 2), events=1)
            assert position == (shell._known_params["field.x"], shell._known_params["field.y"])
            assert not field._mouse_gust
            app.release(x + 10, y + 2)
    finally:
        shell.shutdown()


@pytest.mark.parametrize("instrument", ("aurora", "loom", "drift"))
@pytest.mark.parametrize("via_picker", (False, True))
def test_midi_learn_targets_actual_selected_parameter_in_each_instrument(tmp_path, instrument, via_picker) -> None:
    from trio_aurora.instrument import aurora_spec
    from trio_loom.ui import LoomPanelGroup, loom_spec
    from trio_drift.ui import ParameterDrawer, drift_spec
    from trio_kit.tui.widgets import ParamWidget

    spec = {"aurora": aurora_spec, "loom": loom_spec, "drift": drift_spec}[instrument]()
    shell = Shell(spec, no_audio=True, data_dir=tmp_path, start_midi=False)
    shell.midi = MidiInput(shell._on_midi_event, backend=FakeMidiBackend(("Test input",)), cc_learn=shell.cc_learn)
    try:
        with HeadlessApp(size=(80, 24) if instrument == "loom" else (100, 30), app=shell.build_app()) as app:
            app.press("f3" if instrument == "drift" else "f2")
            app.screen_text()
            if instrument == "drift":
                control = next(widget for widget in shell.widgets.widgets if isinstance(widget, ParameterDrawer) and widget.visible)
                shell.widgets.focus(control.tag)
                app.press("down")
                expected = "gr.size"
            elif instrument == "loom":
                control = next(widget for widget in shell.widgets.widgets if isinstance(widget, LoomPanelGroup))
                shell.widgets.focus(control.tag)
                app.press("right")
                expected = control.current.key
            else:
                control = next(widget for widget in shell.widgets.widgets if isinstance(widget, ParamWidget) and widget.visible and widget.spec.key != next(iter(shell.registry.specs)))
                shell.widgets.focus(control.tag)
                expected = control.spec.key
            assert expected != next(iter(shell.registry.specs))
            if via_picker:
                app.press("f7")
            app.press("c-l")
            assert shell.cc_learn.armed_control == expected
            before = dict(shell._known_params)
            assert shell.cc_learn.feed(74, 127)
            shell._on_midi_event(ControlChange(74, 127))
            assert shell._known_params[expected] == pytest.approx(shell.registry[expected].maximum)
            assert all(shell._known_params[key] == value for key, value in before.items() if key != expected)
    finally:
        shell.shutdown()
