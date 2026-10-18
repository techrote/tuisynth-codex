from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from trio_kit.events import InstrumentEvent, NoteOff, NoteOn, ParamSet
from trio_kit.shell import Shell
from trio_kit.skins import SkinLibrary
from trio_kit.tui.mouse import MouseInput
from trio_kit.tui.testing import HeadlessApp
from trio_loom.ui import SCREEN_NAMES, chord_label, loom_spec


class StepClock:
    def __init__(self, step: float) -> None:
        self.step = step
        self.value = 0.0

    def __call__(self) -> float:
        self.value += self.step
        return self.value


def _shell(tmp_path: Path, *, clock=StepClock(0.05), skin: str = "rosewood") -> Shell:
    return Shell(
        loom_spec(clock=clock),
        no_audio=True,
        data_dir=tmp_path,
        start_midi=False,
        skin_id=skin,
        mono=skin == "mono",
        seed=17,
    )


def _drag_notes(tmp_path: Path, interval: float) -> tuple[InstrumentEvent, ...]:
    shell = _shell(tmp_path, clock=StepClock(interval))
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.drag([(12, 4 + row) for row in range(8)])
            events = shell.engine.event_queue.drain()
        return tuple(event for event in events if isinstance(event, InstrumentEvent))
    finally:
        shell.shutdown()


def test_sgr_drag_crosses_each_string_in_order_and_velocity_tracks_speed(tmp_path) -> None:
    slow = _drag_notes(tmp_path / "slow", 0.1)
    fast = _drag_notes(tmp_path / "fast", 0.02)
    assert [event.name for event in slow] == ["pluck"] * 8
    assert [event.payload[2] for event in slow] == list(range(7, -1, -1))
    assert [event.payload[2] for event in fast] == list(range(7, -1, -1))
    assert fast[1].payload[1] > slow[1].payload[1]


def test_bow_capture_releases_every_started_string_and_right_click_mutes(tmp_path) -> None:
    shell = _shell(tmp_path)
    try:
        assert shell.set_param("exc.mode", 1)
        shell.engine.event_queue.drain()
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.drag([(12, 4), (12, 5), (12, 6)])
            events = shell.engine.event_queue.drain()
            assert [event.name for event in events if isinstance(event, InstrumentEvent)] == [
                "bow_on", "bow_on", "bow_on", "bow_off", "bow_off", "bow_off"
            ]
            app.click(12, 4, button="right")
            muted = shell.engine.event_queue.drain()
            assert muted == (InstrumentEvent("mute", (7,)),)
    finally:
        shell.shutdown()


def test_bow_capture_keeps_its_start_mode_when_excitation_changes(tmp_path) -> None:
    shell = _shell(tmp_path)
    try:
        assert shell.set_param("exc.mode", 1)
        shell.engine.event_queue.drain()
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.screen_text()
            surface = next(widget for widget in shell.widgets.widgets if widget.tag == "loom-strings")
            assert surface.handle_mouse(MouseInput(12, 4, "down", "left"))
            started = shell.engine.event_queue.drain()
            assert shell.set_param("exc.mode", 0)
            shell.engine.event_queue.drain()
            assert surface.handle_mouse(MouseInput(12, 5, "move"))
            assert surface.handle_mouse(MouseInput(12, 5, "up"))
            events = (*started, *shell.engine.event_queue.drain())
        assert [event.name for event in events if isinstance(event, InstrumentEvent)] == [
            "bow_on", "bow_on", "bow_off", "bow_off"
        ]
    finally:
        shell.shutdown()


def test_chord_mode_routes_piano_to_tuning_and_direct_mode_keeps_notes(tmp_path) -> None:
    shell = _shell(tmp_path)
    try:
        assert shell.set_param("play.mode", 1)
        shell.engine.event_queue.drain()
        shell._on_piano_event(NoteOn(701, 62, 0.8, "onscreen-keyboard"))
        assert shell.engine.event_queue.drain() == (InstrumentEvent("held", (62.0,)),)
        shell._on_piano_event(NoteOn(702, 65, 0.7, "onscreen-keyboard"))
        assert shell.engine.event_queue.drain() == (InstrumentEvent("held", (62.0, 65.0)),)
        shell._on_piano_event(NoteOff(701))
        assert shell.engine.event_queue.drain() == (InstrumentEvent("held", (65.0,)),)
        assert shell.set_param("play.mode", 0)
        shell.engine.event_queue.drain()
        shell._on_piano_event(NoteOn(703, 67, 0.9, "onscreen-keyboard"))
        direct = shell.engine.event_queue.drain()
        assert isinstance(direct[0], InstrumentEvent) and direct[0].name == "held"
        assert direct[1] == NoteOn(703, 67, 0.9, "onscreen-keyboard")
        assert shell.set_param("play.mode", 1)
        shell.engine.event_queue.drain()
        shell._on_piano_event(NoteOff(703))
        released_after_mode_switch = shell.engine.event_queue.drain()
        assert released_after_mode_switch == (InstrumentEvent("held", (65.0,)), NoteOff(703))
        assert chord_label((62, 65, 69)) == "D minor (D F A)"
    finally:
        shell.shutdown()


def test_chord_mode_routes_computer_keyboard_and_midi_through_held_tuning(tmp_path) -> None:
    shell = _shell(tmp_path)
    try:
        assert shell.set_param("play.mode", 1)
        shell.engine.event_queue.drain()
        assert shell.handle_key("any", "z")
        computer = shell.engine.event_queue.drain()
        assert len(computer) == 1
        assert isinstance(computer[0], InstrumentEvent) and computer[0].name == "held"
        assert computer[0].payload
        for event in shell.keyboard.release_all():
            shell._push(event)
        released = shell.engine.event_queue.drain()
        assert isinstance(released[0], InstrumentEvent) and not released[0].payload

        shell._on_midi_event(NoteOn(9901, 72, 0.8, "midi"))
        midi = shell.engine.event_queue.drain()
        assert midi == (InstrumentEvent("held", (72.0,)),)
        shell._on_midi_event(NoteOff(9901))
        assert shell.engine.event_queue.drain() == (InstrumentEvent("held", ()),)
    finally:
        shell.shutdown()


def test_surface_telemetry_animates_and_snapshot_render_does_not_advance_it(tmp_path) -> None:
    shell = _shell(tmp_path, skin="mono")
    try:
        app = shell.build_app()
        shell.snapshot_mode = True
        quiet = app.screen_text()
        shell._push(InstrumentEvent("pluck", (64.0, 0.9, 3)))
        shell.engine.render(256)
        instrument = shell.engine.instrument
        first = instrument.telemetry()
        assert len(first["string_pitches"]) == 8
        assert len(first["string_levels"]) == 8
        assert len(first["string_phases"]) == 8
        assert first["string_levels"][3] > 0
        phase_before = first["string_phases"]
        instrument.process_bus(np.zeros((256, 2), dtype=np.float32), instrument._params)
        assert instrument.telemetry()["string_phases"] != phase_before

        assert shell.spec.refresh_when is not None and not shell.spec.refresh_when(shell)
        app.invalidate()
        one = app.screen_text()
        app.invalidate()
        two = app.screen_text()
        shell.snapshot_mode = False
        assert quiet != one
        assert one == two
    finally:
        shell.shutdown()


def test_headless_layout_focus_and_compact_parameter_cycles(tmp_path) -> None:
    shell = _shell(tmp_path)
    try:
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as app:
            compact = app.screen_text()
            for label in ("STRINGS", "SYMPATHETIC", "EXCITE", "STRING", "BODY", "SYMPATHY", "PLAY", "PIANO"):
                assert label in compact
            app.press("f1")
            assert "LOOM strings:" in app.screen_text()
            app.press("escape")
            app.press("f2")
            assert shell.widgets.focused_tag == "loom-strings"
            app.press("f3")
            assert shell.widgets.focused_tag == "loom-panel-excite"
            panel = shell.widgets.focused
            assert panel is not None
            old_key = panel.current.key
            panel.handle_key("right")
            assert panel.current.key != old_key
            app.press("f4")
            assert shell.widgets.focused_tag == "loom-sympathy"
            app.press("f5")
            assert shell.overlay == "presets"
    finally:
        shell.shutdown()


@pytest.mark.parametrize("skin", ("rosewood", "brass", "indigo-loom", "mono"))
def test_factory_skins_are_warning_free_and_have_required_string_art(tmp_path, skin: str) -> None:
    library = SkinLibrary.for_instrument("loom", factory_dir=Path(__file__).parents[1] / "src" / "trio_loom" / "data" / "skins", skin_id=skin, mono=skin == "mono", environ={})
    assert library.warnings == ()
    assert library.current_id == skin
    if skin != "mono":
        assert len(library.current.ramp("string")) == 5
        assert len(library.current.glyphs["string"]) >= 2
        assert library.current.art.get("logo")


@pytest.mark.parametrize("skin", ("rosewood", "brass", "indigo-loom", "mono"))
@pytest.mark.parametrize("size", ((100, 30), (80, 24)))
def test_golden_loom_snapshots(tmp_path, monkeypatch, skin: str, size: tuple[int, int]) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    columns, rows = size
    shell = _shell(tmp_path / f"{skin}-{columns}x{rows}", skin=skin)
    try:
        snapshot = shell.snapshot(columns, rows) + "\n"
    finally:
        shell.shutdown()
    target = Path(__file__).parent / "snapshots" / f"loom-{skin}-{columns}x{rows}.txt"
    if __import__("os").environ.get("TRIO_UPDATE_SNAPSHOTS") == "1":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(snapshot, encoding="utf-8")
    else:
        assert target.exists(), f"missing golden snapshot: {target.name}"
        assert snapshot == target.read_text(encoding="utf-8")


def test_loom_screen_names_and_controls_are_instrument_specific() -> None:
    assert SCREEN_NAMES == ("strings", "panels", "sympathy", "library")
    assert set(SCREEN_NAMES).isdisjoint({"play", "shape", "space", "weather"})


def test_shift_f3_sequencer_golden_snapshot_and_sgr_controls(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path / "sequencer", skin="rosewood")
    try:
        snapshot = shell.snapshot(80, 24, screen="sequencer")
        assert "SEQ" in snapshot and shell.app is not None and shell.app.error is None
        target = Path(__file__).parent / "snapshots" / "loom-sequencer-rosewood-80x24.txt"
        if __import__("os").environ.get("TRIO_UPDATE_SNAPSHOTS") == "1":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(snapshot + "\n", encoding="utf-8")
        assert target.exists(), f"missing golden snapshot: {target.name}"
        assert snapshot == target.read_text(encoding="utf-8").rstrip("\n")
        shell.shutdown()
        shell = _shell(tmp_path / "interaction", skin="rosewood")
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as driver:
            driver.press("f2")
            driver.press("s-f3")
            grid = next(widget for widget in shell.widgets.widgets if widget.tag == "sequencer-thread")
            driver.start()
            driver.screen_text()
            first = next(cell for cell in grid._cell_centres if cell[1] == 0)
            second = next(cell for cell in grid._cell_centres if cell[1] == 1)
            third = next(cell for cell in grid._cell_centres if cell[1] == 2)
            driver.click(first[2], first[3])
            driver.drag([(second[2], second[3]), (second[2], max(grid.bounds.y, second[3] - 1))])
            driver.click(third[2], third[3], button="right")
            driver.press("right")
            driver.press("enter")
            driver.press("pageup")
            driver.press("space")
            driver.send_keys("amorl")
            settings = shell._known_extras["sequencer"]
            lane = settings["pattern"]["lanes"][0]
            assert lane[0]["on"] and lane[1]["on"] and lane[1]["velocity"] != 0.8
            assert lane[2]["on"] and lane[2]["probability"] == 0.25 and lane[2]["velocity"] > 0.8
            assert settings["playing"]
            assert settings["arpeggiator"] == {"enabled": True, "mode": "down", "octaves": 2, "rate": "1/8T", "latch": True, "seed": 0}
            assert shell.current_screen == "s-f3"
            assert shell.app.error is None
            driver.press("escape")
            driver.screen_text()
            assert shell.current_screen == "f2" and not grid.visible
            assert shell.widgets.focused is not None and shell.widgets.focused.tag == "loom-strings"
    finally:
        shell.shutdown()
