from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from trio_kit.params import ParamError, ParamRegistry, ParamSpec
from trio_kit.preset import (
    Preset,
    PresetError,
    PresetLibrary,
    PresetWarning,
    load_preset,
    parse_preset,
    save_preset,
    serialize_preset,
)


def make_registry() -> ParamRegistry:
    return ParamRegistry(
        (
            ParamSpec("amp.level", "Level", "dB", -60, 6, 0),
            ParamSpec("filter.cutoff", "Cutoff", "Hz", 20, 20000, 440, curve="log"),
            ParamSpec("voice.mode", "Mode", "", 0, 2, 1, kind="choice", choices=("Soft", "Bright", "Noise")),
        )
    )


def make_preset(
    preset_id: str = "test-pad",
    name: str = "Test Pad",
    *,
    synth: str = "aurora",
    params: dict[str, int | float] | None = None,
    extras: dict[str, Any] | None = None,
    tags: tuple[str, ...] = ("pad",),
) -> Preset:
    return Preset(synth, preset_id, name, params or {"amp.level": -12}, extras or {"harmonics": [1.0, 0.5]}, tags)


def make_document(**updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": "trio-preset/1",
        "synth": "aurora",
        "id": "test-pad",
        "name": "Test Pad",
        "params": {"amp.level": -12},
        "extras": {"harmonics": [1.0, 0.5]},
        "tags": ["pad"],
    }
    document.update(updates)
    return document


def test_valid_preset_fills_defaults_and_round_trips() -> None:
    preset = parse_preset(json.dumps(make_document()), "aurora", make_registry())

    assert preset.id == "test-pad"
    assert preset.schema == "trio-preset/1"
    assert preset.params == {"amp.level": -12, "filter.cutoff": 440, "voice.mode": 1}
    assert preset.extras == {"harmonics": [1.0, 0.5]}
    assert preset.tags == ("pad",)
    assert parse_preset(serialize_preset(preset), "aurora", make_registry()) == preset


def test_unknown_parameters_warn_and_are_ignored() -> None:
    document = make_document(params={"amp.level": -4, "old.param": 1})

    with pytest.warns(PresetWarning, match="old.param"):
        preset = parse_preset(document, "aurora", make_registry())

    assert "old.param" not in preset.params
    assert preset.params["amp.level"] == -4


@pytest.mark.parametrize(
    "document",
    (
        make_document(synth="loom"),
        make_document(id="bad_id"),
        make_document(name=""),
        make_document(schema="trio-preset/2"),
        make_document(params=[]),
        make_document(extras=[]),
        make_document(tags="pad"),
        make_document(name=5),
        make_document(name="\ud800"),
        make_document(unknown="field"),
        {"schema": "trio-preset/1"},
    ),
)
def test_invalid_preset_structure_returns_preset_error(document: object) -> None:
    with pytest.raises(PresetError):
        parse_preset(document, "aurora", make_registry())  # type: ignore[arg-type]


def test_wrong_registry_type_is_a_preset_error() -> None:
    with pytest.raises(PresetError, match="registry"):
        parse_preset(make_document(), "aurora", object())  # type: ignore[arg-type]


@pytest.mark.parametrize("root", ([], None, 1, "not a preset"))
def test_non_object_json_roots_are_rejected(root: object) -> None:
    with pytest.raises(PresetError, match="root"):
        parse_preset(json.dumps(root), "aurora", make_registry())


@pytest.mark.parametrize("value", (True, "1", None, float("nan"), float("inf"), float("-inf"), 10**1000))
def test_invalid_parameter_values_preserve_param_error(value: object) -> None:
    document = make_document(params={"amp.level": value})

    with pytest.raises(ParamError, match="amp.level"):
        parse_preset(document, "aurora", make_registry())


def test_non_finite_parameter_constants_in_json_keep_the_parameter_key() -> None:
    raw = json.dumps(make_document(params={"amp.level": float("nan")}))
    with pytest.raises(ParamError, match="amp.level"):
        parse_preset(raw, "aurora", make_registry())


@pytest.mark.parametrize(
    "raw",
    (
        b"\xff",
        b'{"schema":"trio-preset/1","schema":"trio-preset/1"}',
        b'{"schema":"trio-preset/1","synth":"aurora","id":"test-pad","name":"Pad","params":{},"extras":{"bad":NaN}}',
    ),
)
def test_corrupt_encoding_duplicate_fields_and_non_json_constants_are_rejected(raw: bytes) -> None:
    with pytest.raises(PresetError):
        parse_preset(raw, "aurora", make_registry())


def test_oversized_documents_are_rejected() -> None:
    too_large = b" " * (256 * 1024 + 1)

    with pytest.raises(PresetError, match="exceeds"):
        parse_preset(too_large, "aurora", make_registry())


def test_deep_documents_are_rejected_before_ui_consumption() -> None:
    nested: object = "leaf"
    for _ in range(17):
        nested = [nested]
    document = make_document(extras={"deep": nested})

    with pytest.raises(PresetError, match="nesting"):
        parse_preset(document, "aurora", make_registry())


def test_document_at_the_supported_container_depth_is_accepted() -> None:
    nested: object = "leaf"
    for _ in range(14):
        nested = [nested]
    document = make_document(extras={"deep": nested})

    preset = parse_preset(document, "aurora", make_registry())
    assert preset.id == "test-pad"


def test_cyclic_and_oversized_objects_are_rejected() -> None:
    extras: dict[str, Any] = {}
    extras["self"] = extras
    with pytest.raises(PresetError, match="cyclic"):
        parse_preset(make_document(extras=extras), "aurora", make_registry())

    oversized = make_preset(extras={"payload": "x" * (256 * 1024)})
    with pytest.raises(PresetError, match="exceeds"):
        serialize_preset(oversized)


def test_extras_validator_can_validate_or_normalize_data() -> None:
    document = make_document(extras={"harmonics": [1, 0.5]})

    def normalize(extras: dict[str, Any]) -> None:
        extras["validated"] = True

    preset = parse_preset(document, "aurora", make_registry(), normalize)
    assert preset.extras == {"harmonics": [1, 0.5], "validated": True}

    with pytest.raises(PresetError, match="instrument extras"):
        parse_preset(document, "aurora", make_registry(), lambda extras: (_ for _ in ()).throw(ValueError("bad harmonics")))

    with pytest.raises(PresetError, match="return an object"):
        parse_preset(document, "aurora", make_registry(), lambda extras: [1, 2])  # type: ignore[arg-type]


def test_preset_creation_rejects_non_numeric_parameter_data() -> None:
    with pytest.raises(PresetError, match="finite number"):
        Preset("aurora", "test-pad", "Test", {"amp.level": True})
    with pytest.raises(PresetError, match="tags"):
        Preset("aurora", "test-pad", "Test", {}, tags="pad")  # type: ignore[arg-type]


def test_load_preset_wraps_file_errors_and_reads_utf8(tmp_path: Path) -> None:
    path = tmp_path / "preset.json"
    save_preset(path, make_preset())
    assert load_preset(path, "aurora", make_registry()).name == "Test Pad"
    path.write_bytes(b"\xff")
    with pytest.raises(PresetError, match="UTF-8"):
        load_preset(path, "aurora", make_registry())
    with pytest.raises(PresetError, match="could not read"):
        load_preset(tmp_path / "missing.json", "aurora", make_registry())


def test_save_is_atomic_and_refuses_overwrite_by_default(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "test-pad.json"
    save_preset(path, make_preset())
    original = path.read_bytes()
    assert not list(path.parent.glob("*.tmp"))

    with pytest.raises(PresetError, match="already exists"):
        save_preset(path, make_preset(name="Changed"))
    assert path.read_bytes() == original

    save_preset(path, make_preset(name="Changed"), overwrite=True)
    assert load_preset(path, "aurora", make_registry()).name == "Changed"
    assert not list(path.parent.glob("*.tmp"))


def write_factory(directory: Path, *presets: Preset) -> None:
    for preset in presets:
        save_preset(directory / f"{preset.id}.json", preset)


def test_factory_and_user_presets_merge_in_stable_id_order(tmp_path: Path) -> None:
    factory_dir = tmp_path / "package" / "data" / "presets"
    write_factory(factory_dir, make_preset("zeta"), make_preset("alpha"))
    library = PresetLibrary("aurora", make_registry(), data_dir=tmp_path / "data", factory_dir=factory_dir)
    assert library.user_dir == tmp_path / "data" / "aurora"

    library.save(make_preset("custom"))
    assert [preset.id for preset in library.list_presets()] == ["alpha", "custom", "zeta"]
    assert library.get("custom").name == "Test Pad"
    library.delete("custom")
    assert [preset.id for preset in library.list_presets()] == ["alpha", "zeta"]


def test_factory_presets_load_from_package_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "fixture_synth"
    preset_dir = package / "data" / "presets"
    preset_dir.mkdir(parents=True)
    (package / "__init__.py").write_text("\"\"\"Fixture resource package.\"\"\"\n", encoding="utf-8")
    save_preset(preset_dir / "factory.json", make_preset("factory"))
    monkeypatch.syspath_prepend(str(tmp_path))

    library = PresetLibrary("aurora", make_registry(), data_dir=tmp_path / "user", factory_package="fixture_synth")
    assert [preset.id for preset in library.list_presets()] == ["factory"]


def test_factory_preset_is_read_only_until_explicitly_shadowed(tmp_path: Path) -> None:
    factory_dir = tmp_path / "factory"
    factory = make_preset("factory", "Factory Name")
    write_factory(factory_dir, factory)
    library = PresetLibrary("aurora", make_registry(), data_dir=tmp_path / "data", factory_dir=factory_dir)
    library.user_dir.mkdir(parents=True)
    save_preset(library.user_dir / "factory.json", make_preset("factory", "Unapproved Shadow"))

    assert library.get("factory").name == "Factory Name"
    with pytest.raises(PresetError, match="cannot be deleted"):
        library.delete("factory")
    with pytest.raises(PresetError, match="overwrite=True"):
        library.save(make_preset("factory", "User Name"))

    library.save(make_preset("factory", "User Name"), overwrite=True)
    assert library.get("factory").name == "User Name"
    assert library.get("factory").params["filter.cutoff"] == 440
    library.delete("factory")
    assert library.get("factory").name == "Factory Name"


def test_user_overwrite_requires_explicit_opt_in(tmp_path: Path) -> None:
    library = PresetLibrary("aurora", make_registry(), data_dir=tmp_path)
    library.save(make_preset("custom", "First"))

    with pytest.raises(PresetError, match="overwrite=True"):
        library.save(make_preset("custom", "Second"))
    library.save(make_preset("custom", "Second"), overwrite=True)
    assert library.get("custom").name == "Second"


def test_rename_moves_user_presets_and_copies_factory_presets(tmp_path: Path) -> None:
    factory_dir = tmp_path / "factory"
    write_factory(factory_dir, make_preset("factory", "Factory"))
    library = PresetLibrary("aurora", make_registry(), data_dir=tmp_path / "data", factory_dir=factory_dir)
    library.save(make_preset("old-name", "User"))

    renamed = library.rename("old-name", "new-name", name="Renamed User")
    assert renamed.id == "new-name"
    assert renamed.name == "Renamed User"
    with pytest.raises(PresetError, match="was not found"):
        library.get("old-name")
    factory_copy = library.rename("factory", "factory-copy")
    assert factory_copy.id == "factory-copy"
    assert library.get("factory").name == "Factory"


def test_corrupt_override_index_is_reported_as_preset_error(tmp_path: Path) -> None:
    library = PresetLibrary("aurora", make_registry(), data_dir=tmp_path)
    library.user_dir.mkdir(parents=True)
    (library.user_dir / ".factory-overrides.json").write_text("[]", encoding="utf-8")

    with pytest.raises(PresetError, match="override index"):
        library.list_presets()
