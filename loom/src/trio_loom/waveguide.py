"""Exact delay-chunked extended Karplus--Strong string loop."""

from __future__ import annotations

import math

import numpy as np


def midi_frequency(pitch: float) -> float:
    """Equal-tempered pitch in Hz; fractional pitches support smooth retargets."""
    return 440.0 * (2.0 ** ((float(pitch) - 69.0) / 12.0))


class WaveguideString:
    """A fractional-delay string with bounded history retained across retargets.

    The loss and interpolation filters are convolved into three causal feedback
    taps. Since every feedback distance is at least M, processing no more than M
    output samples at once reads only history that predates that chunk.
    """

    def __init__(self, sample_rate: int = 48_000, pitch: float = 60.0, brightness: float = 0.6) -> None:
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer")
        self.sample_rate = sample_rate
        self.history = np.zeros(int(math.ceil(sample_rate / midi_frequency(24))) + 8, dtype=np.float64)
        self.write_index = 0
        self.pitch = 60.0
        self.frequency = midi_frequency(60.0)
        self.loop_samples = 0.0
        self.delay = 1
        self.fraction = 0.0
        self.taps = np.zeros(3, dtype=np.float64)
        self.brightness = 0.6
        self.last_sample = 0.0
        self.set_brightness(brightness)
        self.set_pitch(pitch)

    def set_brightness(self, brightness: float) -> None:
        value = float(brightness)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("brightness must be finite and in the range 0..1")
        self.brightness = value
        if self.loop_samples > 0:
            g = 0.5 * (1.0 - self.brightness)
            self.delay = max(1, math.floor(self.loop_samples - g))
            self.fraction = (self.loop_samples - g) - self.delay
        self._update_taps()

    def set_pitch(self, pitch: float) -> None:
        value = float(pitch)
        if not math.isfinite(value) or not 24.0 <= value <= 100.0:
            raise ValueError("pitch must be finite and in the playable MIDI range 24..100")
        self.pitch = value
        self.frequency = midi_frequency(value)
        self.loop_samples = self.sample_rate / self.frequency
        g = 0.5 * (1.0 - self.brightness)
        self.delay = max(1, math.floor(self.loop_samples - g))
        self.fraction = (self.loop_samples - g) - self.delay
        self._update_taps()

    def retarget(self, pitch: float) -> None:
        """Retune at a block boundary while preserving the existing loop history."""
        self.set_pitch(pitch)

    def _update_taps(self) -> None:
        g = 0.5 * (1.0 - self.brightness)
        d = self.fraction
        self.taps[:] = (
            (1.0 - g) * (1.0 - d),
            (1.0 - g) * d + g * (1.0 - d),
            g * d,
        )

    def process(self, excitation: object, t60: float | np.ndarray) -> np.ndarray:
        """Render a finite excitation vector using exact causal vector chunks."""
        x = np.asarray(excitation, dtype=np.float64)
        if x.ndim != 1 or not np.isfinite(x).all():
            raise ValueError("excitation must be a finite one-dimensional signal")
        decay = np.asarray(t60, dtype=np.float64)
        if decay.ndim == 0:
            scalar_decay = float(decay)
            if not math.isfinite(scalar_decay) or scalar_decay <= 0:
                raise ValueError("t60 must be finite and positive")
            decay = np.full(len(x), scalar_decay, dtype=np.float64)
        if decay.shape != x.shape or not np.isfinite(decay).all() or np.any(decay <= 0):
            raise ValueError("t60 must be finite and positive, as a scalar or a matching vector")
        if not len(x):
            return np.zeros(0, dtype=np.float32)
        rho = 10.0 ** (-3.0 * self.loop_samples / (self.sample_rate * decay))
        output = np.empty(len(x), dtype=np.float64)
        cursor = 0
        offsets = np.arange(self.delay, self.delay + 3, dtype=np.int64)
        while cursor < len(x):
            count = min(self.delay, len(x) - cursor)
            positions = self.write_index + cursor + np.arange(count, dtype=np.int64)
            feedback = np.zeros(count, dtype=np.float64)
            for tap_index, distance in enumerate(offsets):
                feedback += self.taps[tap_index] * self.history[(positions - distance) % len(self.history)]
            chunk = x[cursor : cursor + count] + rho[cursor : cursor + count] * feedback
            self.history[positions % len(self.history)] = chunk
            output[cursor : cursor + count] = chunk
            cursor += count
        self.write_index += len(x)
        self.last_sample = float(output[-1])
        return output.astype(np.float32)

    def reset(self) -> None:
        self.history.fill(0.0)
        self.write_index = 0
        self.last_sample = 0.0


__all__ = ["WaveguideString", "midi_frequency"]
