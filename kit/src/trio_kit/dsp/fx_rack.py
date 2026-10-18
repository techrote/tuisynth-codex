"""Small, stateful post-tone rack used by every TRIO instrument."""

from __future__ import annotations

import math
from collections.abc import Mapping
import threading
from typing import TYPE_CHECKING

import numpy as np
from scipy.signal import lfilter

if TYPE_CHECKING:
    from trio_kit.modulation import ModulationConfig

from trio_kit.dsp.delay import DelayLine
from trio_kit.dsp.lfo import Lfo


class FxRack:
    """Vectorized modulation effects with an identity default and stable state."""

    def __init__(self, sample_rate: int, seed: int = 0) -> None:
        self.sample_rate = sample_rate
        self.seed = seed
        from trio_kit.modulation import ModulationConfig

        self.config = ModulationConfig.defaults()
        self._pending_config: ModulationConfig | None = None
        self._config_lock = threading.Lock()
        self._tremolo_lfo = Lfo(sample_rate, rate=5.0, seed=seed + 1)
        self._phaser_lfo = Lfo(sample_rate, rate=0.35, seed=seed + 2)
        self._wow_lfo = Lfo(sample_rate, rate=0.5, seed=seed + 3)
        self._flutter_lfo = Lfo(sample_rate, rate=8.0, seed=seed + 4)
        self._ring_phase = 0.0
        self._tape_delay = DelayLine(max(2, int(sample_rate * 0.05)), channels=2)
        self._allpass_x = np.zeros((8, 2), dtype=np.float64)
        self._allpass_y = np.zeros((8, 2), dtype=np.float64)
        self._feedback = np.zeros(2, dtype=np.float64)
        self._block_feedback = self._feedback.copy()
        self._phaser_feedback_pending = self._feedback.copy()
        self._phaser_control = 0.0
        self._vectors: dict[str, np.ndarray] = {}
        self._cursor = 0
        self._frames = 0
        self._fx_overrides: Mapping[str, float] = {}

    def set_config(self, config: ModulationConfig) -> None:
        if not hasattr(config, "rack_order") or not hasattr(config, "rack_units"):
            raise TypeError("config must be a ModulationConfig")
        with self._config_lock:
            self._pending_config = config

    def _apply_pending_config(self) -> None:
        with self._config_lock:
            config = self._pending_config
            self._pending_config = None
        if config is not None:
            self.config = config

    def set_fx_overrides(self, values: Mapping[str, float]) -> None:
        self._fx_overrides = values

    def begin_block(self, frames: int, tempo: float, fx_overrides: Mapping[str, float] | None = None) -> Mapping[str, float]:
        self._apply_pending_config()
        settings = self.config.rack_units
        if fx_overrides is not None:
            self._fx_overrides = fx_overrides
        self._tremolo_lfo.set_rate(self._override("fx.tremolo.rate", float(settings["tremolo"]["rate"])))
        self._phaser_lfo.set_rate(self._override("fx.phaser.rate", float(settings["phaser"]["rate"])))
        self._vectors = {
            "tremolo.lfo": self._tremolo_lfo.process(frames),
            "phaser.lfo": self._phaser_lfo.process(frames),
            "tape.wow": self._wow_lfo.process(frames),
            "tape.flutter": self._flutter_lfo.process(frames),
        }
        self._block_feedback = self._feedback.copy()
        self._phaser_control = float(np.mean(self._vectors["phaser.lfo"], dtype=np.float64)) if frames else 0.0
        self._cursor = 0
        self._frames = frames
        return {name: float(np.mean(vector, dtype=np.float64)) if len(vector) else 0.0 for name, vector in self._vectors.items()}

    def process(self, buffer: np.ndarray) -> np.ndarray:
        return self.process_ordered(buffer)

    def process_ordered(self, buffer: np.ndarray, shared_processor=None) -> np.ndarray:
        """Run all rack units in configured order; shared units use the callback."""
        samples = np.asarray(buffer, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError("FX rack input must be stereo")
        count = len(samples)
        if count == 0 or not np.isfinite(samples).all():
            self._cursor += count
            return samples
        vectors: dict[str, np.ndarray] = {}
        for name, vector in self._vectors.items():
            vectors[name] = vector[self._cursor:self._cursor + count]
        if not self._vectors:
            return samples
        current = samples
        for name in self.config.rack_order:
            settings = self.config.rack_units[name]
            if settings["bypass"]:
                continue
            mix = float(settings["mix"])
            if name == "tremolo":
                wet = self._tremolo(current, settings, vectors["tremolo.lfo"])
            elif name == "ring-mod":
                wet = self._ring(current, settings, count)
            elif name == "phaser":
                wet = self._phaser(current, settings)
            elif name == "tape":
                wet = self._tape(current, settings, vectors["tape.wow"], vectors["tape.flutter"])
            elif shared_processor is not None:
                rendered = shared_processor(name, current)
                wet = current if rendered is None else np.asarray(rendered, dtype=np.float32)
                if wet.shape != current.shape:
                    raise ValueError(f"shared {name} effect must preserve shape {current.shape}")
            else:
                continue
            if mix == 1.0:
                current = wet
            elif mix > 0.0:
                current = (current * (1.0 - mix) + wet * mix).astype(np.float32)
        self._cursor += count
        if self._cursor >= self._frames:
            self._feedback = self._phaser_feedback_pending.copy()
        return current

    def _override(self, key: str, default: float) -> float:
        return float(self._fx_overrides.get(key, default))

    def _tremolo(self, samples: np.ndarray, settings: Mapping[str, object], lfo: np.ndarray) -> np.ndarray:
        depth = self._override("fx.tremolo.depth", float(settings["depth"]))
        if settings["mode"] == "autopan":
            pan = np.clip(lfo.astype(np.float64) * depth, -1.0, 1.0)
            angle = (pan + 1.0) * (math.pi * 0.25)
            left = np.cos(angle) * math.sqrt(2.0)
            right = np.sin(angle) * math.sqrt(2.0)
            return (samples.astype(np.float64) * np.column_stack((left, right))).astype(np.float32)
        gain = 1.0 - depth * (0.5 + 0.5 * lfo.astype(np.float64))
        return (samples.astype(np.float64) * gain[:, None]).astype(np.float32)

    def _ring(self, samples: np.ndarray, settings: Mapping[str, object], count: int) -> np.ndarray:
        frequency = self._override("fx.ring.frequency", float(settings["frequency"]))
        depth = self._override("fx.ring.depth", float(settings["depth"]))
        phase = self._ring_phase + np.arange(count, dtype=np.float64) * frequency / self.sample_rate
        carrier = np.sin(2.0 * math.pi * phase)
        self._ring_phase = (self._ring_phase + count * frequency / self.sample_rate) % 1.0
        wet = samples.astype(np.float64) * carrier[:, None]
        return (samples * (1.0 - depth) + wet * depth).astype(np.float32)

    def _phaser(self, samples: np.ndarray, settings: Mapping[str, object]) -> np.ndarray:
        depth = self._override("fx.phaser.depth", float(settings["depth"]))
        stages = int(settings["stages"])
        feedback_amount = float(settings["feedback"])
        data = samples.astype(np.float64) + self._block_feedback[None, :] * feedback_amount
        low = 250.0 + (1.0 + self._phaser_control) * depth * 1900.0
        output = data
        for stage in range(stages):
            frequency = min(self.sample_rate * 0.45, low * (1.0 + stage * 0.33))
            tangent = math.tan(math.pi * frequency / self.sample_rate)
            coefficient = (tangent - 1.0) / (tangent + 1.0)
            initial = (self._allpass_x[stage] - coefficient * self._allpass_y[stage])[None, :]
            result, _ = lfilter([coefficient, 1.0], [1.0, coefficient], output, axis=0, zi=initial)
            self._allpass_x[stage] = output[-1].copy()
            self._allpass_y[stage] = result[-1].copy()
            output = result
        self._phaser_feedback_pending = output[-1].copy() if len(output) else self._phaser_feedback_pending
        return ((samples.astype(np.float64) + output) * 0.5).astype(np.float32)

    def _tape(self, samples: np.ndarray, settings: Mapping[str, object], wow: np.ndarray, flutter: np.ndarray) -> np.ndarray:
        wow_depth = self._override("fx.tape.wow", float(settings["wow"]))
        flutter_depth = self._override("fx.tape.flutter", float(settings["flutter"]))
        base = max(1.0, self.sample_rate * 0.012)
        delay = base + self.sample_rate * (wow_depth * wow.astype(np.float64) + flutter_depth * flutter.astype(np.float64))
        delay = np.clip(delay, 1.0, self._tape_delay.max_delay_samples)
        delayed = self._tape_delay.process(samples, delay)
        saturation = self._override("fx.tape.saturation", float(settings["saturation"]))
        if saturation > 0:
            drive = 1.0 + 8.0 * saturation
            delayed = (np.tanh(delayed * drive) / math.tanh(drive)).astype(np.float32)
        return delayed

    def reset(self) -> None:
        self._tremolo_lfo.reset()
        self._phaser_lfo.reset()
        self._wow_lfo.reset()
        self._flutter_lfo.reset()
        self._ring_phase = 0.0
        self._tape_delay.reset()
        self._allpass_x.fill(0.0)
        self._allpass_y.fill(0.0)
        self._feedback.fill(0.0)
        self._block_feedback.fill(0.0)
        self._phaser_feedback_pending.fill(0.0)
        self._phaser_control = 0.0
        self._vectors = {}
        self._cursor = 0
        self._frames = 0


__all__ = ["FxRack"]
