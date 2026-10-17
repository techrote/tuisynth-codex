"""Shared foundation for the AURORA, LOOM, and DRIFT synthesizers."""

from trio_kit.params import ParamError, ParamRegistry, ParamSpec, ParamWarning
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
from trio_kit.userdata import get_user_data_dir

__version__ = "0.1.0"

__all__ = [
    "ParamError",
    "ParamRegistry",
    "ParamSpec",
    "ParamWarning",
    "Preset",
    "PresetError",
    "PresetLibrary",
    "PresetWarning",
    "get_user_data_dir",
    "load_preset",
    "parse_preset",
    "save_preset",
    "serialize_preset",
]
