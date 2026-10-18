from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import freqz

from trio_kit.constants import BLOCK
from trio_kit.dsp import Biquad, DelayLine


def random_chunks(total: int, seed: int = 4) -> list[int]:
    rng = np.random.default_rng(seed)
    chunks: list[int] = []
    remaining = total
    while remaining:
        count = min(remaining, int(rng.integers(1, BLOCK + 1)))
        chunks.append(count)
        remaining -= count
    return chunks


def process_filter(filter_: Biquad, signal: np.ndarray, chunks: list[int]) -> np.ndarray:
    output: list[np.ndarray] = []
    cursor = 0
    for count in chunks:
        output.append(filter_.process(signal[cursor : cursor + count]))
        cursor += count
    return np.concatenate(output)


@pytest.mark.parametrize("kind", ("lowpass", "bandpass", "highpass", "peaking"))
def test_rbj_filter_frequency_responses(kind: str) -> None:
    filter_ = Biquad(48_000, kind=kind, cutoff=1_000, q=0.707, gain_db=12)
    b, a = filter_.coefficients
    frequencies, response = freqz(b, a, worN=16_384, fs=48_000)
    at_cutoff = np.abs(response[np.argmin(np.abs(frequencies - 1_000))])

    if kind in {"lowpass", "highpass"}:
        assert at_cutoff == pytest.approx(2 ** -0.5, abs=0.01)
    elif kind == "bandpass":
        assert at_cutoff == pytest.approx(1, abs=0.02)
    else:
        assert 20 * np.log10(at_cutoff) == pytest.approx(12, abs=0.05)


def test_high_q_biquad_remains_finite_and_stateful() -> None:
    filter_ = Biquad(48_000, kind="bandpass", cutoff=20, q=20)
    rng = np.random.default_rng(101)
    outputs = [filter_.process(rng.normal(0, 4, (BLOCK, 2))) for _ in range(80)]
    assert all(np.isfinite(output).all() for output in outputs)
    assert np.isfinite(np.concatenate(outputs)).all()


def test_biquad_static_and_smoothed_parameters_are_chunking_equivalent() -> None:
    rng = np.random.default_rng(77)
    signal = rng.normal(0, 0.5, (2_048, 2)).astype(np.float32)
    reference_filter = Biquad(48_000, kind="lowpass", cutoff=500)
    chunked_filter = Biquad(48_000, kind="lowpass", cutoff=500)
    reference = process_filter(reference_filter, signal, [BLOCK] * 8)
    chunked = process_filter(chunked_filter, signal, random_chunks(len(signal), 89))
    assert np.allclose(chunked, reference, rtol=0, atol=1e-7)

    reference_filter.reset()
    chunked_filter.reset()
    reference_filter.set_parameters(cutoff=5_000, q=2)
    chunked_filter.set_parameters(cutoff=5_000, q=2)
    swept_reference = process_filter(reference_filter, signal[:240], [240])
    swept_chunked = process_filter(chunked_filter, signal[:240], random_chunks(240, 91))
    assert np.allclose(swept_chunked, swept_reference, rtol=0, atol=1e-7)
    assert reference_filter.current_cutoff == pytest.approx(5_000)
    assert chunked_filter.current_cutoff == pytest.approx(5_000)


def test_biquad_retarget_during_a_partial_smoothing_span_uses_current_parameters() -> None:
    filter_ = Biquad(48_000, cutoff=1_000)
    filter_.set_parameters(cutoff=5_000)
    filter_.process(np.zeros(13, dtype=np.float32))
    expected = 1_000 + (5_000 - 1_000) * 13 / 240
    assert filter_.current_cutoff == pytest.approx(expected)

    filter_.set_parameters(cutoff=9_000)
    assert filter_.current_cutoff == pytest.approx(expected)
    filter_.process(np.zeros(240, dtype=np.float32))
    assert filter_.current_cutoff == pytest.approx(9_000)


def test_biquad_validates_limits_and_channel_layout() -> None:
    with pytest.raises(ValueError, match="cutoff"):
        Biquad(cutoff=21_601)
    with pytest.raises(ValueError, match="q"):
        Biquad(q=21)
    filter_ = Biquad()
    filter_.process(np.zeros(16, dtype=np.float32))
    with pytest.raises(ValueError, match="channel layout"):
        filter_.process(np.zeros((16, 1), dtype=np.float32))
    filter_.reset()
    assert filter_.process(np.zeros((16, 2), dtype=np.float32)).shape == (16, 2)
    mono_filter = Biquad()
    assert mono_filter.process(np.zeros(16, dtype=np.float64)).dtype == np.float32
    with pytest.raises(ValueError, match="real numeric"):
        Biquad().process(np.zeros(16, dtype=np.complex64))


def test_delay_line_chronology_fractional_reads_and_reset() -> None:
    line = DelayLine(32)
    line.write(np.arange(8, dtype=np.float32))
    assert np.array_equal(line.read(4, 4), np.arange(4, 8, dtype=np.float32))

    line.reset()
    ramp = np.arange(8, dtype=np.float32)
    delayed = line.process(ramp, 1.5)
    assert delayed == pytest.approx((0, 0, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5))
    assert line.write_count == 8


def test_delay_line_random_chunking_matches_one_shot() -> None:
    rng = np.random.default_rng(31)
    signal = rng.normal(size=(2_048, 2)).astype(np.float32)
    reference_line = DelayLine(128, channels=2)
    chunked_line = DelayLine(128, channels=2)
    reference = np.concatenate([reference_line.process(signal[offset : offset + BLOCK], 31.25) for offset in range(0, len(signal), BLOCK)])
    output = []
    cursor = 0
    for count in random_chunks(len(signal)):
        output.append(chunked_line.process(signal[cursor : cursor + count], 31.25))
        cursor += count
    assert np.array_equal(np.concatenate(output), reference)


def test_delay_line_rejects_invalid_capacity_delay_and_audio_shape() -> None:
    with pytest.raises(ValueError, match="max_delay_samples"):
        DelayLine(0)
    line = DelayLine(32)
    with pytest.raises(ValueError, match="delay"):
        line.process(np.ones(8), 0.5)
    with pytest.raises(ValueError, match="delay"):
        line.process(np.zeros(0), 0.5)
    with pytest.raises(ValueError, match="delay"):
        line.read(float("nan"), 8)
    with pytest.raises(ValueError, match="channels"):
        DelayLine(32, channels=2).write(np.ones(8))
    with pytest.raises(ValueError, match="real numeric"):
        line.process(np.ones(8, dtype=np.float32), np.ones(8, dtype=bool))
