"""Shared audio engine components, loaded lazily to keep optional backends separate."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "Engine": ("trio_kit.engine.engine", "Engine"),
    "EngineTelemetry": ("trio_kit.engine.engine", "EngineTelemetry"),
    "OfflineEngine": ("trio_kit.engine.engine", "OfflineEngine"),
    "MasterBus": ("trio_kit.engine.master", "MasterBus"),
    "VoiceManager": ("trio_kit.engine.voices", "VoiceManager"),
    "NullBackend": ("trio_kit.engine.backend", "NullBackend"),
    "SoundDeviceBackend": ("trio_kit.engine.backend", "SoundDeviceBackend"),
    "open_backend": ("trio_kit.engine.backend", "open_backend"),
    "Instrument": ("trio_kit.engine.protocols", "Instrument"),
    "Voice": ("trio_kit.engine.protocols", "Voice"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module = import_module(target[0])
    value = getattr(module, target[1])
    globals()[name] = value
    return value
