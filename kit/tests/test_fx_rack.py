from __future__ import annotations

import numpy as np

from trio_kit.dsp.fx_rack import FxRack
from trio_kit.modulation import ModulationConfig


def _rack_config(**unit_changes: dict[str, object]) -> ModulationConfig:
    data = ModulationConfig.defaults().to_dict()
    for name, changes in unit_changes.items():
        data["rack"]["units"][name].update(changes)
    # Existing instrument effects are not present in standalone rack tests.
    for name in ("chorus", "delay", "reverb"):
        data["rack"]["units"][name]["bypass"] = True
    return ModulationConfig.from_dict(data)


def _render_blocks(rack: FxRack, samples: np.ndarray, *, chunked: bool = False) -> np.ndarray:
    pieces: list[np.ndarray] = []
    cursor = 0
    chunk_sizes = (1, 73, 31, 127, 19, 5)
    chunk_index = 0
    while cursor < len(samples):
        count = min(256, len(samples) - cursor)
        rack.begin_block(count, 120)
        block = samples[cursor:cursor + count]
        if not chunked:
            pieces.append(rack.process(block))
        else:
            offset = 0
            while offset < count:
                subcount = min(chunk_sizes[chunk_index % len(chunk_sizes)], count - offset)
                pieces.append(rack.process(block[offset:offset + subcount]))
                offset += subcount
                chunk_index += 1
        cursor += count
    return np.concatenate(pieces, axis=0)


def test_all_bypassed_rack_is_bit_identical_and_returns_the_original_buffer() -> None:
    samples = np.random.default_rng(7).standard_normal((256, 2)).astype(np.float32)
    rack = FxRack(48_000, seed=5)
    rack.set_config(ModulationConfig.defaults())
    rack.begin_block(len(samples), 120)
    output = rack.process(samples)
    assert output is samples
    assert np.array_equal(output.view(np.uint32), samples.view(np.uint32))


def test_rack_only_edit_preserves_modulated_lfo_rate_and_phase() -> None:
    rack = FxRack(48_000, seed=12)
    initial = _rack_config(tremolo={"bypass": False, "rate": 2.0})
    rack.set_config(initial)
    rack.begin_block(256, 120, {"fx.tremolo.rate": 13.0})
    phase_before = rack._tremolo_lfo.phase
    assert rack._tremolo_lfo.rate == 13.0

    changed_data = initial.to_dict()
    changed_data["rack"]["units"]["tape"]["mix"] = 0.4
    rack.set_config(ModulationConfig.from_dict(changed_data))
    rack.begin_block(256, 120)

    assert rack._tremolo_lfo.rate == 13.0
    assert rack._tremolo_lfo.phase == (phase_before + 256 * 13.0 / 48_000) % 1.0


def test_autopan_preserves_constant_stereo_power() -> None:
    samples = np.ones((4096, 2), dtype=np.float32)
    rack = FxRack(48_000, seed=5)
    rack.set_config(_rack_config(tremolo={"bypass": False, "mode": "autopan", "depth": 1.0}))
    output = _render_blocks(rack, samples)
    power = np.sum(np.square(output.astype(np.float64)), axis=1)
    assert np.allclose(power, 2.0, rtol=1e-5, atol=1e-5)


def test_ring_modulator_creates_sum_and_difference_sidebands() -> None:
    sample_rate = 48_000
    frames = sample_rate
    time = np.arange(frames, dtype=np.float64) / sample_rate
    tone = np.sin(2 * np.pi * 1000 * time).astype(np.float32)
    samples = np.column_stack((tone, tone))
    rack = FxRack(sample_rate, seed=5)
    rack.set_config(_rack_config(**{"ring-mod": {"bypass": False, "frequency": 440.0, "depth": 1.0}}))
    output = _render_blocks(rack, samples)[:, 0]
    spectrum = np.abs(np.fft.rfft(output.astype(np.float64)))
    peak_bins = set(np.argpartition(spectrum, -12)[-12:])
    assert any(abs(index - 560) <= 1 for index in peak_bins)
    assert any(abs(index - 1440) <= 1 for index in peak_bins)


def test_phaser_notch_moves_with_its_lfo() -> None:
    sample_rate = 48_000
    config = _rack_config(phaser={"bypass": False, "rate": 4.0, "depth": 1.0, "stages": 8})
    tone = np.sin(2 * np.pi * 3000 * np.arange(256) / sample_rate).astype(np.float32)
    samples = np.column_stack((tone, tone))
    rack = FxRack(sample_rate, seed=4)
    rack.set_config(config)
    rack.begin_block(len(samples), 120)
    early = rack.process(samples)
    # Advance the phase by one quarter cycle with silence, then measure the same tone.
    advance = round(sample_rate / (4.0 * 4.0))
    _render_blocks(rack, np.zeros((advance, 2), dtype=np.float32))
    rack.begin_block(len(samples), 120)
    late = rack.process(samples)
    early_rms = float(np.sqrt(np.mean(np.square(early[32:].astype(np.float64)))))
    late_rms = float(np.sqrt(np.mean(np.square(late[32:].astype(np.float64)))))
    assert abs(early_rms - late_rms) > 1e-3


def test_zero_phaser_depth_keeps_a_static_allpass_setting() -> None:
    tone = np.sin(2 * np.pi * 1_400 * np.arange(2_048) / 48_000).astype(np.float32)
    samples = np.column_stack((tone, tone))
    outputs = []
    for rate in (0.01, 20.0):
        rack = FxRack(48_000, seed=6)
        rack.set_config(_rack_config(phaser={"bypass": False, "rate": rate, "depth": 0.0, "stages": 8}))
        rack.begin_block(256, 120)
        first = rack.process(samples[:256])
        cursor = 256
        pieces = [first]
        while cursor < len(samples):
            count = min(256, len(samples) - cursor)
            rack.begin_block(count, 120)
            pieces.append(rack.process(samples[cursor:cursor + count]))
            cursor += count
        outputs.append(np.concatenate(pieces))
    np.testing.assert_array_equal(outputs[0], outputs[1])


def test_tape_wow_flutter_change_the_delayed_signal() -> None:
    sample_rate = 48_000
    frames = sample_rate // 2
    time = np.arange(frames, dtype=np.float64) / sample_rate
    tone = np.sin(2 * np.pi * 700 * time).astype(np.float32)
    samples = np.column_stack((tone, tone))
    baseline = FxRack(sample_rate, seed=7)
    baseline.set_config(_rack_config(tape={"bypass": False, "wow": 0.0, "flutter": 0.0}))
    dry_depth = _render_blocks(baseline, samples)
    modulated = FxRack(sample_rate, seed=7)
    modulated.set_config(_rack_config(tape={"bypass": False, "wow": 0.01, "flutter": 0.001}))
    wet_depth = _render_blocks(modulated, samples)
    assert np.max(np.abs(dry_depth - wet_depth)) > 0.01


def test_rack_random_chunks_match_one_vector_and_remain_finite_for_twenty_seconds() -> None:
    sample_rate = 48_000
    rng = np.random.default_rng(120)
    frames = sample_rate * 20
    samples = (0.2 * rng.standard_normal((frames, 2))).astype(np.float32)
    config = _rack_config(
        tremolo={"bypass": False, "mode": "autopan", "depth": 1.0, "rate": 20.0},
        **{"ring-mod": {"bypass": False, "frequency": 2000.0, "depth": 1.0}},
        phaser={"bypass": False, "stages": 8, "rate": 20.0, "depth": 1.0, "feedback": 0.8},
        tape={"bypass": False, "wow": 0.02, "flutter": 0.002, "saturation": 1.0},
    )
    whole = FxRack(sample_rate, seed=19)
    whole.set_config(config)
    expected = _render_blocks(whole, samples)

    chunked = FxRack(sample_rate, seed=19)
    chunked.set_config(config)
    actual = _render_blocks(chunked, samples, chunked=True)
    assert np.isfinite(expected).all()
    assert np.isfinite(actual).all()
    assert np.allclose(actual, expected, rtol=1e-5, atol=1e-5)
