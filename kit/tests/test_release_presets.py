"""Release regression: presets and MIDI mappings safely share their data root."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trio_kit.demo import demo_spec
from trio_kit.input import CcLearnMap, MidiMapWarning
from trio_kit.preset import Preset, PresetError, PresetWarning, save_preset
from trio_kit.shell import Shell


def _shell(directory: Path) -> Shell:
    return Shell(demo_spec(), no_audio=True, start_midi=False, data_dir=directory)


def test_saved_midi_map_does_not_break_preset_save_list_load_or_reopen(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    try:
        parameter = next(iter(shell.registry.specs))
        shell.cc_learn.arm(parameter)
        assert shell.cc_learn.feed(74)
        saved_map = shell.cc_learn.path.read_bytes()
        shell.save_preset("Sound after learn")
        available = {preset.id for preset in shell.presets.list_presets()}
        assert "sound-after-learn" in available
        assert "midi-map" not in available
        assert shell.load_preset("sound-after-learn").name == "Sound after learn"
        assert shell.cc_learn.path.read_bytes() == saved_map
    finally:
        shell.shutdown()
    reopened = _shell(tmp_path)
    try:
        assert reopened.cc_learn.lookup(parameter) == 74
        assert reopened.load_preset("sound-after-learn").id == "sound-after-learn"
        assert len(reopened.presets.list_presets()) >= 3
    finally:
        reopened.shutdown()


@pytest.mark.parametrize(
    "contents",
    (b"{not JSON", b"\xff\xfe", b'{"schema":"trio-midi-map/1","bindings":[]}', b"x" * 65537),
    # Pytest exposes node IDs through PYTEST_CURRENT_TEST. Keep the oversized
    # payload out of that Windows environment variable without reducing it.
    ids=("invalid-json", "invalid-utf8", "invalid-bindings", "oversized-map"),
)
def test_corrupt_midi_map_is_not_misclassified_as_a_preset(tmp_path: Path, contents: bytes) -> None:
    shell = _shell(tmp_path)
    try:
        shell.cc_learn.path.parent.mkdir(parents=True, exist_ok=True)
        shell.cc_learn.path.write_bytes(contents)
        assert {preset.id for preset in shell.presets.list_presets()} == {"init", "soft-glass"}
        with pytest.warns(MidiMapWarning, match="using an empty map"):
            assert CcLearnMap(shell.cc_learn.path).bindings == {}
    finally:
        shell.shutdown()


def test_reserved_save_rename_delete_cannot_destroy_midi_map(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    try:
        parameter = next(iter(shell.registry.specs))
        shell.cc_learn.arm(parameter)
        shell.cc_learn.feed(21)
        original = shell.cc_learn.path.read_bytes()
        shell.save_preset("Keep me")
        for overwrite in (False, True):
            with pytest.raises(PresetError, match="reserved for MIDI"):
                shell.save_preset("MIDI map", overwrite=overwrite)
            with pytest.raises(PresetError, match="reserved for MIDI"):
                shell.presets.rename("keep-me", "midi-map", overwrite=overwrite)
        with pytest.raises(PresetError, match="not a deletable user preset"):
            shell.presets.delete("midi-map")
        assert shell.cc_learn.path.read_bytes() == original
        assert shell.presets.get("keep-me").id == "keep-me"
        assert CcLearnMap(shell.cc_learn.path).lookup(parameter) == 21
    finally:
        shell.shutdown()


def test_historical_colliding_preset_remains_visible_and_renamable_without_loss(tmp_path: Path) -> None:
    shell = _shell(tmp_path)
    try:
        legacy = Preset("demo", "midi-map", "Old saved sound", dict(shell._known_params))
        path = shell.presets.user_dir / "midi-map.json"
        # Reproduce the legitimate on-disk state accepted by earlier versions.
        save_preset(path, legacy)
        original = path.read_bytes()
        with pytest.warns(MidiMapWarning, match="using an empty map"):
            mapping = CcLearnMap(path)
        parameter = next(iter(shell.registry.specs))
        mapping.arm(parameter)
        with pytest.warns(MidiMapWarning, match="cannot replace legacy preset"):
            assert mapping.feed(19)
        assert path.read_bytes() == original
        assert mapping.lookup(parameter) == 19  # Usable in-memory, not falsely persisted.
        with pytest.warns(PresetWarning, match="legacy preset id 'midi-map'"):
            assert shell.presets.get("midi-map").name == "Old saved sound"
        with pytest.warns(PresetWarning, match="legacy preset id 'midi-map'"):
            renamed = shell.presets.rename("midi-map", "old-saved-sound")
        assert renamed.name == "Old saved sound"
        assert not path.exists()
        assert shell.presets.get("old-saved-sound").params == legacy.params
        # Now the MIDI data can use its intended filename without colliding.
        mapping.arm(parameter)
        assert mapping.feed(20)
        assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "trio-midi-map/1"
        assert CcLearnMap(path).lookup(parameter) == 20
        assert shell.presets.get("old-saved-sound").name == "Old saved sound"
    finally:
        shell.shutdown()
