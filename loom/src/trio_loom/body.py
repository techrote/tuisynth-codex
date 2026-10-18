"""Artistic modal body resonators for string color, not physical body simulation.

The modes below are approximate center frequencies and relative strengths chosen
to make useful guitar, violin, cello, harp, and sitar-like spectral color. They
are not measured modal data or claims about any specific instrument construction.
Size scales each center frequency by 1/body.size; stateful RBJ band-pass filters
retain their tails while their coefficients glide when the size changes within a
body type. Selecting another body type installs its corresponding mode bank.
"""

from __future__ import annotations

import math

import numpy as np

from trio_kit.dsp import Biquad


BODY_MODES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "none": (),
    "guitar": ((110, 2.0, 0.8), (220, 2.2, 0.7), (410, 3.2, 0.55), (780, 4.0, 0.45), (1_350, 4.5, 0.35), (2_300, 5.0, 0.25)),
    "violin": ((280, 3.0, 0.45), (520, 3.2, 0.65), (820, 4.0, 0.8), (1_250, 4.5, 0.65), (2_050, 5.0, 0.55), (3_200, 5.5, 0.35)),
    "cello": ((70, 2.0, 0.85), (145, 2.5, 0.75), (310, 3.0, 0.65), (540, 3.5, 0.55), (900, 4.0, 0.45), (1_800, 4.5, 0.3)),
    "harp": ((90, 2.0, 0.75), (185, 2.5, 0.7), (370, 3.0, 0.6), (740, 3.5, 0.5), (1_480, 4.0, 0.38), (2_960, 4.5, 0.25)),
    "sitar": ((120, 2.0, 0.35), (240, 2.5, 0.45), (480, 3.0, 0.55), (960, 3.5, 0.65), (1_920, 4.0, 0.7), (3_840, 4.5, 0.5), (5_200, 5.0, 0.3)),
}


class BodyResonator:
    """Parallel stateful band-pass modes with safe, smoothed retuning."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.mode_name = "none"
        self.size = 1.0
        self.filters: tuple[Biquad, ...] = ()
        self.weights = np.zeros(0, dtype=np.float64)

    def configure(self, mode_name: str, size: float) -> None:
        if mode_name not in BODY_MODES:
            raise ValueError("unknown body mode")
        normalized_size = float(size)
        if not math.isfinite(normalized_size) or not 0.5 <= normalized_size <= 2.0:
            raise ValueError("body size must be finite and in the range 0.5..2")
        modes = BODY_MODES[mode_name]
        if mode_name == self.mode_name and normalized_size == self.size:
            return
        if mode_name == self.mode_name and len(modes) == len(self.filters):
            for filt, (frequency, q, _gain) in zip(self.filters, modes):
                cutoff = min(0.45 * self.sample_rate, max(20.0, frequency / normalized_size))
                filt.set_parameters(cutoff=cutoff, q=q)
        else:
            self.filters = tuple(
                Biquad(
                    self.sample_rate,
                    kind="bandpass",
                    cutoff=min(0.45 * self.sample_rate, max(20.0, frequency / normalized_size)),
                    q=q,
                )
                for frequency, q, _gain in modes
            )
        self.weights = np.asarray([gain for _frequency, _q, gain in modes], dtype=np.float64)
        self.mode_name = mode_name
        self.size = normalized_size

    def process(self, buffer: np.ndarray) -> np.ndarray:
        if not self.filters:
            return np.zeros_like(buffer, dtype=np.float32)
        mono = np.mean(np.asarray(buffer, dtype=np.float64), axis=1)
        wet = np.zeros(len(mono), dtype=np.float64)
        for filt, weight in zip(self.filters, self.weights):
            wet += filt.process(mono).astype(np.float64) * weight
        wet *= 0.7 / math.sqrt(len(self.filters))
        return np.column_stack((wet, wet)).astype(np.float32)

    def reset(self) -> None:
        for filt in self.filters:
            filt.reset()


__all__ = ["BODY_MODES", "BodyResonator"]
