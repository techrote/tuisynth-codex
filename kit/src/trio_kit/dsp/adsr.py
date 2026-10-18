"""Vectorized attack, decay, sustain and release envelope."""

from __future__ import annotations

import math

import numpy as np

from trio_kit.dsp._validation import finite_number, frame_count, positive_sample_rate


_NINETY_NINE_PERCENT = math.log(100.0)


class Adsr:
    """Block envelope with linear attack and 99-percent exponential stages."""

    def __init__(
        self,
        sample_rate: int = 48_000,
        *,
        attack: float = 0.01,
        decay: float = 0.1,
        sustain: float = 0.7,
        release: float = 0.2,
    ) -> None:
        self.sample_rate = positive_sample_rate(sample_rate)
        self._attack = finite_number(attack, "attack", minimum=0)
        self._decay = finite_number(decay, "decay", minimum=0)
        self._sustain = finite_number(sustain, "sustain", minimum=0, maximum=1)
        self._release = finite_number(release, "release", minimum=0)
        self._durations = self._duration_samples()
        self.reset()

    @property
    def attack(self) -> float:
        return self._attack

    @property
    def decay(self) -> float:
        return self._decay

    @property
    def sustain(self) -> float:
        return self._sustain

    @property
    def release(self) -> float:
        return self._release

    def _duration_samples(self) -> tuple[int, int, int]:
        return (
            max(0, int(round(self._attack * self.sample_rate))),
            max(0, int(round(self._decay * self.sample_rate))),
            max(0, int(round(self._release * self.sample_rate))),
        )

    def set_parameters(
        self,
        *,
        attack: float | None = None,
        decay: float | None = None,
        sustain: float | None = None,
        release: float | None = None,
    ) -> None:
        """Update stage settings without discontinuously changing the output."""
        values = (
            finite_number(self._attack if attack is None else attack, "attack", minimum=0),
            finite_number(self._decay if decay is None else decay, "decay", minimum=0),
            finite_number(self._sustain if sustain is None else sustain, "sustain", minimum=0, maximum=1),
            finite_number(self._release if release is None else release, "release", minimum=0),
        )
        old_values = (self._attack, self._decay, self._sustain, self._release)
        if values == old_values:
            return

        old_durations = self._durations
        self._attack, self._decay, self._sustain, self._release = values
        self._durations = self._duration_samples()

        if self._stage == "sustain" and values[2] != old_values[2]:
            self._value = self._velocity * self._sustain
            self._stage_target = self._value
        elif self._stage == "attack" and self._durations[0] != old_durations[0]:
            if self._durations[0] == 0:
                self._value = self._stage_target
                self._enter_decay()
            else:
                self._stage_start = self._value
                self._elapsed = 0
        elif self._stage == "decay" and (
            self._durations[1] != old_durations[1] or values[2] != old_values[2]
        ):
            self._stage_start = self._value
            self._stage_target = self._velocity * self._sustain
            self._elapsed = 0
            if self._durations[1] == 0:
                self._value = self._stage_target
                self._stage = "sustain"
        elif self._stage == "release" and self._durations[2] != old_durations[2]:
            if self._durations[2] == 0:
                self._value = 0.0
                self._stage = "idle"
            else:
                self._stage_start = self._value
                self._elapsed = 0

    @property
    def finished(self) -> bool:
        return self._stage == "idle"

    @property
    def value(self) -> float:
        return self._value

    @property
    def stage(self) -> str:
        return self._stage

    def reset(self) -> None:
        self._stage = "idle"
        self._value = 0.0
        self._stage_start = 0.0
        self._stage_target = 0.0
        self._elapsed = 0
        self._velocity = 0.0

    def gate_on(self, velocity: float = 1.0) -> None:
        self._velocity = finite_number(velocity, "velocity", minimum=0, maximum=1)
        self._stage_start = self._value
        self._stage_target = self._velocity
        self._elapsed = 0
        attack_samples = self._durations[0]
        if attack_samples == 0:
            self._value = self._stage_target
            self._enter_decay()
        else:
            self._stage = "attack"

    def gate_off(self) -> None:
        if self._stage in {"idle", "release"}:
            return
        self._stage_start = self._value
        self._stage_target = 0.0
        self._elapsed = 0
        if self._durations[2] == 0 or self._value == 0:
            self._value = 0.0
            self._stage = "idle"
        else:
            self._stage = "release"

    def _enter_decay(self) -> None:
        self._stage_start = self._value
        self._stage_target = self._velocity * self.sustain
        self._elapsed = 0
        if self._durations[1] == 0:
            self._value = self._stage_target
            self._stage = "sustain"
        else:
            self._stage = "decay"

    def process(self, frames: int) -> np.ndarray:
        frame_count(frames)
        output = np.empty(frames, dtype=np.float32)
        cursor = 0
        while cursor < frames:
            if self._stage == "idle":
                output[cursor:] = 0.0
                break
            if self._stage == "sustain":
                output[cursor:] = self._value
                break

            duration = self._durations[0] if self._stage == "attack" else (
                self._durations[1] if self._stage == "decay" else self._durations[2]
            )
            count = min(frames - cursor, duration - self._elapsed)
            positions = self._elapsed + np.arange(1, count + 1, dtype=np.float64)
            if self._stage == "attack":
                values = self._stage_start + (self._stage_target - self._stage_start) * (positions / duration)
            elif self._stage == "decay":
                remaining = np.exp(-_NINETY_NINE_PERCENT * positions / duration)
                values = self._stage_target + (self._stage_start - self._stage_target) * remaining
            else:
                values = self._stage_start * np.exp(-_NINETY_NINE_PERCENT * positions / duration)
            output[cursor : cursor + count] = values.astype(np.float32)
            cursor += count
            self._elapsed += count
            self._value = float(values[-1])

            if self._elapsed >= duration:
                if self._stage == "attack":
                    self._value = self._stage_target
                    self._enter_decay()
                elif self._stage == "decay":
                    self._value = self._stage_target
                    self._stage = "sustain"
                else:
                    self._value = 0.0
                    self._stage = "idle"
        return output


__all__ = ["Adsr"]
