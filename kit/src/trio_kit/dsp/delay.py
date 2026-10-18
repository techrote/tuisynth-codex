"""Chronological, fractional, block-vectorized circular delay line."""

from __future__ import annotations

import numpy as np

from trio_kit.dsp._validation import audio_buffer, finite_number, frame_count


class DelayLine:
    """Circular delay with causal processing and linearly interpolated reads.

    `read(delay, frames)` reads the next `frames` positions from the current write
    cursor. Thus, after writing 0..7, `read(4, 4)` returns 4..7.
    """

    def __init__(self, max_delay_samples: int, *, channels: int = 1) -> None:
        if isinstance(max_delay_samples, bool) or not isinstance(max_delay_samples, int) or max_delay_samples < 1:
            raise ValueError("max_delay_samples must be a positive integer")
        if isinstance(channels, bool) or not isinstance(channels, int) or channels < 1:
            raise ValueError("channels must be a positive integer")
        self.max_delay_samples = max_delay_samples
        self.channels = channels
        self._capacity = max_delay_samples + 2
        self._buffer = np.zeros((self._capacity, channels), dtype=np.float32)
        self._write_count = 0

    @property
    def write_count(self) -> int:
        return self._write_count

    def reset(self) -> None:
        self._buffer.fill(0.0)
        self._write_count = 0

    def _delay_matrix(self, delay: object, frames: int, *, allow_zero: bool) -> np.ndarray:
        try:
            raw = np.asarray(delay)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("delay must contain finite sample counts") from error
        if raw.dtype.kind not in "iuf":
            raise ValueError("delay must contain real numeric sample counts")
        try:
            values = np.asarray(raw, dtype=np.float64)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("delay must contain finite sample counts") from error
        if values.ndim == 0:
            scalar = finite_number(values.item(), "delay", minimum=0 if allow_zero else 1, maximum=self.max_delay_samples)
            result = np.full((frames, self.channels), scalar, dtype=np.float64)
        elif values.shape == (frames,):
            if not np.isfinite(values).all():
                raise ValueError("delay must contain finite sample counts")
            minimum = 0 if allow_zero else 1
            if np.any(values < minimum) or np.any(values > self.max_delay_samples):
                raise ValueError(f"delay must be in the range {minimum}..{self.max_delay_samples}")
            result = np.repeat(values[:, None], self.channels, axis=1)
        elif values.shape == (frames, self.channels):
            if not np.isfinite(values).all():
                raise ValueError("delay must contain finite sample counts")
            minimum = 0 if allow_zero else 1
            if np.any(values < minimum) or np.any(values > self.max_delay_samples):
                raise ValueError(f"delay must be in the range {minimum}..{self.max_delay_samples}")
            result = values
        else:
            raise ValueError("delay array must have shape (frames,) or (frames, channels)")
        return result

    def _read_indices(self, indices: np.ndarray, current: np.ndarray | None = None) -> np.ndarray:
        output = np.zeros(indices.shape, dtype=np.float64)
        history = (indices >= 0) & (indices < self._write_count)
        if np.any(history):
            channel_index = np.broadcast_to(np.arange(self.channels), indices.shape)
            output[history] = self._buffer[(indices % self._capacity)[history], channel_index[history]]
        if current is not None:
            future = (indices >= self._write_count) & (indices < self._write_count + len(current))
            if np.any(future):
                channel_index = np.broadcast_to(np.arange(self.channels), indices.shape)
                current_index = indices - self._write_count
                output[future] = current[current_index[future], channel_index[future]]
        return output

    def read(self, delay: float | np.ndarray, frames: int) -> np.ndarray:
        count = frame_count(frames)
        delays = self._delay_matrix(delay, count, allow_zero=True)
        absolute = self._write_count + np.arange(count, dtype=np.float64)[:, None] - delays
        lower = np.floor(absolute).astype(np.int64)
        fraction = absolute - lower
        low_sample = self._read_indices(lower)
        high_sample = self._read_indices(lower + 1)
        result = low_sample + (high_sample - low_sample) * fraction
        return result[:, 0].astype(np.float32) if self.channels == 1 else result.astype(np.float32)

    def write(self, buffer: object) -> None:
        samples, _ = audio_buffer(buffer, channels=self.channels)
        count = len(samples)
        if count == 0:
            return
        indices = (self._write_count + np.arange(count)) % self._capacity
        self._buffer[indices] = samples
        self._write_count += count

    def process(self, buffer: object, delay: float | np.ndarray) -> np.ndarray:
        samples, mono = audio_buffer(buffer, channels=self.channels)
        count = len(samples)
        delays = self._delay_matrix(delay, count, allow_zero=False)
        if count == 0:
            return np.zeros(0, dtype=np.float32) if mono else np.zeros((0, self.channels), dtype=np.float32)
        absolute = self._write_count + np.arange(count, dtype=np.float64)[:, None] - delays
        lower = np.floor(absolute).astype(np.int64)
        fraction = absolute - lower
        low_sample = self._read_indices(lower, samples)
        high_sample = self._read_indices(lower + 1, samples)
        output = low_sample + (high_sample - low_sample) * fraction
        self.write(samples)
        return output[:, 0].astype(np.float32) if mono else output.astype(np.float32)


__all__ = ["DelayLine"]
