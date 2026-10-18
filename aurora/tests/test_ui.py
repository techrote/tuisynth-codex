from __future__ import annotations

import os
from pathlib import Path

import pytest

from trio_aurora.instrument import aurora_spec
from trio_aurora.ui import HarmonicPainter, SCREEN_NAMES, waterfall_column_levels
from trio_kit.events import NoteOff, NoteOn
from trio_kit.shell import Shell
from trio_kit.skins import REQUIRED_ROLES, SkinLibrary
from trio_kit.tui.testing import HeadlessApp


SKINS = ("borealis", "solar-wind", "polar-night", "mono")
SNAPSHOT_SIZES = ((100, 30), (80, 24))
SNAPSHOT_SCREENS = ("play", "shape")


def _shell(tmp_path: Path, skin: str = "mono") -> Shell:
    return Shell(
        aurora_spec(),
        no_audio=True,
        start_midi=False,
        skin_id=skin,
        data_dir=tmp_path,
    )


def test_shift_f4_opens_focused_spectral_modulation_area(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    try:
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as app:
            app.press("s-f4")
            assert shell.current_screen == "s-f4"
            assert shell.widgets.focused_tag == "modulation-spectral"
            assert "MOD MATRIX" in app.screen_text()
            assert "SPECTRAL" in app.screen_text()
            app.press("escape")
            assert shell.current_screen == "f2"
    finally:
        shell.shutdown()


def test_sgr_modulation_route_and_pedal_reorder_reach_aurora_screen(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    try:
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as app:
            app.press("s-f4")
            app.screen_text()
            widget = next(item for item in shell.widgets.widgets if item.tag == "modulation-spectral")
            grid = widget._grid
            assert grid is not None
            app.click(grid.x + 5, grid.y)
            app.click(widget.bounds.x + widget._cell_width // 2, widget._details_y + 1)
            app.click(widget.bounds.x + widget._cell_width - 1, widget._details_y + 2)
            route = shell._known_extras["modulation"]["slots"][0]
            assert route["source"] == "lfo1"
            assert route["destination"] == "osc.detune"
            assert route["amount"] == pytest.approx(1.0)

            first, second = widget._pedals[:2]
            app.drag(((first.x + first.width // 2, first.y), (second.x + second.width // 2, second.y)))
            assert shell._known_extras["modulation"]["rack"]["order"][1] == "tremolo"
    finally:
        shell.shutdown()


def test_factory_skins_have_no_warnings_and_define_aurora_roles(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    root = Path(__file__).parents[1] / "src" / "trio_aurora" / "data" / "skins"
    library = SkinLibrary.for_instrument(
        "aurora", data_dir=tmp_path, factory_dir=root, no_color=False, environ={}
    )
    assert library.ids == ("mono", "borealis", "polar-night", "solar-wind")
    assert library.warnings == ()
    for skin_id in SKINS[:-1]:
        skin = library.select(skin_id)
        assert set(REQUIRED_ROLES) <= set(skin.styles)
        assert skin.instrument == "aurora"
        assert len(skin.glyphs["density"]) >= 5
        assert len(skin.ramp("aurora")) >= 2
        assert "A U R O R A" in skin.art_block("logo")[0]


def test_waterfall_levels_are_monotone_silent_and_frozen() -> None:
    profile = tuple(index / 63 for index in range(64))
    live = waterfall_column_levels(profile, active_voices=1, voice_rms=0.1, columns=32)
    assert all(left <= right for left, right in zip(live, live[1:]))
    assert max(live) > 0
    lfo_live = waterfall_column_levels(
        profile, active_voices=1, voice_rms=0.1, columns=32, envelope_level=4.0, lfo_level=1.0
    )
    quiet_lfo = waterfall_column_levels(
        profile, active_voices=1, voice_rms=0.1, columns=32, envelope_level=4.0, lfo_level=0.0
    )
    assert max(lfo_live) > max(quiet_lfo) > 0
    assert waterfall_column_levels(profile, active_voices=0, voice_rms=0.0, columns=32) == (0.0,) * 32
    frozen_a = waterfall_column_levels(profile, active_voices=0, voice_rms=0.0, columns=32, frozen=True)
    frozen_b = waterfall_column_levels(profile, active_voices=0, voice_rms=0.0, columns=32, frozen=True)
    assert frozen_a == frozen_b
    assert max(frozen_a) > 0


def test_harmonic_extras_dirty_state_and_preset_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path)
    try:
        shell._ensure_widgets(100, 30)
        painter = next(widget for widget in shell.widgets.widgets if isinstance(widget, HarmonicPainter))
        profile = [0.0] * 64
        profile[0] = 1.0
        assert shell.set_extras({"harmonics": profile})
        assert shell.modified
        assert painter.harmonics == profile
        saved = shell.save_preset("Painted profile", preset_id="painted-profile")
        assert not shell.modified
        assert shell.set_extras({"harmonics": [0.25] * 64})
        assert shell.modified
        shell.load_preset(saved.id)
        assert painter.harmonics == profile
        assert not shell.modified
        shell.engine.render(256)
        assert shell.engine.get_extras()["harmonics"] == profile
    finally:
        shell.shutdown()


def test_named_screens_piano_skin_cycle_and_quit_are_headless(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path, "borealis")
    worker = shell.engine.instrument._thread
    with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
        first = app.screen_text()
        assert "[PLAY]" in first
        assert "AURORA WATERFALL" in first
        assert shell.piano.octaves == 4
        assert shell.piano.bounds.width == 84
        for index, screen in enumerate(SCREEN_NAMES, start=2):
            app.press(f"f{index}")
            assert shell.current_screen == f"f{index}"
            assert f"[{screen.upper()}]" in app.screen_text()
        library = app.screen_text()
        assert "PRESETS" in library and "SKINS" in library
        previous_skin = shell.skins.current_id
        app.press("f6")
        assert shell.skins.current_id != previous_skin
        app.screen_text()
        key = shell.piano.key_bounds(60)
        app.click(key.x + 1, key.bottom - 1)
        events = shell.piano.events()
        note_on = next(event for event in events if isinstance(event, NoteOn))
        note_off = next(event for event in events if isinstance(event, NoteOff))
        assert note_on.note_id == note_off.note_id
        app.press("c-q")
    assert shell._closed
    assert worker is None or not worker.is_alive()


def test_painter_real_sgr_drag_erase_wheel_and_keyboard_twins(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path, "borealis")
    with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
        app.press("f3")
        app.screen_text()
        painter = next(widget for widget in shell.widgets.widgets if isinstance(widget, HarmonicPainter))
        assert painter.visible_bars == 64
        start = painter.cell_for_index(4, height=0.75)
        end = painter.cell_for_index(12, height=0.75)
        app.drag((start, end))
        assert all(painter.harmonics[index] == pytest.approx(0.75) for index in range(4, 13))
        assert shell.modified

        erase_start = painter.cell_for_index(4)
        erase_end = painter.cell_for_index(12)
        app.drag((erase_start, erase_end), button="right")
        assert all(painter.harmonics[index] == 0.0 for index in range(4, 13))

        index = 20
        painter.selected = index
        x, y = painter.cell_for_index(index)
        before = painter.harmonics[index]
        app.wheel(x, y, "up")
        assert painter.harmonics[index] == pytest.approx(before + 0.05)
        painter.selected = index
        app.press("up")
        assert painter.harmonics[index] == pytest.approx(before + 0.10)
        app.press("c-e")
        assert all(value == 0.0 for harmonic, value in enumerate(painter.harmonics) if harmonic % 2)
        app.press("c-o")
        assert all(value == 0.0 for harmonic, value in enumerate(painter.harmonics) if harmonic % 2 == 0)
        app.press("c-r")
        randomized = tuple(painter.harmonics)
        assert len(set(randomized)) > 1
        app.press("delete")
        assert painter.harmonics[painter.selected] == 0.0
        app.press("c-q")


def test_snapshot_freeze_is_repeatable(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    frames = []
    for _ in range(2):
        shell = _shell(tmp_path, "solar-wind")
        try:
            frames.append(shell.snapshot(80, 24, screen="play"))
        finally:
            shell.shutdown()
    assert frames[0] == frames[1]
    assert "tables frozen" in frames[0]


def test_library_selection_previews_presets_and_skins(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path, "borealis")
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.press("f5")
            app.screen_text()
            presets = next(widget for widget in shell.widgets.widgets if widget.tag == "aurora-library-presets")
            skins = next(widget for widget in shell.widgets.widgets if widget.tag == "aurora-library-skins")
            assert presets.handle_key("down")
            assert shell.engine_preset_name == presets.items[presets.selected]
            assert skins.handle_key("down")
            assert shell.skins.current_id == skins.items[skins.selected]
            app.press("c-q")
    finally:
        shell.shutdown()
    assert shell._closed


@pytest.mark.parametrize("skin", SKINS)
@pytest.mark.parametrize("size", SNAPSHOT_SIZES)
@pytest.mark.parametrize("screen", SNAPSHOT_SCREENS)
def test_play_and_shape_golden_snapshots(tmp_path, monkeypatch, skin, size, screen) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path, skin)
    try:
        actual = shell.snapshot(*size, screen=screen)
    finally:
        shell.shutdown()
    width, height = size
    golden = Path(__file__).parent / "snapshots" / f"aurora-{screen}-{skin}-{width}x{height}.txt"
    if os.environ.get("TRIO_UPDATE_SNAPSHOTS") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual + "\n", encoding="utf-8", newline="\n")
    assert golden.exists(), f"missing snapshot {golden.name}; run tools/check.py --package aurora --update-snapshots"
    assert actual == golden.read_text(encoding="utf-8").rstrip("\n")
    if screen == "play":
        lines = actual.splitlines()
        waterfall = next(index for index, line in enumerate(lines) if "AURORA WATERFALL" in line)
        painter = next(index for index, line in enumerate(lines) if "HARMONICS" in line)
        assert painter - waterfall == (5 if width >= 100 else 4)


def test_shift_f3_sequencer_golden_snapshot_and_sgr_controls(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    shell = _shell(tmp_path, "borealis")
    try:
        snapshot = shell.snapshot(80, 24, screen="sequencer")
        assert "SEQ" in snapshot and shell.app is not None and shell.app.error is None
        target = Path(__file__).parent / "snapshots" / "aurora-sequencer-borealis-80x24.txt"
        if os.environ.get("TRIO_UPDATE_SNAPSHOTS") == "1":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(snapshot + "\n", encoding="utf-8", newline="\n")
        assert target.exists(), f"missing golden snapshot {target.name}; run tools/check.py --package aurora --update-snapshots"
        assert snapshot == target.read_text(encoding="utf-8").rstrip("\n")
        shell.shutdown()
        shell = _shell(tmp_path / "interaction", "borealis")
        with HeadlessApp(size=(80, 24), app=shell.build_app()) as driver:
            driver.press("f3")
            driver.press("s-f3")
            grid = next(widget for widget in shell.widgets.widgets if widget.tag == "sequencer-spectral")
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
            assert shell.current_screen == "f3" and not grid.visible
            assert shell.widgets.focused is None
    finally:
        shell.shutdown()
