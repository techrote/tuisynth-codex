from __future__ import annotations

import numpy as np
import pytest

from trio_kit.constants import BLOCK
from trio_kit.dsp import Chorus, Reverb, StereoDelay


def random_chunks(total: int, seed: int = 23) -> list[int]:
    rng = np.random.default_rng(seed)
    chunks: list[int] = []
    remaining = total
    while remaining:
        count = min(remaining, int(rng.integers(1, BLOCK + 1)))
        chunks.append(count)
        remaining -= count
    return chunks


def process_chunks(effect: object, signal: np.ndarray, chunks: list[int]) -> np.ndarray:
    output: list[np.ndarray] = []
    cursor = 0
    for count in chunks:
        output.append(effect.process(signal[cursor : cursor + count]))  # type: ignore[attr-defined]
        cursor += count
    return np.concatenate(output)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: Chorus(48_000, rate=1.2, seed=3),
        lambda: StereoDelay(48_000, delay_seconds=0.06, feedback=0.6, mix=0.4),
        lambda: Reverb(48_000, size=0.8, mix=0.4),
    ),
)
def test_stereo_effects_are_chunking_equivalent(factory: object) -> None:
    rng = np.random.default_rng(120)
    signal = rng.normal(0, 0.2, (4_096, 2)).astype(np.float32)
    reference = process_chunks(factory(), signal, [BLOCK] * 16)  # type: ignore[operator]
    chunked = process_chunks(factory(), signal, random_chunks(len(signal), 17))  # type: ignore[operator]

    assert np.allclose(chunked, reference, rtol=0, atol=1e-7)


def test_chorus_taps_stay_in_range_and_mix_zero_is_identity() -> None:
    chorus = Chorus(48_000, base_delay_ms=13.5, depth_ms=6.5, mix=0)
    assert chorus.base_delay_ms - chorus.depth_ms == 7
    assert chorus.base_delay_ms + chorus.depth_ms == 20
    signal = np.random.default_rng(5).normal(size=(BLOCK, 2)).astype(np.float32)
    assert np.array_equal(chorus.process(signal), signal)
    chorus.mix = 0.5
    assert np.isfinite(chorus.process(signal)).all()


def test_stereo_delay_ping_pongs_between_channels_and_stays_finite_at_extreme_feedback() -> None:
    sample_rate = 48_000
    delay_samples = int(0.06 * sample_rate)
    total = 2 * delay_samples + BLOCK
    signal = np.zeros((total, 2), dtype=np.float32)
    signal[0, 0] = 1
    delay = StereoDelay(sample_rate, delay_seconds=0.06, feedback=0.9, mix=1)
    output = process_chunks(delay, signal, [BLOCK] * (total // BLOCK) + ([total % BLOCK] if total % BLOCK else []))

    assert output[delay_samples, 0] > 0
    assert output[delay_samples, 1] == 0
    assert output[2 * delay_samples, 1] > 0
    assert np.isfinite(output).all()
    assert np.max(np.abs(output)) <= 1


def test_stereo_delay_feedback_echoes_decay_over_repeated_traversals() -> None:
    sample_rate = 48_000
    delay_samples = int(0.06 * sample_rate)
    total = 8 * delay_samples + BLOCK
    signal = np.zeros((total, 2), dtype=np.float32)
    signal[0, 0] = 1
    effect = StereoDelay(sample_rate, delay_seconds=0.06, feedback=0.75, mix=1)
    rendered = process_chunks(effect, signal, [BLOCK] * (total // BLOCK) + ([total % BLOCK] if total % BLOCK else []))
    echo_peaks = [float(np.max(np.abs(rendered[index * delay_samples : index * delay_samples + 32]))) for index in range(1, 8)]

    assert all(peak > 0 for peak in echo_peaks)
    assert all(later < earlier for earlier, later in zip(echo_peaks, echo_peaks[1:]))


def test_reverb_mix_zero_is_identity_and_size_keeps_all_lines_longer_than_a_block() -> None:
    reverb = Reverb(48_000, size=0.2, mix=0)
    signal = np.random.default_rng(2).normal(size=(BLOCK, 2)).astype(np.float32)
    assert np.array_equal(reverb.process(signal), signal)
    assert all(delay > BLOCK for delay in reverb.line_delays)

    reverb.set_size(1.6)
    assert reverb.size == 1.6
    assert all(delay > BLOCK for delay in reverb.line_delays)
    reverb.mix = 1
    assert np.isfinite(reverb.process(np.zeros((BLOCK, 2), dtype=np.float32))).all()


def test_reverb_impulse_tail_is_finite_and_falls_below_minus_ninety_db() -> None:
    sample_rate = 48_000
    reverb = Reverb(sample_rate, size=1.6, mix=1)
    signal = np.zeros((BLOCK, 2), dtype=np.float32)
    signal[0] = (1, 0.5)
    output = [reverb.process(signal)]
    silence = np.zeros((BLOCK, 2), dtype=np.float32)
    for _ in range((sample_rate * 8) // BLOCK):
        output.append(reverb.process(silence))
    rendered = np.concatenate(output)

    assert np.isfinite(rendered).all()
    tail = rendered[-int(sample_rate * 0.1) :]
    assert float(np.sqrt(np.mean(np.square(tail, dtype=np.float64)))) < 10 ** (-90 / 20)
    reverb.reset()
    assert reverb.process(silence).shape == (BLOCK, 2)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: Chorus(sample_rate=48_000, base_delay_ms=6.9),
        lambda: Chorus(sample_rate=48_000, rate=6.1),
        lambda: StereoDelay(sample_rate=48_000, delay_seconds=0.05),
        lambda: StereoDelay(sample_rate=48_000, feedback=0.91),
        lambda: Reverb(sample_rate=48_000, size=1.7),
        lambda: Reverb(sample_rate=48_000, mix=-0.1),
    ),
)
def test_effects_reject_out_of_contract_parameters(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()  # type: ignore[operator]


def test_delay_parameter_updates_reject_invalid_values_atomically() -> None:
    effect = StereoDelay(delay_seconds=0.2, feedback=0.3, mix=0.4)
    with pytest.raises(ValueError):
        effect.set_parameters(delay_seconds=0.5, feedback=1)
    assert effect.delay_seconds == 0.2
    assert effect.feedback == 0.3
    assert effect.mix == 0.4
