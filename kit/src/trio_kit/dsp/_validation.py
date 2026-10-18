"""Shared validation for public DSP block processors."""

from __future__ import annotations

import math
from numbers import Real

import numpy as np

from trio_kit.constants import BLOCK


def positive_sample_rate(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("sample_rate must be a positive integer")
    return value


def finite_number(value: object, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum:g}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be no greater than {maximum:g}")
    return result


def frame_count(value: object, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("frames must be an integer")
    minimum = 0 if allow_zero else 1
    if not minimum <= value <= BLOCK:
        raise ValueError(f"frames must be in the range {minimum}..{BLOCK}")
    return value


def audio_buffer(buffer: object, *, channels: int | None = None) -> tuple[np.ndarray, bool]:
    try:
        raw = np.asarray(buffer)
        if raw.dtype.kind not in "biuf":
            raise ValueError("audio input must be real numeric samples")
        samples = np.asarray(raw, dtype=np.float32)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("audio input must contain finite numeric samples") from error
    mono = samples.ndim == 1
    if mono:
        if channels not in (None, 1):
            raise ValueError(f"audio input must have {channels} channels")
        samples = samples[:, None]
    elif samples.ndim == 2:
        if channels is not None and samples.shape[1] != channels:
            raise ValueError(f"audio input must have {channels} channels")
    else:
        raise ValueError("audio input must have shape (frames,) or (frames, channels)")
    frame_count(len(samples))
    if channels is not None and samples.shape[1] != channels:
        raise ValueError(f"audio input must have {channels} channels")
    if not np.isfinite(samples).all():
        raise ValueError("audio input must contain only finite samples")
    return samples, mono


def return_audio(samples: np.ndarray, mono: bool) -> np.ndarray:
    return samples[:, 0] if mono else samples
