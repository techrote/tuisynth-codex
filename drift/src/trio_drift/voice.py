"""Six-stream note voice; audio is synthesized by DRIFT's shared grain pool."""

from __future__ import annotations

import numpy as np

from trio_kit.dsp import Adsr
from trio_kit.params import ParamSnapshot


class DriftVoice:
    """One seeded note stream whose envelope schedules grains into the instrument."""

    def __init__(self, instrument: object, sample_rate: int, rng: np.random.Generator) -> None:
        self.instrument = instrument
        self.sample_rate = sample_rate
        self.rng = rng
        self.pitch = 60.0
        self.velocity = 0.0
        self._amp = Adsr(sample_rate, attack=0.6, decay=0.8, sustain=0.8, release=2.5)
        self._scheduled_block = -1
        self._arrivals: tuple[int, ...] = ()
        self._arrival_cursor = 0
        self.finished = True

    def start(self, pitch: float, velocity: float, params: ParamSnapshot) -> None:
        self.pitch = float(pitch)
        self.velocity = float(velocity)
        self._amp.reset()
        self._amp.set_parameters(
            attack=float(params["amp.a"]),
            decay=float(params["amp.d"]),
            sustain=float(params["amp.s"]),
            release=float(params["amp.r"]),
        )
        self._amp.gate_on(1.0)
        self._scheduled_block = -1
        self._arrivals = ()
        self._arrival_cursor = 0
        self.finished = False

    def release(self) -> None:
        self._amp.gate_off()

    def retarget(self, pitch: float) -> None:
        self.pitch = float(pitch)

    def render(self, frames: int, params: ParamSnapshot) -> np.ndarray:
        if frames <= 0:
            return np.zeros((max(0, frames), 2), dtype=np.float32)
        if self.finished:
            return np.zeros((frames, 2), dtype=np.float32)
        self._amp.set_parameters(
            attack=float(params["amp.a"]),
            decay=float(params["amp.d"]),
            sustain=float(params["amp.s"]),
            release=float(params["amp.r"]),
        )
        envelope = self._amp.process(frames)
        self.instrument._render_voice(self, envelope, params)
        self.finished = self._amp.finished
        return np.zeros((frames, 2), dtype=np.float32)


__all__ = ["DriftVoice"]
