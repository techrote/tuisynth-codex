"""AURORA's parameter surface and harmonic-profile validation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real
from typing import Any

from trio_kit.params import ParamRegistry, ParamSpec


DEFAULT_HARMONICS = tuple(1.0 / math.sqrt(index + 1) for index in range(64))
COUNT_CHOICES = ("16", "32", "64")
FILTER_CHOICES = ("lp", "bp", "hp")
LFO_WAVES = ("sine", "triangle", "smooth_random")
LFO_TARGETS = ("pitch", "cutoff", "amplitude", "pan")


def aurora_registry() -> ParamRegistry:
    """Return AURORA's complete, instrument-owned parameter registry."""
    return ParamRegistry(
        (
            ParamSpec("spec.count", "Harmonics", "", 0, 2, 1, kind="choice", choices=COUNT_CHOICES, group="Spectrum"),
            ParamSpec("spec.bw", "Bandwidth", "cents", 1, 400, 60, curve="log", group="Spectrum"),
            ParamSpec("spec.bwscale", "Bandwidth scale", "", 0, 2, 1, group="Spectrum"),
            ParamSpec("spec.stretch", "Partial stretch", "", 0.95, 1.05, 1, group="Spectrum"),
            ParamSpec("spec.tilt", "Tilt", "dB/oct", -12, 6, -3, group="Spectrum"),
            ParamSpec("spec.noise", "Noise floor", "", 0, 1, 0, group="Spectrum"),
            ParamSpec("spec.seed", "Phase seed", "", 0, 9999, 1, kind="discrete", group="Spectrum"),
            ParamSpec("osc.octave", "Octave", "oct", -2, 2, 0, kind="discrete", group="Oscillator"),
            ParamSpec("osc.detune", "Detune", "cents", 0, 50, 6, modulatable=True, modulation_scope="voice", group="Oscillator"),
            ParamSpec("osc.width", "Stereo width", "", 0, 1, 0.85, modulatable=True, modulation_scope="voice", group="Oscillator"),
            ParamSpec("amp.a", "Attack", "s", 0.001, 20, 1.8, curve="log", group="Amplitude"),
            ParamSpec("amp.d", "Decay", "s", 0.01, 20, 1.5, curve="log", group="Amplitude"),
            ParamSpec("amp.s", "Sustain", "", 0, 1, 0.8, group="Amplitude"),
            ParamSpec("amp.r", "Release", "s", 0.01, 30, 4, curve="log", group="Amplitude"),
            ParamSpec("amp.vel", "Velocity", "", 0, 1, 0.4, modulatable=True, modulation_scope="voice", group="Amplitude"),
            ParamSpec("flt.mode", "Filter mode", "", 0, 2, 0, kind="choice", choices=FILTER_CHOICES, group="Filter"),
            ParamSpec("flt.cut", "Cutoff", "Hz", 20, 20_000, 5_000, curve="log", modulatable=True, modulation_scope="voice", group="Filter"),
            ParamSpec("flt.res", "Resonance", "", 0, 0.95, 0.1, modulatable=True, modulation_scope="voice", group="Filter"),
            ParamSpec("flt.env", "Envelope depth", "", -1, 1, 0.2, modulatable=True, modulation_scope="voice", group="Filter"),
            ParamSpec("flt.key", "Key tracking", "", 0, 1, 0.3, modulatable=True, modulation_scope="voice", group="Filter"),
            ParamSpec("fenv.a", "Filter attack", "s", 0.001, 20, 2.5, curve="log", group="Filter envelope"),
            ParamSpec("fenv.d", "Filter decay", "s", 0.01, 20, 2, curve="log", group="Filter envelope"),
            ParamSpec("fenv.s", "Filter sustain", "", 0, 1, 0.5, group="Filter envelope"),
            ParamSpec("fenv.r", "Filter release", "s", 0.01, 30, 5, curve="log", group="Filter envelope"),
            ParamSpec("lfo.rate", "LFO rate", "Hz", 0.01, 10, 0.15, curve="log", group="Motion"),
            ParamSpec("lfo.depth", "LFO depth", "", 0, 1, 0.2, group="Motion"),
            ParamSpec("lfo.wave", "LFO wave", "", 0, 2, 2, kind="choice", choices=LFO_WAVES, group="Motion"),
            ParamSpec("lfo.tgt", "LFO target", "", 0, 3, 1, kind="choice", choices=LFO_TARGETS, group="Motion"),
            ParamSpec("fx.chorus.mix", "Chorus", "", 0, 1, 0.2, modulatable=True, group="Space"),
            ParamSpec("fx.delay.time", "Delay time", "s", 0.06, 2, 0.42, curve="log", modulatable=True, group="Space"),
            ParamSpec("fx.delay.fb", "Delay feedback", "", 0, 0.9, 0.35, modulatable=True, group="Space"),
            ParamSpec("fx.delay.mix", "Delay", "", 0, 1, 0.15, modulatable=True, group="Space"),
            ParamSpec("fx.reverb.size", "Reverb size", "", 0.2, 1.6, 0.85, curve="log", modulatable=True, group="Space"),
            ParamSpec("fx.reverb.damp", "Reverb damping", "", 0, 1, 0.4, modulatable=True, group="Space"),
            ParamSpec("fx.reverb.mix", "Reverb", "", 0, 1, 0.35, modulatable=True, group="Space"),
            ParamSpec("master.level", "Master level", "", 0, 1, 0.75, group="Master"),
            ParamSpec("master.drive", "Master drive", "", 0, 1, 0.1, group="Master"),
        )
    )


def validate_extras(extras: dict[str, Any]) -> Mapping[str, Any]:
    """Validate harmonic painting data and pad shorter profiles to 64 bars."""
    if not isinstance(extras, Mapping):
        raise ValueError("instrument extras must be an object")
    # The shared shell/engine owns these fields. Accept them here as well so
    # callers that validate an entire preset extras object remain compatible.
    unknown = set(extras) - {"harmonics", "sequencer", "modulation"}
    if unknown:
        raise ValueError(f"unknown AURORA extra {sorted(unknown)[0]!r}")
    raw = extras.get("harmonics", DEFAULT_HARMONICS)
    if not isinstance(raw, (list, tuple)) or len(raw) > 64:
        raise ValueError("extras.harmonics must contain at most 64 values")
    harmonics: list[float] = []
    for index, value in enumerate(raw):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"extras.harmonics[{index}] must be a finite number in 0..1")
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(f"extras.harmonics[{index}] must be a finite number in 0..1")
        harmonics.append(number)
    harmonics.extend([0.0] * (64 - len(harmonics)))
    return {"harmonics": harmonics}


def choice_label(registry: ParamRegistry, key: str, value: object) -> str:
    spec = registry[key]
    if spec.choices is None:
        raise ValueError(f"{key} is not a choice parameter")
    return spec.choices[int(spec.validate_value(value))]


__all__ = [
    "COUNT_CHOICES",
    "DEFAULT_HARMONICS",
    "FILTER_CHOICES",
    "LFO_TARGETS",
    "LFO_WAVES",
    "aurora_registry",
    "choice_label",
    "validate_extras",
]
