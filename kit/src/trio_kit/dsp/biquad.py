"""RBJ cookbook filters with stateful, smoothed coefficient updates."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from scipy.signal import lfilter

from trio_kit.dsp._validation import finite_number, frame_count, positive_sample_rate


_ALIASES = {
    "lp": "lowpass",
    "bp": "bandpass",
    "hp": "highpass",
    "peak": "peaking",
}
_KINDS = {"lowpass", "bandpass", "highpass", "peaking"}


class Biquad:
    """Low-pass, band-pass, high-pass, or peaking equalizer filter.

    Parameter changes interpolate over 5 ms. Coefficients are held for fixed
    32-frame spans, and span state is retained if the caller splits a request.
    """

    def __init__(
        self,
        sample_rate: int = 48_000,
        *,
        kind: Literal["lowpass", "bandpass", "highpass", "peaking", "lp", "bp", "hp", "peak"] = "lowpass",
        cutoff: float = 1_000.0,
        q: float = 0.7071067811865476,
        gain_db: float = 0.0,
    ) -> None:
        self.sample_rate = positive_sample_rate(sample_rate)
        if not isinstance(kind, str):
            raise ValueError("kind must name a supported biquad filter")
        normalized_kind = _ALIASES.get(kind, kind)
        if normalized_kind not in _KINDS:
            raise ValueError("kind must be lowpass, bandpass, highpass, or peaking")
        self.kind = normalized_kind
        params = self._validate_parameters(cutoff, q, gain_db)
        self._target = params
        self._current = params
        self._smooth_start = params
        self._smooth_total = max(1, int(round(0.005 * self.sample_rate)))
        self._smooth_elapsed = self._smooth_total
        self._segment_length = 0
        self._segment_remaining = 0
        self._segment_coefficients: tuple[np.ndarray, np.ndarray] | None = None
        self._zi: np.ndarray | None = None
        self._channels: int | None = None
        self._ndim: int | None = None

    def _validate_parameters(self, cutoff: object, q: object, gain_db: object) -> tuple[float, float, float]:
        max_cutoff = 0.45 * self.sample_rate
        if max_cutoff < 20:
            raise ValueError("sample_rate is too low for the 20 Hz minimum cutoff")
        return (
            finite_number(cutoff, "cutoff", minimum=20, maximum=max_cutoff),
            finite_number(q, "q", minimum=0.05, maximum=20),
            finite_number(gain_db, "gain_db", minimum=-36, maximum=36),
        )

    @property
    def cutoff(self) -> float:
        return self._target[0]

    @property
    def current_cutoff(self) -> float:
        return self._parameters_at(self._smooth_elapsed)[0] if self._smooth_elapsed < self._smooth_total else self._current[0]

    @property
    def current_parameters(self) -> tuple[float, float, float]:
        return self._parameters_at(self._smooth_elapsed) if self._smooth_elapsed < self._smooth_total else self._current

    @property
    def coefficients(self) -> tuple[np.ndarray, np.ndarray]:
        b, a = self._design(*self._target)
        return b.copy(), a.copy()

    def set_parameters(
        self,
        *,
        cutoff: float | None = None,
        q: float | None = None,
        gain_db: float | None = None,
    ) -> None:
        requested = self._validate_parameters(
            self._target[0] if cutoff is None else cutoff,
            self._target[1] if q is None else q,
            self._target[2] if gain_db is None else gain_db,
        )
        if requested == self._target:
            return
        start = self.current_parameters
        self._target = requested
        self._smooth_start = start
        self._smooth_elapsed = 0
        self._segment_length = 0
        self._segment_remaining = 0
        self._segment_coefficients = None

    def _parameters_at(self, elapsed: int) -> tuple[float, float, float]:
        fraction = min(1.0, elapsed / self._smooth_total)
        return tuple(start + (target - start) * fraction for start, target in zip(self._smooth_start, self._target))

    def _design(self, cutoff: float, q: float, gain_db: float) -> tuple[np.ndarray, np.ndarray]:
        omega = 2.0 * math.pi * cutoff / self.sample_rate
        cosine = math.cos(omega)
        sine = math.sin(omega)
        alpha = sine / (2.0 * q)
        if self.kind == "lowpass":
            b0, b1, b2 = (1 - cosine) / 2, 1 - cosine, (1 - cosine) / 2
            a0, a1, a2 = 1 + alpha, -2 * cosine, 1 - alpha
        elif self.kind == "highpass":
            b0, b1, b2 = (1 + cosine) / 2, -(1 + cosine), (1 + cosine) / 2
            a0, a1, a2 = 1 + alpha, -2 * cosine, 1 - alpha
        elif self.kind == "bandpass":
            b0, b1, b2 = alpha, 0.0, -alpha
            a0, a1, a2 = 1 + alpha, -2 * cosine, 1 - alpha
        else:
            amplitude = 10.0 ** (gain_db / 40.0)
            b0, b1, b2 = 1 + alpha * amplitude, -2 * cosine, 1 - alpha * amplitude
            a0, a1, a2 = 1 + alpha / amplitude, -2 * cosine, 1 - alpha / amplitude
        b = np.asarray((b0 / a0, b1 / a0, b2 / a0), dtype=np.float64)
        a = np.asarray((1.0, a1 / a0, a2 / a0), dtype=np.float64)
        return b, a

    def reset(self) -> None:
        self._zi = None
        self._channels = None
        self._ndim = None
        self._current = self._target
        self._smooth_start = self._target
        self._smooth_elapsed = self._smooth_total
        self._segment_length = 0
        self._segment_remaining = 0
        self._segment_coefficients = None

    def _start_segment(self) -> None:
        self._segment_length = min(32, self._smooth_total - self._smooth_elapsed)
        midpoint = self._smooth_elapsed + self._segment_length / 2
        params = self._parameters_at(int(midpoint))
        self._segment_coefficients = self._design(*params)
        self._segment_remaining = self._segment_length

    def _filter(self, samples: np.ndarray, coefficients: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
        if self._zi is None:
            self._channels = samples.shape[1] if samples.ndim == 2 else 1
            self._ndim = samples.ndim
            zi_shape = (2,) if samples.ndim == 1 else (2, samples.shape[1])
            self._zi = np.zeros(zi_shape, dtype=np.float64)
        elif samples.ndim != self._ndim or (samples.ndim == 2 and samples.shape[1] != self._channels):
            raise ValueError("biquad channel layout cannot change without reset()")
        b, a = coefficients
        filtered, self._zi = lfilter(b, a, samples, axis=0, zi=self._zi)
        return filtered

    def process(self, buffer: object) -> np.ndarray:
        try:
            raw = np.asarray(buffer)
            if raw.dtype.kind not in "biuf":
                raise ValueError("biquad input must contain real numeric samples")
            samples = np.asarray(raw, dtype=np.float64)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("biquad input must contain finite real numeric samples") from error
        if samples.ndim not in (1, 2) or (samples.ndim == 2 and samples.shape[1] < 1):
            raise ValueError("biquad input must have shape (frames,) or (frames, channels)")
        frame_count(len(samples))
        if not np.isfinite(samples).all():
            raise ValueError("biquad input must contain only finite samples")
        if len(samples) == 0:
            return np.array(samples, dtype=np.float32, copy=True)

        result = np.empty_like(samples)
        cursor = 0
        if self._smooth_elapsed >= self._smooth_total:
            result[:] = self._filter(samples, self._design(*self._current))
        else:
            while cursor < len(samples):
                if self._segment_remaining == 0:
                    if self._smooth_elapsed >= self._smooth_total:
                        result[cursor:] = self._filter(samples[cursor:], self._design(*self._current))
                        break
                    self._start_segment()
                assert self._segment_coefficients is not None
                count = min(len(samples) - cursor, self._segment_remaining)
                result[cursor : cursor + count] = self._filter(
                    samples[cursor : cursor + count], self._segment_coefficients
                )
                cursor += count
                self._segment_remaining -= count
                self._smooth_elapsed += count
                self._current = self._parameters_at(self._smooth_elapsed)
                if self._segment_remaining == 0:
                    self._segment_coefficients = None
        return np.asarray(result, dtype=np.float32)


__all__ = ["Biquad"]
