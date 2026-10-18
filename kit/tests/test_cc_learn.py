from __future__ import annotations

import json

import pytest

from trio_kit.events import ControlChange
from trio_kit.input import CcLearnMap, MidiMapWarning


def test_cc_learn_arms_binds_persists_and_loads_again(tmp_path) -> None:
    path = tmp_path / "midi-map.json"
    learn = CcLearnMap(path)
    assert learn.lookup("filter.cutoff") is None
    assert learn.feed(ControlChange(74, 127)) is False

    learn.arm("filter.cutoff")
    assert learn.armed_control == "filter.cutoff"
    assert learn.feed(ControlChange(74, 127)) is True
    assert learn.armed_control is None
    assert learn.lookup("filter.cutoff") == 74
    assert learn.bindings == {"filter.cutoff": 74}
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema": "trio-midi-map/1",
        "bindings": {"filter.cutoff": 74},
    }

    reloaded = CcLearnMap(path)
    assert reloaded.lookup("filter.cutoff") == 74
    assert list(tmp_path.glob(".midi-map.json.*.tmp")) == []


def test_cc_learn_accepts_raw_cc_and_can_clear_one_or_all_bindings(tmp_path) -> None:
    learn = CcLearnMap(tmp_path / "midi-map.json")
    learn.arm("filter.cutoff")
    assert learn.feed(74, 100)
    learn.arm("amp.level")
    assert learn.feed(7)
    assert learn.bindings == {"filter.cutoff": 74, "amp.level": 7}

    assert learn.clear("filter.cutoff")
    assert learn.lookup("filter.cutoff") is None
    assert learn.lookup("amp.level") == 7
    assert not learn.clear("missing.control")
    assert learn.clear()
    assert learn.bindings == {}
    assert CcLearnMap(tmp_path / "midi-map.json").bindings == {}


@pytest.mark.parametrize(
    "contents",
    (
        "{not json",
        '{"schema":"wrong","bindings":{}}',
        '{"schema":"trio-midi-map/1","bindings":{"filter.cutoff":true}}',
        '{"schema":"trio-midi-map/1","bindings":[]}',
    ),
)
def test_corrupt_or_wrong_shape_maps_warn_and_load_empty(tmp_path, contents: str) -> None:
    path = tmp_path / "midi-map.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.warns(MidiMapWarning, match="using an empty map"):
        learn = CcLearnMap(path)
    assert learn.bindings == {}


def test_oversize_and_invalid_bindings_are_rejected_safely(tmp_path) -> None:
    path = tmp_path / "midi-map.json"
    path.write_bytes(b"x" * (64 * 1024 + 1))
    with pytest.warns(MidiMapWarning, match="64 KiB"):
        assert CcLearnMap(path).bindings == {}

    path.write_text(
        '{"schema":"trio-midi-map/1","bindings":' + "[" * 2_000 + "0" + "]" * 2_000 + "}",
        encoding="utf-8",
    )
    with pytest.warns(MidiMapWarning, match="using an empty map"):
        assert CcLearnMap(path).bindings == {}

    learn = CcLearnMap(tmp_path / "other.json")
    for control_id in ("", " padded ", "x" * 129, "line\nbreak", "\ud800"):
        with pytest.raises(ValueError, match="control_id"):
            learn.arm(control_id)
    for cc in (True, -1, 128, 1.5):
        learn.arm("filter.cutoff")
        with pytest.raises(ValueError, match="CC"):
            learn.feed(cc)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="CC value"):
        learn.feed(74, 128)


def test_for_instrument_uses_the_isolated_user_data_directory(tmp_path) -> None:
    learn = CcLearnMap.for_instrument("aurora", data_dir=tmp_path)
    assert learn.path == tmp_path / "aurora" / "midi-map.json"
    learn.arm("amp.level")
    learn.feed(7)
    assert learn.path.exists()


def test_map_refuses_to_persist_more_bindings_than_its_loader_accepts(tmp_path) -> None:
    path = tmp_path / "midi-map.json"
    path.write_text(
        json.dumps(
            {
                "schema": "trio-midi-map/1",
                "bindings": {f"control.{index}": index % 128 for index in range(512)},
            }
        ),
        encoding="utf-8",
    )
    mapping = CcLearnMap(path)
    mapping.arm("overflow")
    with pytest.warns(MidiMapWarning, match="512 bindings"):
        assert not mapping.feed(7)

    loaded = CcLearnMap(path)
    assert len(loaded.bindings) == 512
    assert loaded.lookup("overflow") is None
