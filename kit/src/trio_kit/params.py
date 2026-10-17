"""Strict parameter definitions, validation, scaling, and morphing."""

from __future__ import annotations

import math
import re
import threading
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import TypeAlias


ParamValue: TypeAlias = int | float
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_EXP_SCALE = math.expm1(1.0)


class ParamError(ValueError):
    """An invalid parameter specification or value."""

    def __init__(self, key: str, message: str) -> None:
        self.key = key
        super().__init__(f"{key}: {message}" if key else message)


class ParamWarning(UserWarning):
    """A parameter value was clamped or rounded during validation."""


def _number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ParamError(key, "expected a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ParamError(key, "expected a finite number") from error
    if not math.isfinite(result):
        raise ParamError(key, "expected a finite number")
    return result


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """Validated metadata describing one continuous or stepped parameter."""

    key: str
    label: str
    unit: str
    minimum: float
    maximum: float
    default: float
    kind: str = "continuous"
    choices: tuple[str, ...] | None = None
    curve: str = "linear"
    modulatable: bool = False
    group: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not _KEY_RE.fullmatch(self.key):
            raise ParamError("", "key must be a dotted identifier such as 'amp.level'")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ParamError(self.key, "label must be a non-empty string")
        if not isinstance(self.unit, str):
            raise ParamError(self.key, "unit must be a string")
        if not isinstance(self.group, str):
            raise ParamError(self.key, "group must be a string")
        if not isinstance(self.modulatable, bool):
            raise ParamError(self.key, "modulatable must be a boolean")

        minimum = _number(self.minimum, self.key)
        maximum = _number(self.maximum, self.key)
        default = _number(self.default, self.key)
        if minimum >= maximum:
            raise ParamError(self.key, "minimum must be less than maximum")
        if not math.isfinite(maximum - minimum):
            raise ParamError(self.key, "parameter range is too large")
        if not minimum <= default <= maximum:
            raise ParamError(self.key, "default must be within the parameter range")
        if not isinstance(self.kind, str) or self.kind not in {"continuous", "discrete", "choice"}:
            raise ParamError(self.key, "kind must be 'continuous', 'discrete', or 'choice'")
        if not isinstance(self.curve, str) or self.curve not in {"linear", "log", "exp"}:
            raise ParamError(self.key, "curve must be 'linear', 'log', or 'exp'")
        if self.curve == "log" and minimum <= 0:
            raise ParamError(self.key, "log curve requires a positive minimum")

        if self.kind == "choice":
            if not isinstance(self.choices, Sequence) or isinstance(self.choices, str):
                raise ParamError(self.key, "choice parameters require a sequence of labels")
            try:
                choices = tuple(self.choices)
            except TypeError as error:
                raise ParamError(self.key, "choice parameters require a sequence of labels") from error
            if not choices or any(not isinstance(choice, str) or not choice.strip() for choice in choices):
                raise ParamError(self.key, "choice labels must be non-empty strings")
            if len(set(choices)) != len(choices):
                raise ParamError(self.key, "choice labels must be unique")
            if minimum != 0 or maximum != len(choices) - 1:
                raise ParamError(self.key, "choice range must be 0 through len(choices) - 1")
            if not default.is_integer():
                raise ParamError(self.key, "choice default must be an integer index")
            object.__setattr__(self, "choices", choices)
        elif self.choices is not None:
            raise ParamError(self.key, "choices are only valid for choice parameters")

        if self.kind == "discrete" and not all(value.is_integer() for value in (minimum, maximum, default)):
            raise ParamError(self.key, "discrete minimum, maximum, and default must be integers")

    def validate_value(self, value: object) -> ParamValue:
        """Validate a value, warning when it is clamped or rounded."""
        number = _number(value, self.key)
        clamped = min(max(number, float(self.minimum)), float(self.maximum))
        if clamped != number:
            warnings.warn(
                f"{self.key}: {number:g} is outside [{self.minimum:g}, {self.maximum:g}]; clamped to {clamped:g}",
                ParamWarning,
                stacklevel=2,
            )
        if self.kind in {"discrete", "choice"}:
            rounded = math.floor(clamped + 0.5)
            if rounded != clamped:
                warnings.warn(
                    f"{self.key}: {clamped:g} rounded to {rounded}",
                    ParamWarning,
                    stacklevel=2,
                )
            return int(rounded)
        return clamped

    def to_unit(self, value: object) -> float:
        """Convert a parameter value to the normalized 0..1 coordinate."""
        normalized_value = float(self.validate_value(value))
        low = float(self.minimum)
        high = float(self.maximum)
        if self.curve == "linear":
            return (normalized_value - low) / (high - low)
        if self.curve == "log":
            return (math.log(normalized_value) - math.log(low)) / (math.log(high) - math.log(low))
        fraction = (normalized_value - low) / (high - low)
        return math.log1p(fraction * _EXP_SCALE)

    def from_unit(self, unit_value: object) -> ParamValue:
        """Convert a normalized 0..1 coordinate into the parameter domain."""
        unit = _number(unit_value, self.key)
        if not 0.0 <= unit <= 1.0:
            raise ParamError(self.key, "normalized value must be in the range 0..1")
        low = float(self.minimum)
        high = float(self.maximum)
        if self.curve == "linear":
            value = low + unit * (high - low)
        elif self.curve == "log":
            value = math.exp((1.0 - unit) * math.log(low) + unit * math.log(high))
        else:
            value = low + (high - low) * math.expm1(unit) / _EXP_SCALE
        if self.kind in {"discrete", "choice"}:
            return self.validate_value(value)
        return value


class ParamRegistry:
    """An insertion-ordered registry of unique parameter specifications."""

    def __init__(self, specs: Iterable[ParamSpec] = ()) -> None:
        self._specs: dict[str, ParamSpec] = {}
        for spec in specs:
            self.register(spec)

    @property
    def specs(self) -> Mapping[str, ParamSpec]:
        return MappingProxyType(self._specs)

    def register(self, spec: ParamSpec) -> None:
        if not isinstance(spec, ParamSpec):
            raise ParamError("", "registry entries must be ParamSpec instances")
        if spec.key in self._specs:
            raise ParamError(spec.key, "parameter key is already registered")
        self._specs[spec.key] = spec

    def __getitem__(self, key: str) -> ParamSpec:
        if not isinstance(key, str):
            raise ParamError("", "parameter key must be a string")
        try:
            return self._specs[key]
        except KeyError as error:
            raise ParamError(str(key), "unknown parameter") from error

    def __iter__(self) -> Iterator[ParamSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def defaults(self) -> dict[str, ParamValue]:
        return {key: self.validate_value(key, spec.default) for key, spec in self._specs.items()}

    def validate_value(self, key: str, value: object) -> ParamValue:
        return self[key].validate_value(value)

    def clamp(self, key: str, value: object) -> ParamValue:
        """Return a valid parameter value, warning when it is clamped or rounded.

        This is intentionally the same validation path used by presets and
        complete parameter snapshots, so no caller can silently bypass the
        strict type and finite-number checks.
        """
        return self.validate_value(key, value)

    def validate(self, values: Mapping[str, object], *, include_defaults: bool = True) -> dict[str, ParamValue]:
        if not isinstance(values, Mapping):
            raise ParamError("", "parameter values must be a mapping")
        unknown = [key for key in values if key not in self._specs]
        if unknown:
            raise ParamError(str(unknown[0]), "unknown parameter")
        result = self.defaults() if include_defaults else {}
        for key, value in values.items():
            if not isinstance(key, str):
                raise ParamError(str(key), "parameter key must be a string")
            result[key] = self.validate_value(key, value)
        return result

    def to_unit(self, key: str, value: object) -> float:
        return self[key].to_unit(value)

    def from_unit(self, key: str, unit_value: object) -> ParamValue:
        return self[key].from_unit(unit_value)

    def format(self, key: str, value: object) -> str:
        spec = self[key]
        normalized = spec.validate_value(value)
        if spec.kind == "choice":
            assert spec.choices is not None
            return spec.choices[int(normalized)]

        number = float(normalized)
        unit = spec.unit.strip().lower()
        if unit == "hz" and abs(number) >= 1000:
            return f"{_format_number(number / 1000)} kHz"
        if unit == "ms" and abs(number) >= 1000:
            return f"{_format_number(number / 1000)} s"
        if unit in {"%", "percent"}:
            percentage = number * 100 if float(spec.minimum) >= 0 and float(spec.maximum) <= 1 else number
            return f"{_format_number(percentage)}%"
        if unit == "db":
            return f"{_format_number(number)} dB"
        if unit == "cents":
            return f"{_format_number(number)} cents"
        if unit in {"semitones", "semitone", "st"}:
            return f"{_format_number(number)} st"
        if not spec.unit:
            return _format_number(number)
        return f"{_format_number(number)} {spec.unit}"

    def morph(
        self,
        start: Mapping[str, object],
        end: Mapping[str, object],
        amount: object,
    ) -> dict[str, ParamValue]:
        """Interpolate parameter maps; stepped values switch at amount 0.5."""
        t = _number(amount, "morph.t")
        if not 0.0 <= t <= 1.0:
            raise ParamError("morph.t", "morph amount must be in the range 0..1")
        if not isinstance(start, Mapping) or not isinstance(end, Mapping):
            raise ParamError("morph", "both endpoints must be mappings")
        extra_start = set(start) - self._specs.keys()
        extra_end = set(end) - self._specs.keys()
        if extra_start or extra_end:
            unknown = next(iter(extra_start or extra_end))
            raise ParamError(str(unknown), "unknown parameter")

        result: dict[str, ParamValue] = {}
        for key, spec in self._specs.items():
            left = self.validate_value(key, start.get(key, spec.default))
            right = self.validate_value(key, end.get(key, spec.default))
            if t == 0.0:
                result[key] = left
            elif t == 1.0:
                result[key] = right
            elif spec.kind in {"discrete", "choice"}:
                result[key] = left if t < 0.5 else right
            else:
                unit = (1.0 - t) * spec.to_unit(left) + t * spec.to_unit(right)
                result[key] = spec.from_unit(unit)
        return result


def _format_number(value: float) -> str:
    if value == 0:
        return "0"
    rounded = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if rounded == "-0" else rounded


@dataclass(frozen=True, slots=True)
class ParamSnapshot(Mapping[str, ParamValue]):
    """Immutable, versioned values observed coherently by one audio block."""

    _values: Mapping[str, ParamValue]
    version: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise ParamError("", "snapshot version must be a non-negative integer")
        if not isinstance(self._values, Mapping):
            raise ParamError("", "snapshot values must be a mapping")
        values: dict[str, ParamValue] = {}
        for key, value in self._values.items():
            if not isinstance(key, str):
                raise ParamError("", "snapshot parameter keys must be strings")
            normalized = _number(value, key)
            values[key] = int(value) if isinstance(value, int) and not isinstance(value, bool) else normalized
        object.__setattr__(self, "_values", MappingProxyType(values))

    def __getitem__(self, key: str) -> ParamValue:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class ParamState:
    """Thread-safe publisher of complete immutable parameter snapshots."""

    def __init__(self, registry: ParamRegistry, initial: Mapping[str, object] | None = None) -> None:
        if not isinstance(registry, ParamRegistry):
            raise ParamError("", "state registry must be a ParamRegistry")
        self.registry = registry
        self._lock = threading.Lock()
        self._snapshot = ParamSnapshot(registry.validate(initial if initial is not None else {}), 0)

    @property
    def snapshot(self) -> ParamSnapshot:
        with self._lock:
            return self._snapshot

    def apply(self, changes: Mapping[str, object]) -> ParamSnapshot:
        """Validate and publish updates as one all-or-nothing version change."""
        if not isinstance(changes, Mapping):
            raise ParamError("", "parameter changes must be a mapping")
        with self._lock:
            current = dict(self._snapshot)
            candidate = dict(current)
            for key, value in changes.items():
                candidate[key] = self.registry.validate_value(key, value)
            complete = self.registry.validate(candidate)
            if complete == current:
                return self._snapshot
            self._snapshot = ParamSnapshot(complete, self._snapshot.version + 1)
            return self._snapshot

    def set(self, key: str, value: object) -> ParamSnapshot:
        return self.apply({key: value})

    def reset(self) -> ParamSnapshot:
        return self.apply(self.registry.defaults())
