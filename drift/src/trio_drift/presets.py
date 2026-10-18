"""Validated access to the eight packaged DRIFT factory presets."""

from __future__ import annotations

from importlib.resources import files

from trio_kit.preset import Preset, parse_preset
from trio_drift.params import drift_registry


_IDS = {
    "squall-choir", "desert-flute", "monsoon-breath", "howling-pass",
    "whisper-field", "vowel-sweep", "glass-wind", "deep-exhale",
}


def load_factory_presets() -> tuple[Preset, ...]:
    root = files("trio_drift").joinpath("data", "presets")
    registry = drift_registry()
    presets = tuple(
        parse_preset(path.read_text(encoding="utf-8"), "drift", registry)
        for path in sorted(root.iterdir(), key=lambda item: item.name)
        if path.name.endswith(".json")
    )
    actual = {preset.id for preset in presets}
    if actual != _IDS:
        raise RuntimeError(f"DRIFT factory preset set is incomplete: {sorted(_IDS - actual)}")
    return presets


def load_factory_preset(preset_id: str) -> Preset:
    for preset in load_factory_presets():
        if preset.id == preset_id:
            return preset
    raise KeyError(f"unknown DRIFT factory preset {preset_id!r}")


__all__ = ["load_factory_preset", "load_factory_presets"]
