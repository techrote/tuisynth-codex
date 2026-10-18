"""Schema-versioned factory and user preset handling."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from importlib import resources
from numbers import Real
from pathlib import Path
from types import MappingProxyType
from typing import Any

from trio_kit.params import ParamRegistry
from trio_kit.userdata import get_user_data_dir


PRESET_SCHEMA = "trio-preset/1"
_OVERRIDE_SCHEMA = "trio-preset-overrides/1"
_MAX_PRESET_BYTES = 256 * 1024
_MAX_JSON_DEPTH = 16
_PRESET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_SYNTH_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
ExtraValidator = Callable[[dict[str, Any]], Mapping[str, Any] | None]


class PresetError(ValueError):
    """A malformed, invalid, or unavailable preset operation."""


class PresetWarning(UserWarning):
    """A preset contains parameters that the current instrument does not use."""


def validate_preset_id(preset_id: object) -> str:
    if not isinstance(preset_id, str) or not _PRESET_ID_RE.fullmatch(preset_id):
        raise PresetError("preset id must match ^[a-z0-9][a-z0-9-]{0,47}$")
    return preset_id


def _validate_json_tree(
    value: object,
    *,
    maximum_depth: int = _MAX_JSON_DEPTH,
    finite_numbers: bool = True,
) -> None:
    """Reject non-JSON data, non-finite numbers, and overly deep structures."""
    stack: list[tuple[object, int, bool]] = [(value, 1, False)]
    active_containers: set[int] = set()
    visited_nodes = 0
    while stack:
        current, depth, exiting = stack.pop()
        if exiting:
            active_containers.remove(id(current))
            continue
        visited_nodes += 1
        if visited_nodes > 100_000:
            raise PresetError("preset structure is too large")
        if current is None or isinstance(current, bool):
            continue
        if isinstance(current, str):
            try:
                current.encode("utf-8")
            except UnicodeEncodeError as error:
                raise PresetError("strings must contain valid UTF-8 text") from error
            continue
        if isinstance(current, int):
            if finite_numbers:
                try:
                    finite = math.isfinite(float(current))
                except (OverflowError, ValueError):
                    finite = False
                if not finite:
                    raise PresetError("numbers must be finite")
            continue
        if isinstance(current, float):
            if finite_numbers and not math.isfinite(current):
                raise PresetError("non-finite numbers are not valid preset data")
            continue
        if isinstance(current, Mapping):
            if depth > maximum_depth:
                raise PresetError(f"JSON nesting exceeds {maximum_depth} levels")
            identity = id(current)
            if identity in active_containers:
                raise PresetError("cyclic mappings are not valid JSON preset data")
            active_containers.add(identity)
            stack.append((current, depth, True))
            try:
                for key, child in current.items():
                    if not isinstance(key, str):
                        raise PresetError("JSON object keys must be strings")
                    try:
                        key.encode("utf-8")
                    except UnicodeEncodeError as error:
                        raise PresetError("JSON object keys must contain valid UTF-8 text") from error
                    stack.append((child, depth + 1, False))
            except PresetError:
                raise
            except Exception as error:
                raise PresetError("JSON object could not be read") from error
            continue
        if isinstance(current, list):
            if depth > maximum_depth:
                raise PresetError(f"JSON nesting exceeds {maximum_depth} levels")
            identity = id(current)
            if identity in active_containers:
                raise PresetError("cyclic lists are not valid JSON preset data")
            active_containers.add(identity)
            stack.append((current, depth, True))
            stack.extend((child, depth + 1, False) for child in current)
            continue
        raise PresetError(f"{type(current).__name__} is not valid JSON preset data")


def _parse_json_constant(value: str) -> float:
    # Preserve invalid JSON numeric constants long enough for a parameter field
    # to report a keyed ParamError. Strict non-parameter fields still reject them.
    return {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}[value]


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class Preset:
    """A validated preset document with normalized parameter defaults."""

    synth: str
    id: str
    name: str
    params: Mapping[str, int | float]
    extras: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.synth, str) or not _SYNTH_RE.fullmatch(self.synth):
            raise PresetError("synth must be a lowercase instrument identifier")
        validate_preset_id(self.id)
        if not isinstance(self.name, str) or not self.name.strip():
            raise PresetError("preset name must be a non-empty string")
        if not isinstance(self.description, str) or len(self.description) > 512:
            raise PresetError("preset description must be a string of at most 512 characters")
        if not isinstance(self.params, Mapping):
            raise PresetError("params must be an object")
        if not isinstance(self.extras, Mapping):
            raise PresetError("extras must be an object")
        try:
            params = dict(self.params)
            extras = dict(self.extras)
        except (TypeError, ValueError) as error:
            raise PresetError("preset fields have invalid structure") from error
        if isinstance(self.tags, str):
            raise PresetError("tags must be a sequence of strings")
        try:
            tags = tuple(self.tags)
        except TypeError as error:
            raise PresetError("tags must be a sequence of strings") from error
        for key, value in params.items():
            if not isinstance(key, str):
                raise PresetError("parameter keys must be strings")
            if isinstance(value, bool) or not isinstance(value, Real):
                raise PresetError(f"parameter {key!r} must be a finite number")
            try:
                finite = math.isfinite(float(value))
            except (OverflowError, ValueError):
                finite = False
            if not finite:
                raise PresetError(f"parameter {key!r} must be a finite number")
        _validate_json_tree(params)
        _validate_json_tree(extras)
        if any(not isinstance(tag, str) for tag in tags):
            raise PresetError("tags must be a list of strings")
        object.__setattr__(self, "params", MappingProxyType(params))
        object.__setattr__(self, "extras", MappingProxyType(extras))
        object.__setattr__(self, "tags", tags)

    @property
    def schema(self) -> str:
        return PRESET_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        document = {
            "schema": PRESET_SCHEMA,
            "synth": self.synth,
            "id": self.id,
            "name": self.name,
            "params": dict(self.params),
            "extras": dict(self.extras),
            "tags": list(self.tags),
        }
        if self.description:
            document["description"] = self.description
        return document

    def to_json(self) -> str:
        return serialize_preset(self)


def _decode_document(data: str | bytes | bytearray) -> object:
    if isinstance(data, str):
        try:
            encoded = data.encode("utf-8")
        except UnicodeEncodeError as error:
            raise PresetError("preset must be valid UTF-8") from error
        if len(encoded) > _MAX_PRESET_BYTES:
            raise PresetError(f"preset exceeds {_MAX_PRESET_BYTES} bytes")
        text = data
    elif isinstance(data, (bytes, bytearray)):
        if len(data) > _MAX_PRESET_BYTES:
            raise PresetError(f"preset exceeds {_MAX_PRESET_BYTES} bytes")
        try:
            text = bytes(data).decode("utf-8")
        except UnicodeDecodeError as error:
            raise PresetError("preset must be valid UTF-8") from error
    else:
        raise PresetError("preset input must be UTF-8 JSON text or an object")
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_parse_json_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError) as error:
        raise PresetError(f"invalid preset JSON: {error}") from error
    _validate_json_tree(decoded, finite_numbers=False)
    return decoded


def parse_preset(
    data: str | bytes | bytearray | Mapping[str, Any],
    synth: str,
    registry: ParamRegistry,
    extras_validator: ExtraValidator | None = None,
) -> Preset:
    """Parse and validate one ``trio-preset/1`` JSON document."""
    if not isinstance(synth, str) or not _SYNTH_RE.fullmatch(synth):
        raise PresetError("synth must be a lowercase instrument identifier")
    if not isinstance(registry, ParamRegistry):
        raise PresetError("registry must be a ParamRegistry")
    if isinstance(data, (str, bytes, bytearray)):
        document = _decode_document(data)
    elif isinstance(data, Mapping):
        try:
            document = dict(data)
        except Exception as error:
            raise PresetError("preset object could not be read") from error
        _validate_json_tree(document, finite_numbers=False)
        try:
            encoded_size = len(json.dumps(document, ensure_ascii=False, allow_nan=True).encode("utf-8"))
        except (TypeError, ValueError, RecursionError) as error:
            raise PresetError(f"invalid preset object: {error}") from error
        if encoded_size > _MAX_PRESET_BYTES:
            raise PresetError(f"preset exceeds {_MAX_PRESET_BYTES} bytes")
    else:
        raise PresetError("preset input must be UTF-8 JSON text or an object")
    if not isinstance(document, dict):
        raise PresetError("preset root must be an object")

    required = {"schema", "synth", "id", "name", "params"}
    missing = required - document.keys()
    if missing:
        raise PresetError(f"preset is missing required field {sorted(missing)[0]!r}")
    allowed = required | {"extras", "tags", "description"}
    unknown_fields = document.keys() - allowed
    if unknown_fields:
        raise PresetError(f"unknown top-level field {sorted(unknown_fields)[0]!r}")
    if document["schema"] != PRESET_SCHEMA:
        raise PresetError(f"schema must be {PRESET_SCHEMA!r}")
    if document["synth"] != synth:
        raise PresetError(f"preset synth {document['synth']!r} does not match {synth!r}")
    preset_id = validate_preset_id(document["id"])
    name = document["name"]
    if not isinstance(name, str) or not name.strip():
        raise PresetError("preset name must be a non-empty string")

    raw_params = document["params"]
    if not isinstance(raw_params, dict):
        raise PresetError("params must be an object")
    if any(not isinstance(key, str) for key in raw_params):
        raise PresetError("parameter keys must be strings")
    params = registry.defaults()
    for key, value in raw_params.items():
        if key not in registry.specs:
            _validate_json_tree(value)
            warnings.warn(f"preset contains unknown parameter {key!r}; ignored", PresetWarning, stacklevel=2)
            continue
        params[key] = registry.validate_value(key, value)

    extras = document.get("extras", {})
    if not isinstance(extras, dict):
        raise PresetError("extras must be an object")
    if extras_validator is not None:
        try:
            extras_candidate = dict(extras)
            validated_extras = extras_validator(extras_candidate)
        except Exception as error:
            raise PresetError(f"invalid instrument extras: {error}") from error
        if validated_extras is None:
            extras = extras_candidate
        else:
            if not isinstance(validated_extras, Mapping):
                raise PresetError("extras validator must return an object or None")
            try:
                extras = dict(validated_extras)
            except Exception as error:
                raise PresetError(f"invalid instrument extras: {error}") from error
    _validate_json_tree(extras)

    tags = document.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise PresetError("tags must be a list of strings")
    description = document.get("description", "")
    if not isinstance(description, str) or len(description) > 512:
        raise PresetError("description must be a string of at most 512 characters")
    return Preset(
        synth=synth,
        id=preset_id,
        name=name,
        params=params,
        extras=extras,
        tags=tuple(tags),
        description=description,
    )


def load_preset(
    path: str | os.PathLike[str],
    synth: str,
    registry: ParamRegistry,
    extras_validator: ExtraValidator | None = None,
) -> Preset:
    """Read and validate one UTF-8 preset file."""
    try:
        target = Path(path)
        if target.stat().st_size > _MAX_PRESET_BYTES:
            raise PresetError(f"preset exceeds {_MAX_PRESET_BYTES} bytes")
        data = target.read_bytes()
    except PresetError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise PresetError(f"could not read preset {path!s}: {error}") from error
    return parse_preset(data, synth, registry, extras_validator)


def serialize_preset(preset: Preset) -> str:
    """Serialize a preset as UTF-8-compatible, stable JSON text."""
    if not isinstance(preset, Preset):
        raise PresetError("expected a Preset instance")
    document = preset.to_dict()
    _validate_json_tree(document)
    try:
        result = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    except (TypeError, ValueError, RecursionError) as error:
        raise PresetError(f"could not serialize preset: {error}") from error
    if len(result.encode("utf-8")) > _MAX_PRESET_BYTES:
        raise PresetError(f"preset exceeds {_MAX_PRESET_BYTES} bytes")
    return result


def _atomic_write(path: Path, content: bytes, *, overwrite: bool) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    except FileExistsError as error:
        raise PresetError(f"preset file already exists: {path}") from error
    except OSError as error:
        raise PresetError(f"could not save preset {path}: {error}") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def save_preset(path: str | os.PathLike[str], preset: Preset, *, overwrite: bool = False) -> Path:
    """Atomically write a preset, refusing an existing file by default."""
    if not isinstance(overwrite, bool):
        raise PresetError("overwrite must be a boolean")
    try:
        target = Path(path)
    except (TypeError, ValueError) as error:
        raise PresetError(f"invalid preset path: {error}") from error
    _atomic_write(target, serialize_preset(preset).encode("utf-8"), overwrite=overwrite)
    return target


class PresetLibrary:
    """Merge packaged factory presets with per-instrument user presets."""

    def __init__(
        self,
        synth: str,
        registry: ParamRegistry,
        *,
        data_dir: str | os.PathLike[str] | None = None,
        factory_package: str | None = None,
        factory_dir: Any | None = None,
        extras_validator: ExtraValidator | None = None,
    ) -> None:
        if not isinstance(synth, str) or not _SYNTH_RE.fullmatch(synth):
            raise PresetError("synth must be a lowercase instrument identifier")
        if not isinstance(registry, ParamRegistry):
            raise PresetError("registry must be a ParamRegistry")
        if factory_package is not None and not isinstance(factory_package, str):
            raise PresetError("factory_package must be a package name string")
        self.synth = synth
        self.registry = registry
        self.user_dir = get_user_data_dir(synth, data_dir)
        self.factory_package = factory_package
        self.factory_dir = factory_dir
        self.extras_validator = extras_validator

    def _factory_directory(self) -> Any | None:
        if self.factory_dir is not None:
            return self.factory_dir
        if self.factory_package is None:
            return None
        try:
            return resources.files(self.factory_package).joinpath("data", "presets")
        except (ModuleNotFoundError, TypeError) as error:
            raise PresetError(f"could not access factory presets in {self.factory_package!r}") from error

    def _load_directory(self, directory: Any | None, *, factory: bool) -> dict[str, Preset]:
        if directory is None:
            return {}
        try:
            if not directory.is_dir():
                return {}
        except OSError as error:
            raise PresetError(f"could not inspect preset directory {directory}: {error}") from error
        presets: dict[str, Preset] = {}
        try:
            entries = sorted(
                (
                    entry
                    for entry in directory.iterdir()
                    if entry.is_file()
                    and entry.name.lower().endswith(".json")
                    and (factory or entry.name.lower() != ".factory-overrides.json")
                ),
                key=lambda entry: entry.name,
            )
        except OSError as error:
            raise PresetError(f"could not list preset directory {directory}: {error}") from error
        for entry in entries:
            try:
                preset_data = entry.read_bytes()
            except OSError as error:
                raise PresetError(f"could not read preset {entry}: {error}") from error
            preset = parse_preset(preset_data, self.synth, self.registry, self.extras_validator)
            if not factory and entry.stem != preset.id:
                raise PresetError(f"user preset filename {entry.name!r} must match its id")
            if preset.id in presets:
                raise PresetError(f"duplicate preset id {preset.id!r} in {directory}")
            presets[preset.id] = preset
        return presets

    def _factory_presets(self) -> dict[str, Preset]:
        return self._load_directory(self._factory_directory(), factory=True)

    def _override_file(self) -> Path:
        return self.user_dir / ".factory-overrides.json"

    def _override_ids(self) -> set[str]:
        path = self._override_file()
        if not path.exists():
            return set()
        try:
            data = path.read_bytes()
            document = _decode_document(data)
        except OSError as error:
            raise PresetError(f"could not read factory override index: {error}") from error
        if not isinstance(document, dict) or set(document) != {"schema", "ids"}:
            raise PresetError("factory override index is malformed")
        if document["schema"] != _OVERRIDE_SCHEMA or not isinstance(document["ids"], list):
            raise PresetError("factory override index has an unsupported schema")
        ids: set[str] = set()
        for preset_id in document["ids"]:
            validated = validate_preset_id(preset_id)
            if validated in ids:
                raise PresetError("factory override index contains duplicate ids")
            ids.add(validated)
        return ids

    def _write_override_ids(self, ids: set[str]) -> None:
        path = self._override_file()
        if not ids:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                raise PresetError(f"could not update factory override index: {error}") from error
            return
        payload = json.dumps({"schema": _OVERRIDE_SCHEMA, "ids": sorted(ids)}, indent=2).encode("utf-8") + b"\n"
        _atomic_write(path, payload, overwrite=True)

    def list_presets(self) -> tuple[Preset, ...]:
        factory = self._factory_presets()
        users = self._load_directory(self.user_dir, factory=False)
        overrides = self._override_ids()
        merged = dict(factory)
        for preset_id, preset in users.items():
            if preset_id not in factory or preset_id in overrides:
                merged[preset_id] = preset
        return tuple(merged[preset_id] for preset_id in sorted(merged))

    def list_factory_presets(self) -> tuple[Preset, ...]:
        """Return the packaged presets only, without user overrides or user-data reads."""
        factory = self._factory_presets()
        return tuple(factory[preset_id] for preset_id in sorted(factory))

    def get(self, preset_id: str) -> Preset:
        preset_id = validate_preset_id(preset_id)
        for preset in self.list_presets():
            if preset.id == preset_id:
                return preset
        raise PresetError(f"preset {preset_id!r} was not found")

    def save(self, preset: Preset, *, overwrite: bool = False) -> Path:
        if not isinstance(preset, Preset):
            raise PresetError("expected a Preset instance")
        if preset.synth != self.synth:
            raise PresetError(f"preset synth {preset.synth!r} does not match {self.synth!r}")
        if not isinstance(overwrite, bool):
            raise PresetError("overwrite must be a boolean")
        normalized = parse_preset(preset.to_dict(), self.synth, self.registry, self.extras_validator)
        factory = self._factory_presets()
        target = self.user_dir / f"{normalized.id}.json"
        overrides = self._override_ids() if normalized.id in factory else set()
        if (target.exists() or normalized.id in factory) and not overwrite:
            raise PresetError(f"preset {normalized.id!r} already exists; pass overwrite=True to replace it")
        saved_path = save_preset(target, normalized, overwrite=overwrite)
        if normalized.id in factory:
            overrides.add(normalized.id)
            self._write_override_ids(overrides)
        return saved_path

    def rename(self, old_id: str, new_id: str, *, name: str | None = None, overwrite: bool = False) -> Preset:
        old_id = validate_preset_id(old_id)
        new_id = validate_preset_id(new_id)
        if old_id == new_id:
            raise PresetError("new preset id must differ from old id")
        original = self.get(old_id)
        renamed = replace(original, id=new_id, name=name if name is not None else original.name)
        self.save(renamed, overwrite=overwrite)
        old_path = self.user_dir / f"{old_id}.json"
        if old_path.exists():
            self.delete(old_id)
        return renamed

    def delete(self, preset_id: str) -> None:
        preset_id = validate_preset_id(preset_id)
        factory = self._factory_presets()
        overrides = self._override_ids()
        user_path = self.user_dir / f"{preset_id}.json"
        if preset_id in factory and preset_id not in overrides:
            raise PresetError(f"factory preset {preset_id!r} cannot be deleted")
        if not user_path.exists():
            if preset_id in factory:
                raise PresetError(f"factory preset {preset_id!r} cannot be deleted")
            raise PresetError(f"user preset {preset_id!r} was not found")
        try:
            user_path.unlink()
        except OSError as error:
            raise PresetError(f"could not delete preset {preset_id!r}: {error}") from error
        if preset_id in overrides:
            overrides.remove(preset_id)
            self._write_override_ids(overrides)
