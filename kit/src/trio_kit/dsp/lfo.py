"""Seeded, phase-continuous low-frequency oscillator."""

from __future__ import annotations

import math

import numpy as np

from trio_kit.dsp._validation import finite_number, frame_count, positive_sample_rate


_WAVEFORMS = {"sine", "triangle", "saw", "square", "sample_hold", "smooth_random"}


class Lfo:
    """Vectorized oscillator with periodic and seeded random waveforms."""

    def __init__(
        self,
        sample_rate: int = 48_000,
        *,
        rate: float = 1.0,
        waveform: str = "sine",
        seed: int = 0,
        phase: float = 0.0,
        max_rate: float = 20.0,
    ) -> None:
        self.sample_rate = positive_sample_rate(sample_rate)
        if not isinstance(waveform, str) or waveform not in _WAVEFORMS:
            raise ValueError(f"waveform must be one of {tuple(sorted(_WAVEFORMS))}")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        self.max_rate = finite_number(max_rate, "max_rate", minimum=20, maximum=self.sample_rate / 2)
        self.waveform = waveform
        self._rate = finite_number(rate, "rate", minimum=0.01, maximum=self.max_rate)
        if self._rate > self.sample_rate / 2:
            raise ValueError("rate must not exceed the Nyquist frequency")
        self._initial_phase = finite_number(phase, "phase", minimum=0, maximum=1) % 1.0
        self.seed = seed
        self.reset()

    def reset(self) -> None:
        self._phase = self._initial_phase
        self._rng = np.random.default_rng(self.seed)
        self._random_current = float(self._rng.uniform(-1.0, 1.0))
        self._random_next = float(self._rng.uniform(-1.0, 1.0))

    @property
    def phase(self) -> float:
        return self._phase

    @property
    def rate(self) -> float:
        return self._rate

    def peek(self) -> float:
        """Return the waveform value at the current phase without advancing state."""
        phase = self._phase
        if self.waveform == "sine":
            return math.sin(2.0 * math.pi * phase)
        if self.waveform == "triangle":
            return 1.0 - 4.0 * abs(phase - 0.5)
        if self.waveform == "saw":
            return 2.0 * phase - 1.0
        if self.waveform == "square":
            return 1.0 if phase < 0.5 else -1.0
        if self.waveform == "sample_hold":
            return self._random_current
        smooth = phase * phase * (3.0 - 2.0 * phase)
        return self._random_current + (self._random_next - self._random_current) * smooth

    def set_rate(self, rate: float) -> None:
        normalized = finite_number(rate, "rate", minimum=0.01, maximum=self.max_rate)
        if normalized > self.sample_rate / 2:
            raise ValueError("rate must not exceed the Nyquist frequency")
        self._rate = normalized

    def process(self, frames: int) -> np.ndarray:
        frame_count(frames)
        if frames == 0:
            return np.zeros(0, dtype=np.float32)
        increment = self._rate / self.sample_rate
        phase_positions = self._phase + np.arange(frames, dtype=np.float64) * increment
        local_phase = phase_positions - np.floor(phase_positions)
        if self.waveform == "sine":
            output = np.sin(2.0 * math.pi * local_phase)
        elif self.waveform == "triangle":
            output = 1.0 - 4.0 * np.abs(local_phase - 0.5)
        elif self.waveform == "saw":
            output = 2.0 * local_phase - 1.0
        elif self.waveform == "square":
            output = np.where(local_phase < 0.5, 1.0, -1.0)
        else:
            cycle = np.floor(phase_positions).astype(np.int64)
            ending_phase = self._phase + frames * increment
            cycles_advanced = int(math.floor(ending_phase))
            new_values = self._rng.uniform(-1.0, 1.0, size=cycles_advanced) if cycles_advanced else np.empty(0)
            current_values = np.empty(frames, dtype=np.float64)
            next_values = np.empty(frames, dtype=np.float64)
            in_first = cycle == 0
            current_values[in_first] = self._random_current
            next_values[in_first] = self._random_next
            later = ~in_first
            if np.any(later):
                later_cycle = cycle[later]
                current_values[later] = np.where(
                    later_cycle == 1,
                    self._random_next,
                    new_values[np.maximum(later_cycle - 2, 0)],
                )
                next_values[later] = new_values[np.maximum(later_cycle - 1, 0)]
            if self.waveform == "sample_hold":
                output = current_values
            else:
                smooth = local_phase * local_phase * (3.0 - 2.0 * local_phase)
                output = current_values + (next_values - current_values) * smooth
            if cycles_advanced:
                self._random_current = self._random_next if cycles_advanced == 1 else float(new_values[cycles_advanced - 2])
                self._random_next = float(new_values[cycles_advanced - 1])

        ending_phase = self._phase + frames * increment
        self._phase = ending_phase - math.floor(ending_phase)
        return np.asarray(output, dtype=np.float32)


__all__ = ["Lfo"]
