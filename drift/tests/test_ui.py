from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from trio_drift.ui import WeatherMap, drift_spec
from trio_kit.events import InstrumentEvent, ParamSet
from trio_kit.shell import Shell
from trio_kit.skins import SkinLibrary
from trio_kit.tui import Canvas, Rect
from trio_kit.tui.testing import HeadlessApp


SKINS = ("mono", "desert-haze", "monsoon", "squall")


def _shell(tmp_path: Path, *, skin: str = "mono") -> Shell:
    return Shell(
        drift_spec(clock=lambda: 0.0),
        no_audio=True,
        start_midi=False,
        skin_id=skin,
        mono=skin == "mono",
        data_dir=tmp_path,
        seed=17,
    )


def test_shift_f4_opens_focused_pressure_modulation_area(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    try:
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as app:
            app.press("s-f4")
            assert shell.current_screen == "s-f4"
            assert shell.widgets.focused_tag == "modulation-pressure"
            assert "MOD MATRIX" in app.screen_text()
            assert "PRESSURE" in app.screen_text()
            app.press("escape")
            assert shell.current_screen == "f2"
    finally:
        shell.shutdown()


def test_sgr_modulation_route_and_pedal_reorder_reach_drift_screen(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    try:
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as app:
            app.press("s-f4")
            app.screen_text()
            widget = next(item for item in shell.widgets.widgets if item.tag == "modulation-pressure")
            grid = widget._grid
            assert grid is not None
            app.click(grid.x + 5, grid.y)
            app.click(widget.bounds.x + widget._cell_width // 2, widget._details_y + 1)
            app.click(widget.bounds.x + widget._cell_width - 1, widget._details_y + 2)
            route = shell._known_extras["modulation"]["slots"][0]
            assert route["source"] == "lfo1"
            assert route["destination"] == "src.tone"
            assert route["amount"] == pytest.approx(1.0)

            first, second = widget._pedals[:2]
            app.drag(((first.x + first.width // 2, first.y), (second.x + second.width // 2, second.y)))
            assert shell._known_extras["modulation"]["rack"]["order"][1] == "tremolo"
    finally:
        shell.shutdown()


def test_factory_skins_are_warning_free_and_include_guaranteed_mono(tmp_path: Path) -> None:
    factory = Path(__file__).resolve().parents[1] / "src" / "trio_drift" / "data" / "skins"
    library = SkinLibrary("drift", factory_dir=factory, include_user=False, environ={})

    assert library.ids == SKINS
    assert library.warnings == ()
    for skin_id in SKINS[1:]:
        library.select(skin_id)
        skin = library.current
        assert skin.instrument == "drift"
        assert skin.art_block("logo")
        assert skin.art_block("isobars")
        assert skin.art_block("grains")
        assert skin.art_block("cursor")
        assert len(skin.ramp("grain_age")) == 5
        assert len(skin.ramp("isobar")) == 5


@pytest.mark.parametrize(("skin", "maximum_glyph"), (("mono", "#"), ("squall", "●")))
def test_seeded_isobars_and_grain_glyphs_draw_from_telemetry(
    skin: str,
    maximum_glyph: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path / skin, skin=skin)
    try:
        base = shell.engine.telemetry()
        synthetic = replace(
            base,
            instrument={
                "active_grains": 2,
                "spawned_grains": 2,
                "dropped_grains": 0,
                "grain_density": 35.0,
                "field_x": 0.5,
                "field_y": 0.5,
                "vowel": 2.0,
                "wind": 0.0,
                "gust": 0.0,
                "source_color": 0.0,
                "source_regenerations": 1,
                "voice_rms": 0.0,
                "grain_pan": (0.05, 0.95),
                "grain_ratio": (2.0**3, 2.0**-3),
                "grain_amplitude": (0.0, 1.0),
                "grain_age": (0.0, 1.0),
            },
        )
        monkeypatch.setattr(shell.engine, "telemetry", lambda: synthetic)
        now = [0.0]
        weather = WeatherMap(shell, Rect(2, 4, 76, 12), clock=lambda: now[0])
        canvas_a = Canvas(80, 24, ascii_only=skin == "mono")
        weather.draw(canvas_a)
        assert weather.drawn_particle_count == 2
        low_cell, high_cell = weather.particle_cells
        assert plot_contains(weather.plot, low_cell)
        assert plot_contains(weather.plot, high_cell)
        assert canvas_a.cells[low_cell[1]][low_cell[0]].char == "."
        assert canvas_a.cells[high_cell[1]][high_cell[0]].char == maximum_glyph
        if skin == "mono":
            assert canvas_a.cells[low_cell[1]][low_cell[0]].role == "muted"
            assert canvas_a.cells[high_cell[1]][high_cell[0]].role == "accent"

        now[0] = 100.0
        shell.snapshot_mode = True
        weather_again = WeatherMap(shell, Rect(2, 4, 76, 12), clock=lambda: now[0])
        canvas_b = Canvas(80, 24, ascii_only=skin == "mono")
        weather_again.draw(canvas_b)
        canvas_c = Canvas(80, 24, ascii_only=skin == "mono")
        weather_again.draw(canvas_c)
        assert canvas_b.snapshot() == canvas_c.snapshot()
        assert weather_again.drawn_particle_count == 2
    finally:
        shell.shutdown()


def plot_contains(plot: Rect, cell: tuple[int, int]) -> bool:
    x, y = cell
    return plot.x <= x < plot.right and plot.y <= y < plot.bottom


def test_particle_endpoints_stay_inside_plot_and_count_visible_cells(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path)
    try:
        base = shell.engine.telemetry()
        synthetic = replace(
            base,
            instrument={
                **base.instrument,
                "active_grains": 3,
                "grain_pan": (0.0, 1.0, 0.0),
                "grain_ratio": (16.0, 1.0 / 16.0, 16.0),
                "grain_amplitude": (0.5, 0.5, 1.0),
                "grain_age": (0.5, 0.5, 0.7),
            },
        )
        monkeypatch.setattr(shell.engine, "telemetry", lambda: synthetic)
        shell.snapshot_mode = True
        weather = WeatherMap(shell, Rect(2, 4, 76, 12), clock=lambda: 0.0)
        weather.draw(Canvas(80, 24, ascii_only=True))

        plot = weather.plot
        assert weather.particle_cells == (
            (plot.x, plot.y),
            (plot.right - 1, plot.bottom - 1),
            (plot.x, plot.y),
        )
        assert weather.drawn_particle_count == 2
        assert all(plot_contains(plot, cell) for cell in weather.particle_cells)
    finally:
        shell.shutdown()


def test_real_sgr_weather_map_gesture_controls_and_keyboard_twin(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    try:
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as driver:
            driver.press("f2")
            weather = next(widget for widget in shell.widgets.widgets if isinstance(widget, WeatherMap))
            plot = weather.plot
            driver.drag(((plot.x, plot.y), (plot.right - 1, plot.bottom - 1)))
            assert shell._known_params["field.x"] == pytest.approx(1.0)
            assert shell._known_params["field.y"] == pytest.approx(0.0)
            queued = shell.engine.event_queue.drain()
            gusts = [event.name for event in queued if isinstance(event, InstrumentEvent) and event.name.startswith("gust_")]
            assert gusts == ["gust_on", "gust_off"]
            field_y_values = [event.value for event in queued if isinstance(event, ParamSet) and event.key == "field.y"]
            field_x_values = [event.value for event in queued if isinstance(event, ParamSet) and event.key == "field.x"]
            assert field_y_values == [1.0, 0.0]
            assert field_x_values == [1.0]

            driver.click(plot.x, plot.y, button="right")
            assert shell._known_params["field.x"] == pytest.approx(0.5)
            assert shell._known_params["field.y"] == pytest.approx(0.5)
            density = float(shell._known_params["gr.density"])
            driver.wheel(plot.x, plot.y, "up")
            assert float(shell._known_params["gr.density"]) > density

            driver.press("right")
            driver.press("pageup")
            assert shell._known_params["field.x"] == pytest.approx(0.52)
            assert shell._known_params["field.y"] == pytest.approx(0.6)
            driver.press("enter")
            assert weather._gust_active
            driver.press("enter")
            assert not weather._gust_active
            driver.press("delete")
            assert shell._known_params["field.x"] == pytest.approx(0.5)
            assert shell._known_params["field.y"] == pytest.approx(0.5)
    finally:
        shell.shutdown()


def test_grain_air_drawers_and_library_are_mutually_exclusive_and_closable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path, skin="squall")
    try:
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as driver:
            driver.press("f3")
            driver.app._ensure_frame()
            drawer = next(widget for widget in shell.widgets.widgets if widget.tag == "drift-grain-drawer")
            assert drawer.visible
            assert drawer.keys == (
                "gr.density", "gr.size", "gr.size_jit", "gr.pos", "gr.pos_scatter",
                "gr.spread", "gr.pitch_scatter", "gr.window", "gr.max",
            )
            density = float(shell._known_params["gr.density"])
            driver.press("right")
            assert float(shell._known_params["gr.density"]) > density
            driver.app._ensure_frame()
            size = float(shell._known_params["gr.size"])
            col_width = (drawer.bounds.width - 2) // 2
            control_x = drawer.bounds.x + 1 + col_width + 1
            driver.click(control_x, drawer.bounds.y + 1)
            assert drawer.selected == 1
            driver.press("right")
            assert float(shell._known_params["gr.size"]) > size

            shell.set_param("gr.pos", 0.8, record_history=False)
            driver.app._ensure_frame()
            position_y = drawer.bounds.y + 2
            driver.click(control_x, position_y, button="right")
            assert float(shell._known_params["gr.pos"]) == pytest.approx(0.5)
            driver.app._ensure_frame()
            driver.wheel(control_x, position_y, "up")
            assert float(shell._known_params["gr.pos"]) > 0.5

            driver.press("escape")
            assert shell.current_screen == "f2"
            assert not drawer.visible

            driver.press("f4")
            grain = next(widget for widget in shell.widgets.widgets if widget.tag == "drift-grain-drawer")
            air = next(widget for widget in shell.widgets.widgets if widget.tag == "drift-air-drawer")
            assert air.visible and not grain.visible
            assert air.keys == (
                "src.color", "src.tone", "src.breath", "fmt.vowel", "fmt.shift", "fmt.q",
                "fmt.mix", "field.amount", "wind.gust", "wind.howl", "wind.rate", "fx.reverb.mix",
            )
            before = float(shell._known_params["src.color"])
            driver.press("right")
            assert float(shell._known_params["src.color"]) > before
            driver.press("escape")

            driver.press("f5")
            library = next(widget for widget in shell.widgets.widgets if widget.tag == "drift-library")
            assert library.visible and not air.visible and not grain.visible
            assert library.skin_index == shell.skins.ids.index("squall")
            driver.press("right")
            driver.press("up")
            driver.press("up")
            driver.press("enter")
            assert shell.skins.current_id == "desert-haze"
            driver.press("escape")
            assert shell.current_screen == "f2"
    finally:
        shell.shutdown()


def test_headless_screens_render_at_full_and_compact_sizes_for_every_skin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    for skin in SKINS:
        shell = _shell(tmp_path / skin, skin=skin)
        try:
            for width, height in ((100, 30), (80, 24)):
                map_frame = shell.snapshot(width, height, screen="map")
                grain_frame = shell.snapshot(width, height, screen="grain")
                assert len(map_frame.splitlines()) == height
                assert len(grain_frame.splitlines()) == height
                assert "DRIFT" in map_frame and "STORM" in map_frame and "CALM" in map_frame
                assert "GRAIN" in grain_frame and "density" in grain_frame
                assert "F3 grain" in map_frame or "F3" in map_frame
                assert shell.app is not None and shell.app.error is None
        finally:
            shell.shutdown()


def test_drift_spec_keeps_instrument_identity_and_screen_routes() -> None:
    spec = drift_spec(clock=lambda: 0.0)
    assert spec.identifier == "drift"
    assert spec.screen_names == ("map", "grain", "air", "library")
    assert spec.max_voices == 6
    assert spec.widgets is not None and spec.on_screen is not None


def test_shift_f3_sequencer_golden_snapshot_and_sgr_controls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path / "sequencer", skin="squall")
    try:
        snapshot = shell.snapshot(80, 24, screen="sequencer")
        assert "SEQ" in snapshot and shell.app is not None and shell.app.error is None
        target = Path(__file__).parent / "snapshots" / "drift-sequencer-squall-80x24.txt"
        if __import__("os").environ.get("TRIO_UPDATE_SNAPSHOTS") == "1":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(snapshot + "\n", encoding="utf-8")
        assert target.exists(), f"missing golden snapshot: {target.name}"
        assert snapshot == target.read_text(encoding="utf-8").rstrip("\n")
        shell.shutdown()
        shell = _shell(tmp_path / "interaction", skin="squall")
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as driver:
            driver.press("f4")
            driver.press("s-f3")
            grid = next(widget for widget in shell.widgets.widgets if widget.tag == "sequencer-pressure")
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
            assert shell.current_screen == "f4" and not grid.visible
            assert shell.widgets.focused is not None and shell.widgets.focused.tag == "drift-air-drawer"
    finally:
        shell.shutdown()
