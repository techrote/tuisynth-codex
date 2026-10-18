"""Polyphonic LOOM pluck and bowed-string voices."""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

from trio_kit.params import ParamSnapshot
from trio_loom.excitation import BowExciter, PluckExciter
from trio_loom.waveguide import WaveguideString


_PLAYABLE_LOW = 24.0
_PLAYABLE_HIGH = 100.0
_QUIET_THRESHOLD = 10.0 ** (-90.0 / 20.0)


def _choice(params: ParamSnapshot, key: str, choices: tuple[str, ...]) -> str:
    index = int(params[key])
    return choices[min(max(index, 0), len(choices) - 1)]


class LoomVoice:
    """One waveguide string with seeded pluck or linear bow excitation."""

    def __init__(
        self,
        sample_rate: int,
        rng: np.random.Generator,
        report: Callable[[int, float, float], None] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.rng = rng
        self.waveguide = WaveguideString(sample_rate)
        self.pluck = PluckExciter(sample_rate, rng)
        self.bow = BowExciter(sample_rate, rng)
        self._report = report
        self._excitation = np.zeros(0, dtype=np.float32)
        self._excitation_cursor = 0
        self.pitch = 60.0
        self.velocity = 0.0
        self.mode = "pluck"
        self.finished = True
        self._released = False
        self._release_elapsed = 0
        self._release_from_t60 = 6.0
        self._last_t60 = 6.0
        self._pressure = 0.5
        self._quiet_frames = 0
        self._last_level = 0.0
        self._choke_total = 0
        self._choke_position = 0

    def start(self, pitch: float, velocity: float, params: ParamSnapshot) -> None:
        self._start(pitch, velocity, params, None)

    def start_event(self, pitch: float, velocity: float, params: ParamSnapshot, mode: str) -> None:
        self._start(pitch, velocity, params, mode)

    def _start(self, pitch: float, velocity: float, params: ParamSnapshot, mode_override: str | None) -> None:
        self.pitch = min(_PLAYABLE_HIGH, max(_PLAYABLE_LOW, float(pitch)))
        self.velocity = min(1.0, max(0.0, float(velocity)))
        self.mode = mode_override or _choice(params, "exc.mode", ("pluck", "bow"))
        self.waveguide.reset()
        self.waveguide.set_brightness(float(params["str.bright"]))
        self.waveguide.set_pitch(self.pitch)
        self._excitation_cursor = 0
        self._released = False
        self._release_elapsed = 0
        self._release_from_t60 = float(params["str.decay"])
        self._last_t60 = self._release_from_t60
        self._pressure = float(params["exc.pressure"])
        self._quiet_frames = 0
        self._last_level = 0.0
        self._choke_total = 0
        self._choke_position = 0
        self.finished = False
        if self.mode == "pluck":
            self._excitation = self.pluck.excite(
                self.pitch,
                self.velocity,
                float(params["exc.hardness"]),
                float(params["str.pickpos"]),
            )
        else:
            self._excitation = np.zeros(0, dtype=np.float32)
            self.bow.start(
                self.pitch,
                self.velocity,
                float(params["exc.pressure"]),
                float(params["exc.speed"]),
                float(params["exc.noise"]),
            )
        if self._report is not None:
            self._report(id(self), self.pitch, 0.0)

    def release(self) -> None:
        if self.finished or self._released:
            return
        self._released = True
        self._release_elapsed = 0
        if self.mode == "bow":
            self.bow.release()

    def choke(self) -> None:
        """Mute this string with a short anti-click fade."""
        if self.finished:
            return
        self.release()
        self._choke_total = max(1, int(round(0.005 * self.sample_rate)))
        self._choke_position = 0

    def retarget(self, pitch: float) -> None:
        if self.finished:
            return
        self.pitch = min(_PLAYABLE_HIGH, max(_PLAYABLE_LOW, float(pitch)))
        self.waveguide.retarget(self.pitch)
        if self.mode == "bow":
            self.bow.retarget(self.pitch, self._pressure)

    def render(self, frames: int, params: ParamSnapshot) -> np.ndarray:
        if frames <= 0 or self.finished:
            return np.zeros((max(0, frames), 2), dtype=np.float32)
        brightness = float(params["str.bright"])
        if brightness != self.waveguide.brightness:
            self.waveguide.set_brightness(brightness)
        if self.mode == "pluck":
            excitation = np.zeros(frames, dtype=np.float32)
            remaining = len(self._excitation) - self._excitation_cursor
            count = min(frames, max(0, remaining))
            if count:
                excitation[:count] = self._excitation[
                    self._excitation_cursor : self._excitation_cursor + count
                ]
                self._excitation_cursor += count
        else:
            self._pressure = float(params["exc.pressure"])
            self.bow.set_controls(
                pressure=self._pressure,
                speed=float(params["exc.speed"]),
                noise=float(params["exc.noise"]),
            )
            excitation = self.bow.process(frames)

        held_decay = float(params["str.decay"])
        if not self._released:
            self._last_t60 = held_decay
            t60 = np.full(frames, held_decay, dtype=np.float64)
        else:
            release_decay = float(params["str.release"])
            fade_frames = max(1, int(round(0.020 * self.sample_rate)))
            position = self._release_elapsed + np.arange(frames, dtype=np.float64)
            mix = np.minimum(1.0, position / fade_frames)
            t60 = self._release_from_t60 + (release_decay - self._release_from_t60) * mix
            self._release_elapsed += frames
            self._last_t60 = release_decay

        mono = self.waveguide.process(excitation, t60).astype(np.float64)
        if self._choke_total:
            count = min(frames, self._choke_total - self._choke_position)
            gains = np.maximum(
                0.0,
                1.0 - (self._choke_position + np.arange(count, dtype=np.float64)) / self._choke_total,
            )
            mono[:count] *= gains
            if count < frames:
                mono[count:] = 0.0
            self._choke_position += count
            if self._choke_position >= self._choke_total:
                self.finished = True
                mono.fill(0.0)
        peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
        rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64)))) if len(mono) else 0.0
        self._last_level = rms
        if self._released:
            if peak <= _QUIET_THRESHOLD:
                self._quiet_frames += frames
            else:
                # Count only the quiet suffix of this block so that a transient at
                # its start cannot prematurely finish a later loud section.
                below = np.abs(mono) <= _QUIET_THRESHOLD
                quiet_suffix = 0
                for sample_is_quiet in below[::-1]:
                    if not sample_is_quiet:
                        break
                    quiet_suffix += 1
                self._quiet_frames = quiet_suffix
            if self._quiet_frames >= int(round(0.100 * self.sample_rate)):
                self.finished = True
                mono.fill(0.0)
        if self._report is not None:
            self._report(id(self), self.pitch, 0.0 if self.finished else rms)
        return np.column_stack((mono, mono)).astype(np.float32)


__all__ = ["LoomVoice"]
