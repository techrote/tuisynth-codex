"""Deterministic bounded grain scheduling, windows, and overlap-add rendering."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np


def poisson_arrivals(
    rng: np.random.Generator,
    density: float,
    frames: int,
    sample_rate: int,
    *,
    start_frame: int = 0,
) -> tuple[int, ...]:
    """Draw sorted absolute offsets for a Poisson process over a frame interval."""
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be a numpy Generator")
    if not math.isfinite(float(density)) or density < 0:
        raise ValueError("density must be finite and non-negative")
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 0:
        raise ValueError("frames must be a non-negative integer")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    if isinstance(start_frame, bool) or not isinstance(start_frame, int) or start_frame < 0:
        raise ValueError("start_frame must be a non-negative integer")
    if frames == 0 or density == 0:
        return ()
    count = int(rng.poisson(float(density) * frames / sample_rate))
    if count == 0:
        return ()
    offsets = np.sort(rng.integers(0, frames, size=count, endpoint=False))
    return tuple(start_frame + int(offset) for offset in offsets)


def window_values(kind: str, age: np.ndarray | int, length: int, sample_rate: int) -> np.ndarray:
    """Return a grain window segment with exact zero-valued endpoints."""
    if kind not in {"hann", "tukey", "expodec", "rexpodec"}:
        raise ValueError("unsupported grain window")
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise ValueError("length must be a positive integer")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    indices = np.asarray(age, dtype=np.int64)
    if np.any(indices < 0) or np.any(indices >= length):
        raise ValueError("grain age is outside its window")
    if length == 1:
        return np.zeros(indices.shape, dtype=np.float64)
    position = indices.astype(np.float64) / (length - 1)
    if kind == "hann":
        result = 0.5 - 0.5 * np.cos(2.0 * np.pi * position)
    elif kind == "tukey":
        edge = 0.125
        result = np.ones_like(position)
        rising = position < edge
        falling = position > 1.0 - edge
        result[rising] = 0.5 * (1.0 - np.cos(np.pi * position[rising] / edge))
        result[falling] = 0.5 * (1.0 - np.cos(np.pi * (1.0 - position[falling]) / edge))
    else:
        fade_frames = max(1, int(round(0.002 * sample_rate)))
        fade_frames = min(fade_frames, length - 1)
        decay = np.exp(-math.log(100.0) * np.maximum(indices - fade_frames, 0) / max(1, length - 1 - fade_frames))
        attack = np.clip(indices / fade_frames, 0.0, 1.0)
        result = attack * decay
        result[indices == length - 1] = 0.0
        if kind == "rexpodec":
            reverse_age = length - 1 - indices
            reverse_decay = np.exp(-math.log(100.0) * np.maximum(reverse_age - fade_frames, 0) / max(1, length - 1 - fade_frames))
            reverse_attack = np.clip(reverse_age / fade_frames, 0.0, 1.0)
            result = reverse_attack * reverse_decay
            result[indices == 0] = 0.0
    result = np.asarray(result, dtype=np.float64)
    result[(indices == 0) | (indices == length - 1)] = 0.0
    return result


@dataclass(slots=True)
class Grain:
    """One frozen, bounded grain request positioned on the engine's absolute frame clock."""

    start_frame: int
    length: int
    source_position: float
    ratio: float
    pan: float
    amplitude: float
    window: str

    def __post_init__(self) -> None:
        if self.start_frame < 0 or self.length < 1:
            raise ValueError("grain timing must be non-negative with positive length")
        if not all(math.isfinite(value) for value in (self.source_position, self.ratio, self.pan, self.amplitude)):
            raise ValueError("grain parameters must be finite")
        if self.ratio <= 0 or self.amplitude < 0 or not 0 <= self.pan <= 1:
            raise ValueError("grain ratio, amplitude, or pan is outside its valid range")
        if self.window not in {"hann", "tukey", "expodec", "rexpodec"}:
            raise ValueError("unsupported grain window")
        self.source_position %= 1.0


def _read(buffer: np.ndarray, positions: np.ndarray) -> np.ndarray:
    length = len(buffer)
    wrapped = np.mod(positions, length)
    base = np.floor(wrapped).astype(np.int64)
    fraction = wrapped - base
    following = (base + 1) % length
    return buffer[base] * (1.0 - fraction) + buffer[following] * fraction


def _read_sources(sources: Mapping[str, np.ndarray], positions: np.ndarray, tone: float, breath: float) -> np.ndarray:
    noise = _read(sources["noise"], positions)
    tone_signal = _read(sources["tone"], positions)
    breath_signal = _read(sources["breath"], positions)
    return (1.0 - tone) * noise + tone * tone_signal + breath * breath_signal


class GrainPool:
    """An active-grain cap with accounted drops and vectorized per-grain rendering."""

    def __init__(self, capacity: int = 64) -> None:
        self.capacity = self._valid_capacity(capacity)
        self.grains: list[Grain] = []
        self.dropped = 0
        self.spawned = 0
        self._last: tuple[Grain, ...] = ()

    @staticmethod
    def _valid_capacity(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 16 <= value <= 96:
            raise ValueError("grain capacity must be an integer from 16 through 96")
        return value

    @property
    def active_count(self) -> int:
        return len(self.grains)

    @property
    def grain_snapshot(self) -> tuple[Grain, ...]:
        return self._last

    def set_capacity(self, capacity: int) -> None:
        self.capacity = self._valid_capacity(capacity)
        if len(self.grains) > self.capacity:
            excess = len(self.grains) - self.capacity
            self.grains = self.grains[excess:]
            self.dropped += excess

    def spawn(self, grain: Grain) -> bool:
        if len(self.grains) >= self.capacity:
            self.dropped += 1
            return False
        self.grains.append(grain)
        self.spawned += 1
        return True

    def render(
        self,
        frames: int,
        *,
        block_offset: int,
        sample_rate: int,
        sources: Mapping[str, np.ndarray],
        old_sources: Mapping[str, np.ndarray] | None,
        source_fade: np.ndarray | None,
        tone: float,
        breath: float,
    ) -> np.ndarray:
        """Render only overlaps with this segment; no loop iterates over samples."""
        if frames < 0 or block_offset < 0:
            raise ValueError("render positions must be non-negative")
        output = np.zeros((frames, 2), dtype=np.float64)
        segment_end = block_offset + frames
        keep: list[Grain] = []
        snapshot: list[Grain] = []
        for grain in self.grains:
            grain_end = grain.start_frame + grain.length
            overlap_start = max(block_offset, grain.start_frame)
            overlap_end = min(segment_end, grain_end)
            if overlap_end > overlap_start:
                count = overlap_end - overlap_start
                age = np.arange(overlap_start - grain.start_frame, overlap_end - grain.start_frame, dtype=np.int64)
                source_positions = grain.source_position * len(sources["noise"]) + age * grain.ratio
                signal = _read_sources(sources, source_positions, tone, breath)
                if old_sources is not None and source_fade is not None:
                    before = _read_sources(old_sources, source_positions, tone, breath)
                    fade = source_fade[overlap_start - block_offset : overlap_end - block_offset]
                    signal = before * (1.0 - fade) + signal * fade
                window = window_values(grain.window, age, grain.length, sample_rate)
                angle = grain.pan * (math.pi / 2.0)
                left_gain = math.cos(angle)
                right_gain = math.sin(angle)
                destination = slice(overlap_start - block_offset, overlap_end - block_offset)
                weighted = signal * window * grain.amplitude
                output[destination, 0] += weighted * left_gain
                output[destination, 1] += weighted * right_gain
                snapshot.append(grain)
            if grain_end > segment_end:
                keep.append(grain)
        self.grains = keep
        self._last = tuple(snapshot[-64:])
        return output.astype(np.float32)


__all__ = ["Grain", "GrainPool", "poisson_arrivals", "window_values"]
