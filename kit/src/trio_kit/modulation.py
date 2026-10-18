"""Validated modulation sources, matrix routing and per-note snapshot support."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import threading
from types import MappingProxyType
from typing import Any

import numpy as np

from trio_kit.dsp.lfo import Lfo
from trio_kit.params import ParamRegistry, ParamSnapshot


WAVEFORMS = ("sine", "triangle", "saw", "square", "sample_hold", "smooth_random")
SYNC_DIVISIONS = ("1/4", "1/8", "1/8T", "1/16", "1/16T", "1/32")
SOURCES = (
    "lfo1", "lfo2", "lfo3", "modenv", "velocity", "modwheel", "keytrack",
    "note-random", "pitchbend", "tremolo.lfo", "phaser.lfo", "tape.wow", "tape.flutter",
)
FX_UNITS = ("tremolo", "ring-mod", "phaser", "tape")
RACK_UNITS = (*FX_UNITS, "chorus", "delay", "reverb")
FX_RANGES: Mapping[str, tuple[float, float]] = MappingProxyType({
    "fx.tremolo.depth": (0.0, 1.0), "fx.tremolo.rate": (0.01, 20.0),
    "fx.ring.frequency": (0.5, 2000.0), "fx.ring.depth": (0.0, 1.0),
    "fx.phaser.depth": (0.0, 1.0), "fx.phaser.rate": (0.01, 20.0),
    "fx.tape.wow": (0.0, 0.02), "fx.tape.flutter": (0.0, 0.002),
    "fx.tape.saturation": (0.0, 1.0),
})
_DEFAULT_UNIT_SETTINGS: Mapping[str, Mapping[str, object]] = {
    "tremolo": {"bypass": True, "mix": 1.0, "mode": "autopan", "depth": 0.5, "rate": 5.0},
    "ring-mod": {"bypass": True, "mix": 1.0, "frequency": 440.0, "depth": 1.0},
    "phaser": {"bypass": True, "mix": 1.0, "stages": 4, "rate": 0.35, "depth": 0.8, "feedback": 0.2},
    "tape": {"bypass": True, "mix": 1.0, "wow": 0.001, "flutter": 0.00015, "saturation": 0.0},
    "chorus": {"bypass": False, "mix": 1.0},
    "delay": {"bypass": False, "mix": 1.0},
    "reverb": {"bypass": False, "mix": 1.0},
}


def _finite(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number in {low:g}..{high:g}")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be a finite number in {low:g}..{high:g}")
    return number


@dataclass(frozen=True, slots=True)
class LfoConfig:
    waveform: str = "sine"
    rate: float = 0.5
    sync: bool = False
    division: str = "1/4"
    phase: float = 0.0
    mode: str = "global"
    seed: int = 0

    @classmethod
    def from_dict(cls, value: object) -> LfoConfig:
        if not isinstance(value, Mapping):
            raise ValueError("LFO configuration must be an object")
        unknown = set(value) - {"waveform", "rate", "sync", "division", "phase", "mode", "seed"}
        if unknown:
            raise ValueError(f"unknown LFO fields: {', '.join(sorted(map(str, unknown)))}")
        waveform = value.get("waveform", "sine")
        sync = value.get("sync", False)
        division = value.get("division", "1/4")
        mode = value.get("mode", "global")
        seed = value.get("seed", 0)
        if waveform not in WAVEFORMS:
            raise ValueError("LFO waveform is unsupported")
        if not isinstance(sync, bool):
            raise ValueError("LFO sync must be a boolean")
        if division not in SYNC_DIVISIONS:
            raise ValueError("LFO tempo division is unsupported")
        if mode not in {"global", "voice"}:
            raise ValueError("LFO mode must be global or voice")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("LFO seed must be a non-negative integer")
        return cls(str(waveform), _finite(value.get("rate", 0.5), "LFO rate", 0.01, 20), sync,
                   str(division), _finite(value.get("phase", 0), "LFO phase", 0, 1), str(mode), seed)

    def to_dict(self) -> dict[str, object]:
        return {"waveform": self.waveform, "rate": self.rate, "sync": self.sync,
                "division": self.division, "phase": self.phase, "mode": self.mode, "seed": self.seed}


@dataclass(frozen=True, slots=True)
class ModSlot:
    source: str | None = None
    destination: str | None = None
    amount: float = 0.0

    @classmethod
    def from_dict(cls, value: object) -> ModSlot:
        if not isinstance(value, Mapping):
            raise ValueError("modulation slot must be an object")
        unknown = set(value) - {"source", "destination", "amount"}
        if unknown:
            raise ValueError(f"unknown modulation slot fields: {', '.join(sorted(map(str, unknown)))}")
        source = value.get("source")
        destination = value.get("destination")
        if source is not None and source not in SOURCES:
            raise ValueError(f"unknown modulation source {source!r}")
        if destination is not None and (not isinstance(destination, str) or not destination):
            raise ValueError("modulation destination must be a non-empty string or null")
        return cls(source, destination, _finite(value.get("amount", 0), "modulation amount", -1, 1))

    def to_dict(self) -> dict[str, object]:
        return {"source": self.source, "destination": self.destination, "amount": self.amount}


@dataclass(frozen=True, slots=True)
class ModulationConfig:
    lfos: tuple[LfoConfig, LfoConfig, LfoConfig]
    mod_env: Mapping[str, float]
    slots: tuple[ModSlot, ...]
    rack_order: tuple[str, ...]
    rack_units: Mapping[str, Mapping[str, object]]

    @classmethod
    def defaults(cls) -> ModulationConfig:
        return cls.from_dict({})

    @classmethod
    def from_dict(cls, value: object) -> ModulationConfig:
        if not isinstance(value, Mapping):
            raise ValueError("modulation settings must be an object")
        unknown = set(value) - {"lfos", "mod_env", "slots", "rack"}
        if unknown:
            raise ValueError(f"unknown modulation fields: {', '.join(sorted(map(str, unknown)))}")
        raw_lfos = value.get("lfos", ({}, {}, {}))
        if not isinstance(raw_lfos, Sequence) or isinstance(raw_lfos, (str, bytes)) or len(raw_lfos) != 3:
            raise ValueError("modulation requires exactly three LFO configurations")
        lfos = tuple(LfoConfig.from_dict(item) for item in raw_lfos)
        raw_env = value.get("mod_env", {})
        if not isinstance(raw_env, Mapping):
            raise ValueError("ModEnv configuration must be an object")
        if set(raw_env) - {"attack", "decay", "sustain", "release"}:
            raise ValueError("unknown ModEnv fields")
        env = MappingProxyType({
            "attack": _finite(raw_env.get("attack", 0.01), "ModEnv attack", 0.001, 20),
            "decay": _finite(raw_env.get("decay", 0.2), "ModEnv decay", 0.001, 20),
            "sustain": _finite(raw_env.get("sustain", 0.5), "ModEnv sustain", 0, 1),
            "release": _finite(raw_env.get("release", 0.4), "ModEnv release", 0.001, 30),
        })
        raw_slots = value.get("slots", ({},) * 8)
        if not isinstance(raw_slots, Sequence) or isinstance(raw_slots, (str, bytes)) or len(raw_slots) != 8:
            raise ValueError("modulation matrix must contain exactly eight slots")
        slots = tuple(ModSlot.from_dict(item) for item in raw_slots)
        rack = value.get("rack", {})
        if not isinstance(rack, Mapping) or set(rack) - {"order", "units"}:
            raise ValueError("rack must contain only order and units")
        order = rack.get("order", RACK_UNITS)
        if (
            not isinstance(order, Sequence)
            or isinstance(order, (str, bytes))
            or len(order) != len(RACK_UNITS)
            or any(not isinstance(item, str) or item not in RACK_UNITS for item in order)
            or len(set(order)) != len(RACK_UNITS)
        ):
            raise ValueError("rack order must contain each rack unit exactly once")
        order_tuple = tuple(order)
        raw_units = rack.get("units", {})
        if not isinstance(raw_units, Mapping) or set(raw_units) - set(RACK_UNITS):
            raise ValueError("rack units contain an unknown effect")
        normalized_units: dict[str, Mapping[str, object]] = {}
        for name in RACK_UNITS:
            raw = raw_units.get(name, {})
            if not isinstance(raw, Mapping):
                raise ValueError(f"rack unit {name} must be an object")
            merged = dict(_DEFAULT_UNIT_SETTINGS[name])
            merged.update(raw)
            allowed = set(_DEFAULT_UNIT_SETTINGS[name])
            if set(merged) != allowed:
                raise ValueError(f"unknown rack unit field for {name}")
            if not isinstance(merged["bypass"], bool):
                raise ValueError(f"{name} bypass must be a boolean")
            merged["mix"] = _finite(merged["mix"], f"{name} mix", 0, 1)
            if name in {"chorus", "delay", "reverb"}:
                normalized_units[name] = MappingProxyType(merged)
                continue
            if name == "tremolo":
                if merged["mode"] not in {"tremolo", "autopan"}:
                    raise ValueError("tremolo mode must be tremolo or autopan")
                merged["depth"] = _finite(merged["depth"], "tremolo depth", 0, 1)
                merged["rate"] = _finite(merged["rate"], "tremolo rate", 0.01, 20)
            elif name == "ring-mod":
                merged["frequency"] = _finite(merged["frequency"], "ring carrier frequency", 0.5, 2000)
                merged["depth"] = _finite(merged["depth"], "ring depth", 0, 1)
            elif name == "phaser":
                if merged["stages"] not in {4, 8}:
                    raise ValueError("phaser stages must be 4 or 8")
                merged["rate"] = _finite(merged["rate"], "phaser rate", 0.01, 20)
                merged["depth"] = _finite(merged["depth"], "phaser depth", 0, 1)
                merged["feedback"] = _finite(merged["feedback"], "phaser feedback", 0, 0.8)
            else:
                merged["wow"] = _finite(merged["wow"], "tape wow depth", 0, 0.02)
                merged["flutter"] = _finite(merged["flutter"], "tape flutter depth", 0, 0.002)
                merged["saturation"] = _finite(merged["saturation"], "tape saturation", 0, 1)
            normalized_units[name] = MappingProxyType(merged)
        return cls((lfos[0], lfos[1], lfos[2]), env, slots, order_tuple, MappingProxyType(normalized_units))

    def to_dict(self) -> dict[str, object]:
        return {
            "lfos": [item.to_dict() for item in self.lfos],
            "mod_env": dict(self.mod_env),
            "slots": [item.to_dict() for item in self.slots],
            "rack": {"order": list(self.rack_order), "units": {name: dict(settings) for name, settings in self.rack_units.items()}},
        }


def validate_modulation(value: object, registry: ParamRegistry | None = None) -> dict[str, object]:
    """Return normalized preset JSON for the shared modulation area."""
    config = ModulationConfig.from_dict(value)
    if registry is not None:
        for index, slot in enumerate(config.slots, start=1):
            destination = slot.destination
            if destination is None or destination in FX_RANGES:
                continue
            spec = registry.specs.get(destination)
            if spec is None:
                raise ValueError(f"modulation slot {index} has unknown destination {destination!r}")
            if not spec.modulatable or spec.kind != "continuous":
                raise ValueError(f"modulation slot {index} destination {destination!r} is not a modulatable continuous parameter")
            source = slot.source
            source_is_voice = source in {"modenv", "velocity", "keytrack", "note-random"}
            if source in {"lfo1", "lfo2", "lfo3"}:
                source_is_voice = config.lfos[int(source[-1]) - 1].mode == "voice"
            if source_is_voice and getattr(spec, "modulation_scope", "global") == "global":
                raise ValueError(f"modulation slot {index} voice source cannot target global-only destination {destination!r}")
        for index, slot in enumerate(config.slots, start=1):
            if slot.destination not in FX_RANGES or slot.source is None:
                continue
            source_is_voice = slot.source in {"modenv", "velocity", "keytrack", "note-random"}
            if slot.source in {"lfo1", "lfo2", "lfo3"}:
                source_is_voice = config.lfos[int(slot.source[-1]) - 1].mode == "voice"
            if source_is_voice:
                raise ValueError(f"modulation slot {index} voice source cannot target shared effect {slot.destination!r}")
    return config.to_dict()


class ModulationProcessor:
    """Block-rate modulation evaluator with stable note-scoped sources."""

    def __init__(self, registry: ParamRegistry, sample_rate: int, seed: int = 0) -> None:
        self.registry = registry
        self.sample_rate = sample_rate
        self.seed = seed
        self.config = ModulationConfig.defaults()
        self._pending_config: ModulationConfig | None = None
        self._config_lock = threading.Lock()
        self.tempo = 120.0
        self.modwheel = 0.0
        self.pitchbend = 0.0
        self._global_lfos = [self._make_lfo(index, cfg) for index, cfg in enumerate(self.config.lfos)]
        self._global_sources: dict[str, float] = {}
        self._global_smoothed: dict[tuple[int, str], float] = {}
        self._global_deltas: dict[str, float] = {}
        self._block_base_snapshot: ParamSnapshot | None = None
        self._block_effective_snapshot: ParamSnapshot | None = None
        self._note_random: dict[int, float] = {}
        self._voice_lfos: dict[tuple[int, int], Lfo] = {}
        self._voice_smoothed: dict[tuple[int, int, str], float] = {}
        self._base_frame = 0
        self._block_frames = 256
        self._fx_overrides: dict[str, float] = {}
        self._fx_smoothed: dict[str, float] = {}

    def _make_lfo(self, index: int, config: LfoConfig, *, note_id: int | None = None) -> Lfo:
        rate = _lfo_rate(config, self.tempo)
        seed = config.seed if note_id is None else int(np.random.SeedSequence([self.seed, config.seed, note_id, index]).generate_state(1)[0])
        return Lfo(self.sample_rate, rate=rate, waveform=config.waveform, seed=seed, phase=config.phase, max_rate=32.0)

    def set_config(self, config: ModulationConfig) -> None:
        if not isinstance(config, ModulationConfig):
            raise TypeError("config must be a ModulationConfig")
        with self._config_lock:
            self._pending_config = config

    @property
    def requested_config(self) -> ModulationConfig:
        """Return the latest requested config, including a not-yet-committed edit."""
        with self._config_lock:
            return self._pending_config or self.config

    def _apply_pending_config(self) -> None:
        with self._config_lock:
            config = self._pending_config
            self._pending_config = None
        if config is None or config == self.config:
            return

        previous = self.config
        old_slots = previous.slots
        self.config = config
        self._global_lfos = [
            oscillator if previous.lfos[index] == lfo_config else self._make_lfo(index, lfo_config)
            for index, (oscillator, lfo_config) in enumerate(zip(self._global_lfos, config.lfos))
        ]

        def is_voice_source(source: str | None, lfos: tuple[LfoConfig, LfoConfig, LfoConfig]) -> bool:
            if source in {"modenv", "velocity", "keytrack", "note-random"}:
                return True
            if source in {"lfo1", "lfo2", "lfo3"}:
                return lfos[int(source[-1]) - 1].mode == "voice"
            return False

        retained_global_routes: set[tuple[int, str]] = set()
        retained_voice_routes: set[tuple[int, str]] = set()
        for index, (old, new) in enumerate(zip(old_slots, config.slots)):
            if old.destination is None or old.destination != new.destination:
                continue
            old_voice = is_voice_source(old.source, previous.lfos)
            new_voice = is_voice_source(new.source, config.lfos)
            if old_voice != new_voice:
                continue
            route = (index, new.destination)
            (retained_voice_routes if new_voice else retained_global_routes).add(route)
        self._global_smoothed = {
            key: value for key, value in self._global_smoothed.items() if key in retained_global_routes
        }
        self._voice_smoothed = {
            key: value for key, value in self._voice_smoothed.items()
            if (key[1], key[2]) in retained_voice_routes
        }
        changed_lfos = {index for index, (old, new) in enumerate(zip(previous.lfos, config.lfos)) if old != new}
        self._voice_lfos = {key: value for key, value in self._voice_lfos.items() if key[1] not in changed_lfos}

        old_fx_destinations = {slot.destination for slot in old_slots if slot.source is not None and slot.destination in FX_RANGES}
        new_fx_destinations = {slot.destination for slot in config.slots if slot.source is not None and slot.destination in FX_RANGES}
        self._fx_smoothed = {
            destination: value for destination, value in self._fx_smoothed.items()
            if destination in old_fx_destinations and destination in new_fx_destinations
        }
        self._global_deltas.clear()
        self._block_base_snapshot = None
        self._block_effective_snapshot = None
        self._fx_overrides.clear()

    def on_event(self, name: str, payload: tuple[float | int | str, ...]) -> None:
        if name == "mod_wheel" and payload:
            self.modwheel = min(1.0, max(0.0, float(payload[0])))
        elif name == "pitch_bend" and payload:
            self.pitchbend = min(1.0, max(-1.0, float(payload[0]) / 12.0))
        elif name == "transport" and payload:
            self.tempo = min(240.0, max(40.0, float(payload[0])))

    def begin_block(self, base_frame: int, frames: int, *, tempo: float | None = None, fx_sources: Mapping[str, float] | None = None) -> None:
        self._apply_pending_config()
        if tempo is not None:
            self.tempo = min(240.0, max(40.0, float(tempo)))
        self._base_frame = base_frame
        self._block_frames = frames
        sources: dict[str, float] = {
            "modwheel": self.modwheel * 2.0 - 1.0,
            "pitchbend": self.pitchbend,
        }
        for index, (oscillator, config) in enumerate(zip(self._global_lfos, self.config.lfos)):
            if config.mode != "global":
                continue
            oscillator.set_rate(_lfo_rate(config, self.tempo))
            vector = oscillator.process(frames)
            sources[f"lfo{index + 1}"] = float(np.mean(vector, dtype=np.float64)) if frames else 0.0
        if fx_sources:
            sources.update(fx_sources)
        self._global_sources = sources
        self._fx_overrides = self._evaluate_fx_overrides(sources)

    @property
    def fx_overrides(self) -> Mapping[str, float]:
        return MappingProxyType(dict(self._fx_overrides))

    def _source_is_voice(self, source: str) -> bool:
        if source in {"modenv", "velocity", "keytrack", "note-random"}:
            return True
        if source.startswith("lfo") and source[-1:].isdigit():
            return self.config.lfos[int(source[-1]) - 1].mode == "voice"
        return False

    def apply_global(self, snapshot: ParamSnapshot) -> ParamSnapshot:
        self._block_base_snapshot = snapshot
        if not any(slot.source is not None and slot.destination is not None and not self._source_is_voice(slot.source) for slot in self.config.slots):
            self._global_deltas = {}
            self._block_effective_snapshot = snapshot
            return snapshot
        effective, self._global_deltas = self._apply_slots(
            snapshot, self._global_sources, voice_id=None, smoothing_frames=self._block_frames,
        )
        self._block_effective_snapshot = effective
        return effective

    def voice_snapshot(
        self,
        snapshot: ParamSnapshot,
        *,
        note_id: int,
        pitch: float,
        velocity: float,
        age_frames: int,
        released_frames: int | None,
        frames: int,
    ) -> ParamSnapshot:
        sources: dict[str, float] = dict(self._global_sources)
        sources["velocity"] = min(1.0, max(0.0, velocity)) * 2.0 - 1.0
        sources["keytrack"] = min(1.0, max(-1.0, (pitch - 60.0) / 60.0))
        sources["note-random"] = self._random_for_note(note_id)
        sources["modenv"] = 2.0 * self._mod_env(age_frames / self.sample_rate, None if released_frames is None else released_frames / self.sample_rate) - 1.0
        for index, config in enumerate(self.config.lfos):
            name = f"lfo{index + 1}"
            if config.mode == "global":
                continue
            key = (note_id, index)
            oscillator = self._voice_lfos.get(key)
            if oscillator is None:
                oscillator = self._make_lfo(index, config, note_id=note_id)
                self._voice_lfos[key] = oscillator
            oscillator.set_rate(_lfo_rate(config, self.tempo))
            vector = oscillator.process(frames) if frames else np.asarray([oscillator.peek()], dtype=np.float32)
            sources[name] = float(np.mean(vector, dtype=np.float64))
        voice_slots = [slot for slot in self.config.slots if slot.source is not None and slot.destination is not None and self._source_is_voice(slot.source)]
        voice_deltas: dict[str, float] = {}
        if voice_slots:
            _voice_only_snapshot, voice_deltas = self._apply_slots(
                snapshot, sources, voice_id=note_id, only_voice=True, smoothing_frames=frames,
            )

        # Global and per-voice routes can share a destination. Rebuild from the
        # unmodulated block base so all deltas are combined before clamping.
        if snapshot is self._block_effective_snapshot and self._block_base_snapshot is not None:
            base = self._block_base_snapshot
            deltas = dict(self._global_deltas)
        else:
            base = snapshot
            deltas = {}
        for destination, delta in voice_deltas.items():
            deltas[destination] = deltas.get(destination, 0.0) + delta
        if not deltas:
            return snapshot
        values = dict(base)
        for destination, delta in deltas.items():
            spec = self.registry[destination]
            values[destination] = min(
                float(spec.maximum),
                max(float(spec.minimum), float(base[destination]) + delta),
            )
        return ParamSnapshot(values, base.version)

    def note_finished(self, note_id: int) -> None:
        self._note_random.pop(note_id, None)
        self._voice_smoothed = {key: value for key, value in self._voice_smoothed.items() if key[0] != note_id}
        self._voice_lfos = {key: value for key, value in self._voice_lfos.items() if key[0] != note_id}

    def reset(self) -> None:
        for oscillator in self._global_lfos:
            oscillator.reset()
        self._global_smoothed.clear()
        self._global_deltas.clear()
        self._block_base_snapshot = None
        self._block_effective_snapshot = None
        self._note_random.clear()
        self._voice_lfos.clear()
        self._voice_smoothed.clear()
        self._global_sources.clear()
        self._fx_overrides.clear()
        self._fx_smoothed.clear()
        self.modwheel = 0.0
        self.pitchbend = 0.0
        self.tempo = 120.0
        self._base_frame = 0

    def _random_for_note(self, note_id: int) -> float:
        if note_id not in self._note_random:
            rng = np.random.default_rng(np.random.SeedSequence([self.seed, note_id, 0x4D4F44]))
            self._note_random[note_id] = float(rng.uniform(-1.0, 1.0))
        return self._note_random[note_id]

    def _mod_env(self, age: float, released: float | None) -> float:
        a, d, s, r = (self.config.mod_env[name] for name in ("attack", "decay", "sustain", "release"))
        if released is not None:
            release_level = self._env_level(max(0.0, age - released), a, d, s)
            return max(0.0, release_level * (1.0 - released / r))
        return self._env_level(age, a, d, s)

    @staticmethod
    def _env_level(age: float, attack: float, decay: float, sustain: float) -> float:
        if age <= attack:
            return age / attack
        if age <= attack + decay:
            return 1.0 + (sustain - 1.0) * ((age - attack) / decay)
        return sustain

    def _apply_slots(
        self,
        snapshot: ParamSnapshot,
        sources: Mapping[str, float],
        *,
        voice_id: int | None,
        only_voice: bool = False,
        smoothing_frames: int,
    ) -> tuple[ParamSnapshot, dict[str, float]]:
        values = dict(snapshot)
        touched = False
        smoothing = 1.0 - math.exp(-max(0, smoothing_frames) / (self.sample_rate * 0.02))
        deltas: dict[str, float] = {}
        for index, slot in enumerate(self.config.slots):
            if slot.source is None or slot.destination is None:
                continue
            source_is_voice = self._source_is_voice(slot.source)
            if only_voice != source_is_voice:
                continue
            if slot.destination not in self.registry.specs:
                continue
            spec = self.registry[slot.destination]
            if not spec.modulatable or getattr(spec, "modulation_scope", "global") not in ({"voice", "both"} if only_voice else {"global", "voice", "both"}):
                continue
            source = sources.get(slot.source)
            if source is None:
                continue
            key = (voice_id, index, slot.destination) if voice_id is not None else (index, slot.destination)
            target = source * slot.amount * (float(spec.maximum) - float(spec.minimum)) * 0.5
            state = self._voice_smoothed if voice_id is not None else self._global_smoothed
            if key not in state and voice_id is not None:
                state[key] = target
                deltas[slot.destination] = deltas.get(slot.destination, 0.0) + target
                touched = True
                continue
            previous = state.get(key, 0.0)
            smooth = previous + (target - previous) * smoothing
            state[key] = smooth
            deltas[slot.destination] = deltas.get(slot.destination, 0.0) + smooth
            touched = True
        for destination, delta in deltas.items():
            spec = self.registry[destination]
            values[destination] = min(float(spec.maximum), max(float(spec.minimum), float(snapshot[destination]) + delta))
        return (ParamSnapshot(values, snapshot.version) if touched else snapshot), deltas

    def _evaluate_fx_overrides(self, sources: Mapping[str, float]) -> dict[str, float]:
        targets: dict[str, float] = {}
        for slot in self.config.slots:
            if slot.source is None or slot.destination not in FX_RANGES:
                continue
            source = sources.get(slot.source)
            if source is None:
                continue
            low, high = FX_RANGES[slot.destination]
            targets[slot.destination] = targets.get(slot.destination, 0.0) + source * slot.amount * (high - low) * 0.5
        smoothing = 1.0 - math.exp(-max(1, self._block_frames) / (self.sample_rate * 0.02))
        result: dict[str, float] = {}
        for destination, target in targets.items():
            low, high = FX_RANGES[destination]
            previous = self._fx_smoothed.get(destination, 0.0)
            smooth = previous + (target - previous) * smoothing
            self._fx_smoothed[destination] = smooth
            result[destination] = min(high, max(low, self._fx_baseline(destination) + smooth))
        return result

    def _fx_baseline(self, destination: str) -> float:
        unit_name, field = destination[3:].split(".", 1)
        unit_name = {"ring": "ring-mod"}.get(unit_name, unit_name)
        setting = {"depth": "depth", "rate": "rate", "frequency": "frequency", "wow": "wow", "flutter": "flutter", "saturation": "saturation"}[field]
        unit = self.config.rack_units[unit_name]
        return float(unit[setting])


def _lfo_rate(config: LfoConfig, tempo: float) -> float:
    if not config.sync:
        return config.rate
    beats = {"1/4": 1.0, "1/8": 0.5, "1/8T": 1.0 / 3.0, "1/16": 0.25, "1/16T": 1.0 / 6.0, "1/32": 0.125}[config.division]
    return (tempo / 60.0) / beats


__all__ = ["FX_RANGES", "FX_UNITS", "LfoConfig", "ModSlot", "ModulationConfig", "ModulationProcessor", "RACK_UNITS", "SOURCES", "SYNC_DIVISIONS", "WAVEFORMS", "validate_modulation"]
