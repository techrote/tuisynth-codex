from __future__ import annotations

import math

import numpy as np

from trio_loom.excitation import BowExciter, PluckExciter
from trio_loom.waveguide import WaveguideString, midi_frequency


def _scalar_reference(waveguide: WaveguideString, excitation: np.ndarray, t60: float) -> np.ndarray:
    output = np.zeros(len(excitation), dtype=np.float64)
    rho = 10.0 ** (-3.0 * waveguide.loop_samples / (waveguide.sample_rate * t60))
    for index, sample in enumerate(excitation):
        feedback = 0.0
        for tap, distance in zip(waveguide.taps, range(waveguide.delay, waveguide.delay + 3)):
            previous = index - distance
            if previous >= 0:
                feedback += float(tap) * output[previous]
        output[index] = float(sample) + rho * feedback
    return output.astype(np.float32)


def _fft_peak_frequency(samples: np.ndarray, sample_rate: int) -> float:
    window = np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(samples * window))
    frequencies = np.fft.rfftfreq(len(samples), 1.0 / sample_rate)
    peak = int(np.argmax(spectrum[1:]) + 1)
    logs = np.log(np.maximum(spectrum[peak - 1 : peak + 2], np.finfo(float).tiny))
    denominator = logs[0] - 2.0 * logs[1] + logs[2]
    fraction = 0.5 * (logs[0] - logs[2]) / denominator if denominator else 0.0
    return float((peak + fraction) * sample_rate / len(samples))


def test_chunked_waveguide_matches_scalar_reference() -> None:
    rng = np.random.default_rng(19)
    excitation = rng.normal(0.0, 0.01, 4_096).astype(np.float32)
    actual_loop = WaveguideString(48_000, 57.25, 0.37)
    expected_loop = WaveguideString(48_000, 57.25, 0.37)

    actual = actual_loop.process(excitation, 3.7)
    expected = _scalar_reference(expected_loop, excitation, 3.7)

    assert actual.dtype == np.float32
    assert np.max(np.abs(actual - expected)) < 1e-6


def test_fundamental_is_tuned_within_five_cents_across_the_playable_notes() -> None:
    sample_rate = 48_000
    for pitch in range(24, 101):
        excitation = PluckExciter(sample_rate, np.random.default_rng(4)).excite(pitch, 1.0, 0.55, 0.13)
        signal = np.concatenate((excitation, np.zeros(sample_rate - len(excitation), dtype=np.float32)))
        rendered = WaveguideString(sample_rate, pitch, 0.6).process(signal, 6.0)
        estimated = _fft_peak_frequency(rendered, sample_rate)
        cents = 1200.0 * math.log2(estimated / midi_frequency(pitch))
        assert abs(cents) <= 5.0


def test_t60_matches_the_requested_decay_for_short_medium_and_long_settings() -> None:
    sample_rate = 48_000
    pitch = 52
    frequency = midi_frequency(pitch)
    window_size = 4_800
    times = np.arange(window_size, dtype=np.float64) / sample_rate
    for requested in (1.0, 4.0, 10.0):
        excitation = PluckExciter(sample_rate, np.random.default_rng(42)).excite(pitch, 1.0, 0.55, 0.13)
        tail = np.zeros(round((requested + 0.1) * sample_rate), dtype=np.float32)
        rendered = WaveguideString(sample_rate, pitch, 0.6).process(np.concatenate((excitation, tail)), requested)
        centers: list[float] = []
        levels: list[float] = []
        for start in range(window_size, int(requested * sample_rate), window_size):
            segment = rendered[start : start + window_size].astype(np.float64)
            cosine = 2.0 / window_size * np.sum(segment * np.cos(2.0 * math.pi * frequency * times))
            sine = 2.0 / window_size * np.sum(segment * np.sin(2.0 * math.pi * frequency * times))
            level = math.hypot(float(cosine), float(sine))
            if level > 1e-10:
                centers.append((start + window_size / 2) / sample_rate)
                levels.append(level)
        slope = float(np.polyfit(centers, np.log(levels), 1)[0])
        measured = math.log(1_000.0) / -slope
        assert abs(measured - requested) / requested <= 0.25


def test_small_pitch_retarget_preserves_history_without_a_sample_jump() -> None:
    sample_rate = 48_000
    pitch = 60.0
    excitation = PluckExciter(sample_rate, np.random.default_rng(31)).excite(pitch, 1.0, 0.7, 0.18)
    loop = WaveguideString(sample_rate, pitch, 0.65)
    first = loop.process(np.pad(excitation, (0, 512)), 6.0)
    loop.retarget(60.1)
    second = loop.process(np.zeros(256, dtype=np.float32), 6.0)

    assert loop.write_index == len(first) + len(second)
    assert abs(float(second[0] - first[-1])) < 0.02
    assert np.isfinite(second).all()


def test_seeded_pluck_is_repeatable_velocity_scaled_and_has_a_finite_comb_tail() -> None:
    first = PluckExciter(48_000, np.random.default_rng(7)).excite(57, 1.0, 0.6, 0.21)
    duplicate = PluckExciter(48_000, np.random.default_rng(7)).excite(57, 1.0, 0.6, 0.21)
    half = PluckExciter(48_000, np.random.default_rng(7)).excite(57, 0.5, 0.6, 0.21)
    loop_samples = round(48_000 / midi_frequency(57))
    pick_delay = round(0.21 * loop_samples)

    assert len(first) == loop_samples + pick_delay
    assert np.array_equal(first, duplicate)
    assert np.allclose(half, first * 0.5)
    assert abs(float(np.sum(first, dtype=np.float64))) < 1e-5
    assert np.isfinite(first).all() and np.any(first)


def test_bow_has_seeded_attack_flutter_and_a_150_ms_release_fade() -> None:
    def process_in_blocks(bow: BowExciter, frames: int) -> np.ndarray:
        return np.concatenate([bow.process(min(256, frames - start)) for start in range(0, frames, 256)])

    def render_bow() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        bow = BowExciter(48_000, np.random.default_rng(91))
        bow.start(55, 0.8, pressure=0.6, speed=0.7, noise=0.8)
        attack_a = process_in_blocks(bow, 1_920)
        attack_b = process_in_blocks(bow, 1_920)
        bow.release()
        release = process_in_blocks(bow, 7_200)
        return attack_a, attack_b, release

    first = render_bow()
    second = render_bow()
    assert all(np.array_equal(a, b) for a, b in zip(first, second))
    assert np.sqrt(np.mean(first[1] ** 2)) > np.sqrt(np.mean(first[0] ** 2))
    # The excitation reaches zero at 150 ms; the stateful band-pass retains its
    # natural short resonant tail and is below -86 dBFS by the end of that window.
    assert np.max(np.abs(first[2][-32:])) < 5e-5
    assert all(np.isfinite(part).all() for part in first)
