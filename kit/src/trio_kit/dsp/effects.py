"""Stateful stereo modulation, delay and feedback-delay-network effects."""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter

from trio_kit.constants import BLOCK
from trio_kit.dsp._validation import audio_buffer, finite_number, positive_sample_rate
from trio_kit.dsp.biquad import Biquad
from trio_kit.dsp.delay import DelayLine
from trio_kit.dsp.lfo import Lfo


def _stereo(buffer: object) -> np.ndarray:
    samples, _ = audio_buffer(buffer, channels=2)
    return samples


class Chorus:
    """Stereo chorus with two 7-20 ms taps in opposing LFO phase."""

    def __init__(
        self,
        sample_rate: int = 48_000,
        *,
        rate: float = 0.7,
        base_delay_ms: float = 13.5,
        depth_ms: float = 6.5,
        mix: float = 0.3,
        seed: int = 0,
    ) -> None:
        self.sample_rate = positive_sample_rate(sample_rate)
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        self._base_delay_ms = finite_number(base_delay_ms, "base_delay_ms", minimum=7, maximum=20)
        self._depth_ms = finite_number(depth_ms, "depth_ms", minimum=0, maximum=6.5)
        if self._base_delay_ms - self._depth_ms < 7 or self._base_delay_ms + self._depth_ms > 20:
            raise ValueError("chorus taps must remain in the 7..20 ms range")
        self._mix = finite_number(mix, "mix", minimum=0, maximum=1)
        normalized_rate = finite_number(rate, "rate", minimum=0.1, maximum=6)
        self.lfo = Lfo(self.sample_rate, rate=normalized_rate, waveform="sine", seed=seed)
        self.delay_line = DelayLine(int(math.ceil(self.sample_rate * 0.020)), channels=2)

    @property
    def mix(self) -> float:
        return self._mix

    @mix.setter
    def mix(self, value: float) -> None:
        self._mix = finite_number(value, "mix", minimum=0, maximum=1)

    @property
    def rate(self) -> float:
        return self.lfo.rate

    @property
    def base_delay_ms(self) -> float:
        return self._base_delay_ms

    @property
    def depth_ms(self) -> float:
        return self._depth_ms

    def set_parameters(self, *, rate: float | None = None, mix: float | None = None) -> None:
        normalized_rate = None if rate is None else finite_number(rate, "rate", minimum=0.1, maximum=6)
        normalized_mix = None if mix is None else finite_number(mix, "mix", minimum=0, maximum=1)
        if normalized_rate is not None:
            self.lfo.set_rate(normalized_rate)
        if normalized_mix is not None:
            self._mix = normalized_mix

    def process(self, buffer: object) -> np.ndarray:
        samples = _stereo(buffer)
        if len(samples) == 0:
            return np.zeros((0, 2), dtype=np.float32)
        modulation = self.lfo.process(len(samples)).astype(np.float64)
        base = self._base_delay_ms * self.sample_rate / 1000.0
        depth = self._depth_ms * self.sample_rate / 1000.0
        delays = np.column_stack((base + depth * modulation, base - depth * modulation))
        wet = self.delay_line.process(samples, delays)
        return (samples * (1.0 - self._mix) + wet * self._mix).astype(np.float32)

    def reset(self) -> None:
        self.delay_line.reset()
        self.lfo.reset()


class StereoDelay:
    """Ping-pong echo with a low-pass feedback loop."""

    def __init__(
        self,
        sample_rate: int = 48_000,
        *,
        delay_seconds: float = 0.35,
        feedback: float = 0.35,
        mix: float = 0.25,
        lowpass_hz: float = 6_000,
    ) -> None:
        self.sample_rate = positive_sample_rate(sample_rate)
        self._delay_seconds = 0.0
        self._feedback = finite_number(feedback, "feedback", minimum=0, maximum=0.9)
        self._mix = finite_number(mix, "mix", minimum=0, maximum=1)
        self.delay_line = DelayLine(int(math.ceil(2.0 * self.sample_rate)), channels=2)
        self.lowpass = Biquad(self.sample_rate, kind="lowpass", cutoff=lowpass_hz)
        self._set_delay(delay_seconds)

    @property
    def delay_seconds(self) -> float:
        return self._delay_seconds

    @property
    def feedback(self) -> float:
        return self._feedback

    @property
    def mix(self) -> float:
        return self._mix

    def _set_delay(self, value: float) -> None:
        self._delay_seconds = self._validated_delay(value)

    def _validated_delay(self, value: float) -> float:
        seconds = finite_number(value, "delay_seconds", minimum=0.06, maximum=2.0)
        samples = seconds * self.sample_rate
        if samples < BLOCK:
            raise ValueError("feedback delay must be at least one internal block")
        return seconds

    def set_parameters(
        self,
        *,
        delay_seconds: float | None = None,
        feedback: float | None = None,
        mix: float | None = None,
        lowpass_hz: float | None = None,
    ) -> None:
        normalized_delay = None if delay_seconds is None else self._validated_delay(delay_seconds)
        normalized_feedback = None if feedback is None else finite_number(feedback, "feedback", minimum=0, maximum=0.9)
        normalized_mix = None if mix is None else finite_number(mix, "mix", minimum=0, maximum=1)
        normalized_lowpass = None
        if lowpass_hz is not None:
            normalized_lowpass = finite_number(
                lowpass_hz,
                "lowpass_hz",
                minimum=20,
                maximum=0.45 * self.sample_rate,
            )
        if normalized_lowpass is not None:
            self.lowpass.set_parameters(cutoff=normalized_lowpass)
        if normalized_delay is not None:
            self._delay_seconds = normalized_delay
        if normalized_feedback is not None:
            self._feedback = normalized_feedback
        if normalized_mix is not None:
            self._mix = normalized_mix

    def process(self, buffer: object) -> np.ndarray:
        samples = _stereo(buffer)
        if len(samples) == 0:
            return np.zeros((0, 2), dtype=np.float32)
        delay_samples = self._delay_seconds * self.sample_rate
        delayed = self.delay_line.read(delay_samples, len(samples))
        feedback_signal = delayed[:, ::-1] * self._feedback
        loop_signal = samples + feedback_signal
        filtered = self.lowpass.process(loop_signal)
        self.delay_line.write(filtered)
        return (samples * (1.0 - self._mix) + delayed * self._mix).astype(np.float32)

    def reset(self) -> None:
        self.delay_line.reset()
        self.lowpass.reset()


class Reverb:
    """Eight-line Householder feedback delay network with per-line damping."""

    _BASE_SECONDS = (0.0311, 0.03335, 0.0364, 0.0389, 0.04165, 0.0444, 0.04752, 0.0496)

    def __init__(self, sample_rate: int = 48_000, *, size: float = 0.8, mix: float = 0.25) -> None:
        self.sample_rate = positive_sample_rate(sample_rate)
        self._mix = finite_number(mix, "mix", minimum=0, maximum=1)
        max_delay = int(math.ceil(max(self._BASE_SECONDS) * 1.6 * self.sample_rate))
        self.delay_lines = [DelayLine(max_delay, channels=1) for _ in range(8)]
        self._damping_alpha = math.exp(-2.0 * math.pi * 6_000.0 / self.sample_rate)
        self._damping_b = np.asarray((1.0 - self._damping_alpha,), dtype=np.float64)
        self._damping_a = np.asarray((1.0, -self._damping_alpha), dtype=np.float64)
        self._damping_zi = np.zeros((1, 8), dtype=np.float64)
        self._input_weights = np.full(8, 1.0 / math.sqrt(8.0), dtype=np.float64)
        self._size = 0.8
        self._delays: tuple[int, ...] = ()
        self._decay_gains = np.ones(8, dtype=np.float64)
        self.set_size(size)

    @property
    def size(self) -> float:
        return self._size

    @property
    def mix(self) -> float:
        return self._mix

    @mix.setter
    def mix(self, value: float) -> None:
        self._mix = finite_number(value, "mix", minimum=0, maximum=1)

    @property
    def line_delays(self) -> tuple[int, ...]:
        return self._delays

    def set_size(self, size: float) -> None:
        normalized = finite_number(size, "size", minimum=0.2, maximum=1.6)
        delays = tuple(int(round(seconds * normalized * self.sample_rate)) for seconds in self._BASE_SECONDS)
        if any(delay <= BLOCK for delay in delays):
            raise ValueError("every reverb line delay must be longer than one internal block")
        rt60 = 0.35 + 1.25 * normalized
        gains = np.asarray(
            [10.0 ** (-3.0 * delay / self.sample_rate / rt60) for delay in delays],
            dtype=np.float64,
        )
        self._size = normalized
        self._delays = delays
        self._decay_gains = gains

    def process(self, buffer: object) -> np.ndarray:
        samples = _stereo(buffer)
        frames = len(samples)
        if frames == 0:
            return np.zeros((0, 2), dtype=np.float32)
        delayed = np.column_stack(
            [line.read(delay, frames) for line, delay in zip(self.delay_lines, self._delays)]
        ).astype(np.float64)
        householder = (2.0 / 8.0) * np.sum(delayed, axis=1, keepdims=True) - delayed
        damped, self._damping_zi = lfilter(
            self._damping_b,
            self._damping_a,
            householder,
            axis=0,
            zi=self._damping_zi,
        )
        mono_input = np.mean(samples.astype(np.float64), axis=1)
        line_input = mono_input[:, None] * self._input_weights + damped * self._decay_gains[None, :]
        for index, line in enumerate(self.delay_lines):
            line.write(line_input[:, index])
        wet_left = np.mean(delayed[:, (0, 2, 4, 6)], axis=1)
        wet_right = np.mean(delayed[:, (1, 3, 5, 7)], axis=1)
        wet = np.column_stack((wet_left, wet_right)).astype(np.float32)
        return (samples * (1.0 - self._mix) + wet * self._mix).astype(np.float32)

    def reset(self) -> None:
        for line in self.delay_lines:
            line.reset()
        self._damping_zi.fill(0.0)


__all__ = ["Chorus", "Reverb", "StereoDelay"]
