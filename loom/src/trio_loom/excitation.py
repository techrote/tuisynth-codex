"""Seeded pluck and deliberately linear bowed-string excitation models."""

from __future__ import annotations

import math

import numpy as np

from trio_kit.dsp import Biquad
from trio_loom.waveguide import midi_frequency


class PluckExciter:
    """Generate a deterministic noise, low-pass, and pick-position comb burst."""

    def __init__(self, sample_rate: int, rng: np.random.Generator) -> None:
        self.sample_rate = sample_rate
        self.rng = rng

    def excite(self, pitch: float, velocity: float, hardness: float, pick_position: float) -> np.ndarray:
        frequency = midi_frequency(pitch)
        length = max(1, int(round(self.sample_rate / frequency)))
        cutoff = 400.0 + min(max(float(hardness), 0.0), 1.0) * 15_600.0
        alpha = 1.0 - math.exp(-2.0 * math.pi * min(cutoff, 0.45 * self.sample_rate) / self.sample_rate)
        white = self.rng.standard_normal(length)
        low = np.empty(length, dtype=np.float64)
        state = 0.0
        for index, sample in enumerate(white):
            state += alpha * (sample - state)
            low[index] = state
        # A unit fundamental component prevents a random short noise burst from
        # accidentally suppressing the played pitch in its 1 s FFT estimate. It
        # remains seed-independent, while the noisy part retains the plucked grain.
        phase = float(self.rng.uniform(0.0, 2.0 * math.pi))
        low += np.sin(phase + 2.0 * math.pi * frequency * np.arange(length) / self.sample_rate)
        pick_delay = min(length - 1, max(1, int(round(float(pick_position) * length))))
        # Keep the finite-difference filter's trailing tap after the white-noise
        # burst; truncating it would leave an artificial DC offset in the loop.
        comb = np.zeros(length + pick_delay, dtype=np.float64)
        comb[:length] = low
        comb[pick_delay : pick_delay + length] -= low
        # A fixed headroom factor keeps a full 8-note strum below the master ceiling.
        return (comb * (0.0125 * min(max(float(velocity), 0.0), 1.0))).astype(np.float32)


class BowExciter:
    """Seeded band-limited noise bow with the documented linear envelope/flutters.

    This is a linear excitation approximation; it is not a nonlinear friction or
    stick-slip model. It uses an 80 ms attack, 25-40 Hz deterministic rosin flutter,
    depth `noise * .3`, and a 150 ms release fade.
    """

    def __init__(self, sample_rate: int, rng: np.random.Generator) -> None:
        self.sample_rate = sample_rate
        self.rng = rng
        self.filter: Biquad | None = None
        self.pitch = 60.0
        self.velocity = 0.0
        self.speed = 0.0
        self.noise_depth = 0.0
        self.flutter_rate = 30.0
        self.flutter_phase = 0.0
        self.held_frames = 0
        self.release_frame: int | None = None

    def start(self, pitch: float, velocity: float, pressure: float, speed: float, noise: float) -> None:
        self.pitch = float(pitch)
        self.velocity = float(velocity)
        self.speed = min(max(float(speed), 0.0), 1.0)
        self.noise_depth = min(max(float(noise), 0.0), 1.0) * 0.3
        self.flutter_rate = float(self.rng.uniform(25.0, 40.0))
        self.flutter_phase = float(self.rng.uniform(0.0, 2.0 * math.pi))
        center = midi_frequency(self.pitch) * (2.0 + 6.0 * min(max(float(pressure), 0.0), 1.0))
        center = min(max(center, 20.0), 0.45 * self.sample_rate)
        q = 2.0 + 2.0 * min(max(float(pressure), 0.0), 1.0)
        self.filter = Biquad(self.sample_rate, kind="bandpass", cutoff=center, q=q)
        self.held_frames = 0
        self.release_frame = None

    def release(self) -> None:
        if self.release_frame is None:
            self.release_frame = 0

    def retarget(self, pitch: float, pressure: float) -> None:
        """Glide the bowed excitation filter while preserving its internal state."""
        self.pitch = float(pitch)
        self.set_controls(pressure=pressure)

    def set_controls(self, *, pressure: float, speed: float | None = None, noise: float | None = None) -> None:
        normalized_pressure = min(max(float(pressure), 0.0), 1.0)
        if speed is not None:
            self.speed = min(max(float(speed), 0.0), 1.0)
        if noise is not None:
            self.noise_depth = min(max(float(noise), 0.0), 1.0) * 0.3
        if self.filter is None:
            return
        center = midi_frequency(self.pitch) * (2.0 + 6.0 * normalized_pressure)
        center = min(max(center, 20.0), 0.45 * self.sample_rate)
        q = 2.0 + 2.0 * normalized_pressure
        self.filter.set_parameters(cutoff=center, q=q)

    def process(self, frames: int) -> np.ndarray:
        if frames <= 0:
            return np.zeros(0, dtype=np.float32)
        if self.filter is None:
            return np.zeros(frames, dtype=np.float32)
        band = self.filter.process(self.rng.standard_normal(frames)).astype(np.float64)
        positions = self.held_frames + np.arange(frames, dtype=np.float64)
        attack_frames = max(1, int(round(0.080 * self.sample_rate)))
        attack = np.minimum(1.0, (positions + 1.0) / attack_frames)
        flutter_angles = self.flutter_phase + 2.0 * math.pi * self.flutter_rate * np.arange(frames) / self.sample_rate
        flutter = 1.0 + self.noise_depth * np.sin(flutter_angles)
        self.flutter_phase = float((flutter_angles[-1] + 2.0 * math.pi * self.flutter_rate / self.sample_rate) % (2.0 * math.pi))
        envelope = attack
        if self.release_frame is not None:
            release_positions = self.release_frame + np.arange(frames, dtype=np.float64)
            envelope = envelope * np.maximum(0.0, 1.0 - release_positions / max(1.0, 0.150 * self.sample_rate))
            self.release_frame += frames
        self.held_frames += frames
        return (band * envelope * flutter * self.velocity * self.speed * 0.08).astype(np.float32)


__all__ = ["BowExciter", "PluckExciter"]
