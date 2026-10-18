"""Validated factory preset access for LOOM."""

from __future__ import annotations

from importlib.resources import files

from trio_kit.preset import Preset, parse_preset
from trio_loom.params import loom_registry


def load_factory_presets() -> tuple[Preset, ...]:
    """Load all packaged presets through the shared strict preset validator."""
    root = files("trio_loom").joinpath("data", "presets")
    registry = loom_registry()
    presets = tuple(
        parse_preset(path.read_text(encoding="utf-8"), "loom", registry)
        for path in sorted(root.iterdir(), key=lambda item: item.name)
        if path.name.endswith(".json")
    )
    if len(presets) < 8:
        raise RuntimeError("LOOM must package at least eight factory presets")
    return presets


def load_factory_preset(preset_id: str) -> Preset:
    for preset in load_factory_presets():
        if preset.id == preset_id:
            return preset
    raise KeyError(f"unknown LOOM factory preset {preset_id!r}")


__all__ = ["load_factory_preset", "load_factory_presets"]
