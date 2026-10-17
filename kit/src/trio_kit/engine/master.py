"""Stateful DC removal, drive, limiter, and final output safety."""

from __future__ import annotations

import math
from numbers import Real

import numpy as np
from scipy.signal import lfilter

from trio_kit.constants import OUTPUT_CEILING


class MasterBus:
    """Process stereo float buffers and keep limiter/filter state across calls."""

    def __init__(
        self,
        sample_rate: int = 48_000,
        *,
        ceiling: float = OUTPUT_CEILING,
        drive: float = 0.0,
        release_seconds: float = 0.12,
        dc_hz: float = 10.0,
    ) -> None:
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer")
        self.sample_rate = sample_rate
        self.ceiling = self._positive(ceiling, "ceiling")
        if self.ceiling > 1.0:
            raise ValueError("ceiling must be no greater than 1")
        self.drive = self._positive(drive, "drive", allow_zero=True)
        self.release_seconds = self._positive(release_seconds, "release_seconds")
        self.dc_hz = self._positive(dc_hz, "dc_hz")
        alpha = math.exp(-2.0 * math.pi * self.dc_hz / self.sample_rate)
        self._dc_b = np.asarray((1.0, -1.0), dtype=np.float64)
        self._dc_a = np.asarray((1.0, -alpha), dtype=np.float64)
        self._decay = math.exp(-1.0 / (self.release_seconds * self.sample_rate))
        self.nonfinite_resets = 0
        self.limited_blocks = 0
        self.last_limiter_gain = 1.0
        self._reset_states()

    @staticmethod
    def _positive(value: object, name: str, *, allow_zero: bool = False) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name} must be finite")
        number = float(value)
        if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
            raise ValueError(f"{name} must be finite and {'non-negative' if allow_zero else 'positive'}")
        return number

    @property
    def envelope(self) -> float:
        return self._envelope

    def _reset_states(self) -> None:
        self._dc_zi = np.zeros((1, 2), dtype=np.float64)
        self._envelope = 0.0
        self.last_limiter_gain = 1.0

    def reset(self) -> None:
        self._reset_states()

    def _limit(self, signal: np.ndarray) -> np.ndarray:
        if signal.shape[0] == 0:
            self.last_limiter_gain = 1.0
            return np.array(signal, dtype=np.float32, copy=True)
        peaks = np.max(np.abs(signal), axis=1).astype(np.float64, copy=False)
        indices = np.arange(signal.shape[0], dtype=np.float64)
        decay_powers = np.power(self._decay, indices)
        attack_history = np.divide(
            peaks,
            decay_powers,
            out=np.zeros_like(peaks),
            where=decay_powers > 0,
        )
        from_input = np.maximum.accumulate(attack_history) * decay_powers
        from_previous = self._envelope * np.power(self._decay, indices + 1.0)
        envelope = np.maximum(from_input, from_previous)
        gains = np.minimum(1.0, self.ceiling / np.maximum(envelope, np.finfo(np.float64).tiny))
        self._envelope = float(envelope[-1])
        self.last_limiter_gain = float(np.min(gains))
        if self.last_limiter_gain < 0.999999:
            self.limited_blocks += 1
        return (signal * gains[:, None]).astype(np.float32, copy=False)

    def process(self, buffer: np.ndarray) -> np.ndarray:
        """Process a stereo buffer; replace non-finite input/output with silence."""
        samples = np.asarray(buffer, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError("master input must have shape (frames, 2)")
        if samples.shape[0] == 0:
            return np.zeros((0, 2), dtype=np.float32)
        if not np.isfinite(samples).all():
            self.nonfinite_resets += 1
            self._reset_states()
            return np.zeros(samples.shape, dtype=np.float32)

        filtered, self._dc_zi = lfilter(self._dc_b, self._dc_a, samples, axis=0, zi=self._dc_zi)
        if self.drive > 0.0:
            filtered = np.tanh(filtered * (1.0 + self.drive))
        limited = self._limit(filtered)
        if not np.isfinite(limited).all():
            self.nonfinite_resets += 1
            self._reset_states()
            return np.zeros(samples.shape, dtype=np.float32)
        return np.clip(limited, -self.ceiling, self.ceiling).astype(np.float32, copy=False)


__all__ = ["MasterBus"]
