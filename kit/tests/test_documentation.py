"""User-reference regressions: runtime dispatch, real terminal input and artifacts."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

import pytest

from trio_kit.events import InstrumentEvent, NoteOn
from trio_kit.input.keyboard import KeyboardPiano
from trio_kit.shell import Shell
from trio_kit.tui.canvas import Rect
from trio_kit.tui.testing import HeadlessApp

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("trio_documentation", ROOT / "tools" / "documentation.py")
assert SPEC is not None and SPEC.loader is not None
DOCS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DOCS
SPEC.loader.exec_module(DOCS)


@pytest.mark.parametrize("name,handler,bindings,excluded", DOCS.binding_groups(), ids=lambda value: value if isinstance(value, str) else None)
def test_control_tables_cover_actual_dispatch_branches(name, handler, bindings, excluded) -> None:
    """New/removed keys cannot silently leave a copied reference table behind."""
    implemented = DOCS.compared_keys(handler) - excluded
    documented = {key for binding in bindings for key in binding.keys}
    assert documented == implemented, name


def test_generated_reference_blocks_match_runtime_and_frozen_assets() -> None:
    assert DOCS.check_or_write() == []


def test_reference_check_rejects_stale_user_visible_action(tmp_path: Path) -> None:
    for filename, _marker in DOCS.generated_blocks():
        destination = tmp_path / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / filename, destination)
    target = tmp_path / "aurora/README.md"
    text = target.read_text(encoding="utf-8")
    assert "Erase even-numbered harmonics" in text
    target.write_text(text.replace("Erase even-numbered harmonics", "Erase odd-numbered harmonics"), encoding="utf-8")
    assert DOCS.check_or_write(root=tmp_path) == ["aurora/README.md"]


def test_all_published_document_links_resolve() -> None:
    documents = [ROOT / "README.md", ROOT / "CHANGELOG.md", *(ROOT / name / "README.md" for name in DOCS.INSTRUMENTS)]
    documents.extend(ROOT / "docs" / name for name in ("INSTALL.md", "CONTROLS.md", "CLI.md", "RELEASE.md", "RELEASE-NOTES-0.1.0.md", "ACCEPTANCE.md"))
    for path in documents:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            relative = target.split("#", 1)[0]
            assert (path.parent / relative).exists(), f"{path.relative_to(ROOT)} -> {target}"


@pytest.mark.parametrize("key,pitch", (("z", 48), ("m", 59), ("q", 60), ("u", 71), ("p", 76)))
def test_documented_note_range_uses_real_keyboard_events(key: str, pitch: int) -> None:
    keyboard = KeyboardPiano()
    events = keyboard.press(key, now=0.0)
    assert len(events) == 1 and isinstance(events[0], NoteOn)
    assert events[0].pitch == pitch and events[0].velocity == pytest.approx(0.7)
    assert keyboard.tick(now=0.449) == []
    assert len(keyboard.tick(now=0.451)) == 1


def test_aurora_even_odd_shortcuts_mean_numbered_harmonics_not_array_parity() -> None:
    from trio_aurora.ui import HarmonicPainter
    changes = []
    painter = HarmonicPainter(Rect(0, 0, 64, 8), [1.0] * 64, changes.append)
    painter.handle_key("c-e")
    assert changes[-1] == tuple(1.0 if harmonic % 2 else 0.0 for harmonic in range(1, 65))
    painter = HarmonicPainter(Rect(0, 0, 64, 8), [1.0] * 64, changes.append)
    painter.handle_key("c-o")
    assert changes[-1] == tuple(0.0 if harmonic % 2 else 1.0 for harmonic in range(1, 65))


@pytest.mark.parametrize("instrument", DOCS.INSTRUMENTS)
def test_published_global_keys_dispatch_in_the_real_application(tmp_path: Path, instrument: str) -> None:
    shell = Shell(DOCS.specs()[instrument], no_audio=True, start_midi=False, mono=True, data_dir=tmp_path, seed=0)
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.press("f3")
            assert shell.current_screen == "f3"
            app.press("s-f3")
            assert shell.current_screen == "s-f3"
            app.press("escape")
            assert shell.current_screen == "f3"
            app.press("s-f4")
            assert shell.current_screen == "s-f4"
            app.press("escape")
            assert shell.current_screen == "f3"
            app.press("f2")
            app.screen_text()
            shell.widgets.focus(shell.piano.tag)
            shell.engine.event_queue.drain()
            app.press("space")
            assert shell._known_extras["sequencer"]["playing"] is True
            assert not any(isinstance(event, NoteOn) for event in shell.engine.event_queue.drain())
            app.press("space")
            assert shell._known_extras["sequencer"]["playing"] is False
            app.press("f1")
            assert shell.overlay == "help"
            app.press("escape")
            assert shell.overlay is None
    finally:
        shell.shutdown()


def test_loom_enter_plays_but_space_controls_transport(tmp_path: Path) -> None:
    shell = Shell(DOCS.specs()["loom"], no_audio=True, start_midi=False, mono=True, data_dir=tmp_path)
    try:
        with HeadlessApp(size=(100, 30), app=shell.build_app()) as app:
            app.press("f2")
            shell.engine.event_queue.drain()
            app.press("enter")
            assert any(isinstance(event, InstrumentEvent) and event.name == "pluck" for event in shell.engine.event_queue.drain())
            app.press("space")
            assert shell._known_extras["sequencer"]["playing"] is True
            assert not any(isinstance(event, InstrumentEvent) and event.name in {"pluck", "bow_on"} for event in shell.engine.event_queue.drain())
    finally:
        shell.shutdown()


def test_drift_factory_omission_and_explicit_user_save_are_distinct(tmp_path: Path) -> None:
    spec = DOCS.specs()["drift"]
    for path in Path(spec.factory_presets_dir).glob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "field.x" not in raw["params"] and "field.y" not in raw["params"]
    shell = Shell(spec, no_audio=True, start_midi=False, mono=True, data_dir=tmp_path)
    try:
        shell.set_param("field.x", 0.25)
        shell.set_param("field.y", 0.75)
        shell.save_preset("Coordinate check")
        stored = json.loads((tmp_path / "drift" / "coordinate-check.json").read_text(encoding="utf-8"))
        assert stored["params"]["field.x"] == pytest.approx(0.25)
        assert stored["params"]["field.y"] == pytest.approx(0.75)
        shell.set_param("field.x", 0.5)
        shell.set_param("field.y", 0.5)
        shell.load_preset("coordinate-check")
        assert shell._known_params["field.x"] == pytest.approx(0.25)
        assert shell._known_params["field.y"] == pytest.approx(0.75)
    finally:
        shell.shutdown()
