from __future__ import annotations

import math

import numpy as np

from trio_kit.engine.master import MasterBus
from trio_kit.constants import OUTPUT_CEILING


def test_hot_noise_and_square_wave_stay_finite_under_the_output_ceiling() -> None:
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 12, (20_000, 2)).astype(np.float32)
    square = np.where(np.arange(20_000)[:, None] % 2, 30.0, -30.0).astype(np.float32)
    signal = np.concatenate((noise, np.repeat(square, 2, axis=1)), axis=0)
    master = MasterBus(drive=0.8)

    output = master.process(signal)

    assert output.shape == signal.shape
    assert np.isfinite(output).all()
    assert np.max(np.abs(output)) <= OUTPUT_CEILING
    assert master.limited_blocks > 0
    assert master.last_limiter_gain < 1


def test_vector_limiter_matches_a_slow_recurrence_reference() -> None:
    rng = np.random.default_rng(105)
    signal = rng.normal(0, 1.4, (1_000, 2)).astype(np.float32)
    master = MasterBus(sample_rate=48_000, ceiling=0.8, dc_hz=10)
    master._envelope = 0.43
    decay = math.exp(-1 / (0.12 * 48_000))
    envelope = 0.43
    expected = np.empty_like(signal)
    gains: list[float] = []
    for index, frame in enumerate(signal):
        envelope = max(float(np.max(np.abs(frame))), envelope * decay)
        gain = min(1.0, 0.8 / max(envelope, np.finfo(np.float64).tiny))
        gains.append(gain)
        expected[index] = frame * gain

    actual = master._limit(signal)

    assert np.allclose(actual, expected, rtol=1e-6, atol=1e-7)
    assert np.isclose(master.envelope, envelope, rtol=1e-12, atol=1e-12)
    assert master.last_limiter_gain == min(gains)
    assert np.max(np.abs(actual)) <= 0.8


def test_dc_blocker_removes_a_constant_offset_and_carries_state_across_calls() -> None:
    signal = np.ones((48_000, 2), dtype=np.float32)
    whole = MasterBus().process(signal)
    assert np.max(np.abs(whole[-2_000:])) < 1e-4

    split = MasterBus()
    first = split.process(signal[:7_777])
    second = split.process(signal[7_777:])
    assert np.allclose(np.concatenate((first, second)), whole, rtol=0, atol=1e-7)


def test_nonfinite_input_resets_filter_and_limiter_state_and_returns_silence() -> None:
    master = MasterBus()
    master.process(np.full((512, 2), 2, dtype=np.float32))
    assert master.envelope > 0
    bad = np.ones((256, 2), dtype=np.float32)
    bad[17, 1] = np.nan

    result = master.process(bad)

    assert np.array_equal(result, np.zeros_like(result))
    assert master.nonfinite_resets == 1
    assert master.envelope == 0
    assert master.last_limiter_gain == 1


def test_invalid_master_configuration_and_buffer_shapes_are_rejected() -> None:
    for sample_rate in (0, True):
        try:
            MasterBus(sample_rate=sample_rate)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError("invalid sample rate must be rejected")
    for ceiling in (0, 1.01, float("nan")):
        try:
            MasterBus(ceiling=ceiling)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid ceiling must be rejected")
    try:
        MasterBus().process(np.ones(12, dtype=np.float32))
    except ValueError as error:
        assert "shape" in str(error)
    else:
        raise AssertionError("non-stereo buffers must be rejected")
