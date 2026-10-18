"""Persistent, atomic MIDI controller-learn bindings."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import warnings
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from trio_kit.events import ControlChange
from trio_kit.userdata import get_user_data_dir


_SCHEMA = "trio-midi-map/1"
_MAX_FILE_BYTES = 64 * 1024
_MAX_CONTROL_ID_LENGTH = 128


class MidiMapWarning(UserWarning):
    """A MIDI learn map could not be read or persisted safely."""


class CcLearnMap:
    """Arm a parameter key and bind it to the next incoming CC message."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).expanduser()
        self._bindings = self._load()
        self._armed: str | None = None
        self._lock = threading.RLock()

    @classmethod
    def for_instrument(
        cls,
        instrument: str,
        *,
        data_dir: str | os.PathLike[str] | None = None,
    ) -> CcLearnMap:
        """Use this instrument's standard user-data location."""
        return cls(get_user_data_dir(instrument, data_dir) / "midi-map.json")

    @property
    def bindings(self) -> Mapping[str, int]:
        with self._lock:
            return MappingProxyType(dict(self._bindings))

    @property
    def armed_control(self) -> str | None:
        with self._lock:
            return self._armed

    @staticmethod
    def _valid_control_id(value: object) -> bool:
        return (
            isinstance(value, str)
            and 0 < len(value.strip()) <= _MAX_CONTROL_ID_LENGTH
            and value == value.strip()
            and value.isascii()
            and all(character.isprintable() for character in value)
        )

    @staticmethod
    def _valid_cc(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 127

    def _load(self) -> dict[str, int]:
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(_MAX_FILE_BYTES + 1)
        except FileNotFoundError:
            return {}
        except OSError as error:
            warnings.warn(f"cannot read MIDI learn map {self.path}: {error}; using an empty map", MidiMapWarning, stacklevel=2)
            return {}

        try:
            if len(raw) > _MAX_FILE_BYTES:
                raise ValueError("file exceeds 64 KiB")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("schema") != _SCHEMA:
                raise ValueError("unsupported MIDI map schema")
            bindings = payload.get("bindings")
            if not isinstance(bindings, dict) or len(bindings) > 512:
                raise ValueError("bindings must be an object containing at most 512 entries")
            normalized: dict[str, int] = {}
            for control_id, cc in bindings.items():
                if not self._valid_control_id(control_id) or not self._valid_cc(cc):
                    raise ValueError("bindings contain an invalid control id or CC number")
                normalized[control_id] = cc
            return normalized
        except (UnicodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError) as error:
            warnings.warn(f"invalid MIDI learn map {self.path}: {error}; using an empty map", MidiMapWarning, stacklevel=2)
            return {}

    def arm(self, control_id: str) -> None:
        if not self._valid_control_id(control_id):
            raise ValueError("control_id must be a non-empty string of at most 128 characters")
        with self._lock:
            self._armed = control_id

    def disarm(self) -> None:
        with self._lock:
            self._armed = None

    def feed(self, change: ControlChange | int, value: int | None = None) -> bool:
        """Bind the armed control to a raw CC number or `ControlChange`."""
        if isinstance(change, ControlChange):
            if value is not None:
                raise ValueError("value must be omitted when feeding a ControlChange")
            cc = change.cc
        else:
            cc = change
            if value is not None and not self._valid_cc(value):
                raise ValueError("CC value must be an integer in the range 0..127")
        if not self._valid_cc(cc):
            raise ValueError("CC number must be an integer in the range 0..127")
        with self._lock:
            if self._armed is None:
                return False
            control_id = self._armed
            if control_id not in self._bindings and len(self._bindings) >= 512:
                self._armed = None
                warnings.warn(
                    "MIDI learn map already contains 512 bindings; new binding was not saved",
                    MidiMapWarning,
                    stacklevel=2,
                )
                return False
            self._bindings[control_id] = cc
            self._armed = None
            self._save()
            return True

    def lookup(self, control_id: str) -> int | None:
        if not self._valid_control_id(control_id):
            raise ValueError("control_id must be a non-empty string of at most 128 characters")
        with self._lock:
            return self._bindings.get(control_id)

    def clear(self, control_id: str | None = None) -> bool:
        """Clear one binding, or all bindings when no id is supplied."""
        with self._lock:
            if control_id is None:
                changed = bool(self._bindings)
                self._bindings.clear()
                self._armed = None
            else:
                if not self._valid_control_id(control_id):
                    raise ValueError("control_id must be a non-empty string of at most 128 characters")
                changed = self._bindings.pop(control_id, None) is not None
                if self._armed == control_id:
                    self._armed = None
                    changed = True
            if changed:
                self._save()
            return changed

    def _save(self) -> None:
        temporary: str | None = None
        try:
            serialized = json.dumps(
                {"schema": _SCHEMA, "bindings": self._bindings},
                ensure_ascii=True,
                sort_keys=True,
            ) + "\n"
            if len(serialized.encode("utf-8")) > _MAX_FILE_BYTES:
                warnings.warn(f"MIDI learn map {self.path} exceeds 64 KiB; changes remain in memory", MidiMapWarning, stacklevel=2)
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            warnings.warn(f"cannot save MIDI learn map {self.path}: {error}", MidiMapWarning, stacklevel=2)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass


__all__ = ["CcLearnMap", "MidiMapWarning"]
