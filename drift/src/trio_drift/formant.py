"""Five-band vowel bank with the DRIFT soprano formant table."""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter


FORMANTS = np.asarray((
    ((800, 80, 0), (1150, 90, -6), (2900, 120, -32), (3900, 130, -20), (4950, 140, -50)),
    ((350, 60, 0), (2000, 100, -20), (2800, 120, -15), (3600, 150, -40), (4950, 200, -56)),
    ((270, 60, 0), (2140, 90, -12), (2950, 100, -26), (3900, 120, -26), (4950, 120, -44)),
    ((450, 70, 0), (800, 80, -11), (2830, 100, -22), (3800, 130, -22), (4950, 135, -50)),
    ((325, 50, 0), (700, 60, -16), (2700, 170, -35), (3800, 180, -40), (4950, 200, -60)),
), dtype=np.float64)


def vowel_formants(vowel: float) -> np.ndarray:
    """Linearly interpolate the contracted A/E/I/O/U table."""
    value = min(4.0, max(0.0, float(vowel)))
    lower = min(3, int(math.floor(value)))
    fraction = value - lower
    return FORMANTS[lower] * (1.0 - fraction) + FORMANTS[lower + 1] * fraction


class _Bandpass:
    """Stateful stereo RBJ band-pass supporting the narrow formant Q values."""

    def __init__(self, sample_rate: int, cutoff: float, q: float, *, smooth_seconds: float = 0.005) -> None:
        self.sample_rate = sample_rate
        self._smooth_total = max(1, int(round(sample_rate * smooth_seconds)))
        self._target = (cutoff, q)
        self._start = self._target
        self._elapsed = self._smooth_total
        self._segment_remaining = 0
        self._segment_coefficients: tuple[np.ndarray, np.ndarray] | None = None
        self._zi = np.zeros((2, 2), dtype=np.float64)

    def set_parameters(self, cutoff: float, q: float) -> None:
        if (cutoff, q) == self._target:
            return
        self._start = self.current_parameters
        self._target = (float(cutoff), float(q))
        self._elapsed = 0
        self._segment_remaining = 0
        self._segment_coefficients = None

    @property
    def current_parameters(self) -> tuple[float, float]:
        if self._elapsed >= self._smooth_total:
            return self._target
        fraction = self._elapsed / self._smooth_total
        return tuple(start + (target - start) * fraction for start, target in zip(self._start, self._target))

    def _design(self, cutoff: float, q: float) -> tuple[np.ndarray, np.ndarray]:
        cutoff = min(0.45 * self.sample_rate, max(20.0, cutoff))
        omega = 2.0 * math.pi * cutoff / self.sample_rate
        alpha = math.sin(omega) / (2.0 * max(0.05, q))
        cosine = math.cos(omega)
        a0 = 1.0 + alpha
        b = np.asarray((alpha / a0, 0.0, -alpha / a0), dtype=np.float64)
        a = np.asarray((1.0, -2.0 * cosine / a0, (1.0 - alpha) / a0), dtype=np.float64)
        return b, a

    def _start_segment(self) -> None:
        count = min(32, self._smooth_total - self._elapsed)
        midpoint = self._elapsed + count / 2
        fraction = midpoint / self._smooth_total
        parameters = tuple(start + (target - start) * fraction for start, target in zip(self._start, self._target))
        self._segment_remaining = count
        self._segment_coefficients = self._design(*parameters)

    def process(self, signal: np.ndarray) -> np.ndarray:
        samples = np.asarray(signal, dtype=np.float64)
        result = np.empty_like(samples)
        cursor = 0
        while cursor < len(samples):
            if self._elapsed >= self._smooth_total:
                coefficients = self._design(*self._target)
                filtered, self._zi = lfilter(*coefficients, samples[cursor:], axis=0, zi=self._zi)
                result[cursor:] = filtered
                break
            if self._segment_remaining == 0:
                self._start_segment()
            count = min(len(samples) - cursor, self._segment_remaining)
            assert self._segment_coefficients is not None
            filtered, self._zi = lfilter(*self._segment_coefficients, samples[cursor : cursor + count], axis=0, zi=self._zi)
            result[cursor : cursor + count] = filtered
            cursor += count
            self._elapsed += count
            self._segment_remaining -= count
            if self._segment_remaining == 0:
                self._segment_coefficients = None
        return result.astype(np.float32)

    def reset(self) -> None:
        self._zi.fill(0.0)
        self._start = self._target
        self._elapsed = self._smooth_total
        self._segment_remaining = 0
        self._segment_coefficients = None


class FormantBank:
    """Five parallel stereo band-passes with smoothed exact table settings."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._filters = [_Bandpass(sample_rate, *self._initial(index)) for index in range(5)]
        self._gains = 10.0 ** (FORMANTS[0, :, 2] / 20.0)
        self._last_settings: tuple[float, float, float] | None = None

    @staticmethod
    def _initial(index: int) -> tuple[float, float]:
        frequency, bandwidth, _ = FORMANTS[0, index]
        return float(frequency), float(frequency / bandwidth)

    def configure(self, vowel: float, shift: float, q_scale: float) -> None:
        settings = (float(vowel), float(shift), float(q_scale))
        if settings == self._last_settings:
            return
        rows = vowel_formants(vowel)
        gains = np.power(10.0, rows[:, 2] / 20.0)
        for index, (frequency, bandwidth, _) in enumerate(rows):
            cutoff = float(frequency * shift)
            band_q = float(frequency * shift * q_scale / bandwidth)
            self._filters[index].set_parameters(cutoff, band_q)
        self._gains = gains
        self._last_settings = settings

    def process(self, signal: np.ndarray, mix: float) -> np.ndarray:
        samples = np.asarray(signal, dtype=np.float32)
        wet = np.zeros_like(samples, dtype=np.float64)
        for filt, gain in zip(self._filters, self._gains):
            wet += filt.process(samples) * gain
        return (samples.astype(np.float64) * (1.0 - mix) + wet * mix).astype(np.float32)

    def reset(self) -> None:
        for filt in self._filters:
            filt.reset()


__all__ = ["FORMANTS", "FormantBank", "vowel_formants"]
