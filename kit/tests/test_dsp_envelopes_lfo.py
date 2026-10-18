from __future__ import annotations

import numpy as np
import pytest

from trio_kit.constants import BLOCK
from trio_kit.dsp import Adsr, Lfo


def random_chunks(total: int, seed: int = 9) -> list[int]:
    rng = np.random.default_rng(seed)
    chunks: list[int] = []
    remaining = total
    while remaining:
        count = min(remaining, int(rng.integers(1, BLOCK + 1)))
        chunks.append(count)
        remaining -= count
    return chunks


def process_lfo(unit: Lfo, chunks: list[int]) -> np.ndarray:
    return np.concatenate([unit.process(count) for count in chunks])


def test_adsr_timing_and_stages_follow_the_99_percent_definition() -> None:
    envelope = Adsr(48_000, attack=0.01, decay=0.02, sustain=0.5, release=0.01)
    envelope.gate_on(1)

    attack = np.concatenate((envelope.process(256), envelope.process(224)))
    assert attack[0] == pytest.approx(1 / 480)
    assert attack[-1] == pytest.approx(1)
    assert envelope.stage == "decay"

    decay = np.concatenate((envelope.process(256), envelope.process(256), envelope.process(256), envelope.process(192)))
    assert decay[-1] == pytest.approx(0.505, abs=1e-5)
    assert envelope.stage == "sustain"
    assert envelope.process(32) == pytest.approx(np.full(32, 0.5, dtype=np.float32))

    envelope.gate_off()
    release = np.concatenate((envelope.process(256), envelope.process(224)))
    assert release[0] < 0.5
    assert release[-1] == pytest.approx(0.005, abs=1e-5)
    assert envelope.finished
    assert envelope.value == 0
    assert np.isfinite(envelope.process(32)).all()


def test_adsr_retrigger_starts_from_current_value_without_a_click() -> None:
    envelope = Adsr(48_000, attack=0.01, decay=0, sustain=0.8, release=0.02)
    envelope.gate_on(0.5)
    before = envelope.process(120)
    previous = float(before[-1])

    envelope.gate_on(1.0)
    first = float(envelope.process(1)[0])

    assert first > previous
    assert first - previous < 0.01
    assert envelope.stage == "attack"


def test_adsr_parameter_updates_preserve_continuity_and_validate_atomically() -> None:
    envelope = Adsr(48_000, attack=0.02, decay=0.04, sustain=0.4, release=0.1)
    envelope.gate_on(0.8)
    envelope.process(120)
    before = envelope.value

    with pytest.raises(ValueError, match="sustain"):
        envelope.set_parameters(attack=0.01, sustain=1.2)
    assert envelope.attack == 0.02
    assert envelope.sustain == 0.4
    assert envelope.value == before

    envelope.set_parameters(attack=0.01)
    after = float(envelope.process(1)[0])
    assert after >= before
    assert after - before < 0.01

    envelope.gate_off()
    envelope.process(8)
    before_release_update = envelope.value
    envelope.set_parameters(release=0)
    assert envelope.finished
    assert envelope.value == 0
    assert before_release_update > 0


def test_adsr_random_chunking_matches_the_same_gate_schedule() -> None:
    def render(before_chunks: list[int], after_chunks: list[int]) -> np.ndarray:
        envelope = Adsr(48_000, attack=0.004, decay=0.03, sustain=0.35, release=0.05)
        envelope.gate_on(0.85)
        before = np.concatenate([envelope.process(count) for count in before_chunks])
        envelope.gate_off()
        after = np.concatenate([envelope.process(count) for count in after_chunks])
        return np.concatenate((before, after))

    reference = render([256, 44], [256, 256, 88])
    chunked = render(random_chunks(300, 18), random_chunks(600, 19))
    assert np.allclose(chunked, reference, rtol=0, atol=1e-7)


@pytest.mark.parametrize("waveform", ("sine", "triangle", "saw", "square"))
def test_lfo_periodic_shapes_have_known_phase_values(waveform: str) -> None:
    oscillator = Lfo(sample_rate=80, rate=20, waveform=waveform)
    output = oscillator.process(4)
    expected = {
        "sine": (0, 1, 0, -1),
        "triangle": (-1, 0, 1, 0),
        "saw": (-1, -0.5, 0, 0.5),
        "square": (1, 1, -1, -1),
    }[waveform]
    assert output == pytest.approx(expected, abs=1e-6)
    assert oscillator.phase == pytest.approx(0)


@pytest.mark.parametrize("waveform", ("sample_hold", "smooth_random"))
def test_seeded_random_lfos_repeat_and_are_chunking_equivalent(waveform: str) -> None:
    whole = Lfo(sample_rate=1_000, rate=20, waveform=waveform, seed=71)
    chunked = Lfo(sample_rate=1_000, rate=20, waveform=waveform, seed=71)
    other = Lfo(sample_rate=1_000, rate=20, waveform=waveform, seed=72)

    reference = process_lfo(whole, [BLOCK] * 16)
    actual = process_lfo(chunked, random_chunks(len(reference), 33))
    different = process_lfo(other, [BLOCK] * 16)

    assert np.array_equal(actual, reference)
    assert not np.array_equal(different, reference)
    assert np.max(np.abs(reference)) <= 1


def test_lfo_rate_validation_is_atomic_and_reset_restarts_seeded_state() -> None:
    oscillator = Lfo(sample_rate=1_000, rate=4, waveform="smooth_random", seed=11)
    first = oscillator.process(256)
    with pytest.raises(ValueError, match="rate"):
        oscillator.set_rate(21)
    assert oscillator.rate == 4
    oscillator.reset()
    assert np.array_equal(oscillator.process(256), first)
