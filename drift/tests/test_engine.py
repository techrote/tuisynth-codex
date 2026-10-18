from __future__ import annotations

import json
import math
import re
import time
from importlib.resources import files
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import welch

from trio_drift import (
    DriftInstrument,
    FormantBank,
    Grain,
    GrainPool,
    drift_registry,
    load_factory_presets,
    poisson_arrivals,
    vowel_formants,
    window_values,
)
from trio_kit.engine import Engine
from trio_kit.events import NoteOn
from trio_kit.params import ParamSnapshot


SR = 48_000


def test_windows_have_exact_endpoints_and_expected_shapes() -> None:
    ages = np.arange(0, 4_801)
    for name in ("hann", "tukey", "expodec", "rexpodec"):
        values = window_values(name, ages, 4_801, SR)
        assert values[0] == 0.0
        assert values[-1] == 0.0
        assert np.all(np.isfinite(values))
        assert np.min(values) >= 0.0
        assert np.max(values) <= 1.0 + 1e-12
    expodec = window_values("expodec", ages, 4_801, SR)
    assert int(np.argmax(expodec)) == pytest.approx(96, abs=1)
    rexpodec = window_values("rexpodec", ages, 4_801, SR)
    assert int(np.argmax(rexpodec)) == pytest.approx(4_704, abs=1)
    assert window_values("hann", np.arange(2), 2, SR).tolist() == [0.0, 0.0]


def test_seeded_poisson_has_expected_ten_second_arrival_count() -> None:
    def draw(seed: int) -> tuple[int, ...]:
        rng = np.random.default_rng(seed)
        return tuple(
            frame
            for block in range(math.ceil(10 * SR / 256))
            for frame in poisson_arrivals(rng, 50.0, min(256, 10 * SR - block * 256), SR)
        )

    first = draw(1234)
    second = draw(1234)
    assert first == second
    assert 450 <= len(first) <= 550


def test_grain_pool_caps_active_grains_and_counts_every_drop() -> None:
    pool = GrainPool(16)
    for index in range(20):
        accepted = pool.spawn(Grain(index, 1_000, 0.0, 1.0, 0.5, 0.2, "hann"))
        assert accepted is (index < 16)
    assert pool.active_count == 16
    assert pool.spawned == 16
    assert pool.dropped == 4
    shrinking = GrainPool(20)
    for index in range(20):
        shrinking.spawn(Grain(index, 1_000, 0.0, 1.0, 0.5, 0.2, "hann"))
    shrinking.set_capacity(16)
    assert shrinking.active_count == 16
    assert shrinking.dropped == 4
    pool.set_capacity(16)
    assert pool.active_count == 16


def test_single_grain_parameters_and_pan_are_applied() -> None:
    instrument = DriftInstrument(seed=9)
    instrument.prepare(SR, 256)
    values = instrument.registry.validate({
        "gr.size": 100,
        "gr.size_jit": 0,
        "gr.pos": 0.3,
        "gr.pos_scatter": 0,
        "gr.spread": 0.0,
        "gr.pitch_scatter": 0,
        "field.amount": 0,
    })
    snapshot = ParamSnapshot(values)
    voice = instrument.create_voice(np.random.default_rng(9))
    voice.pitch = 69.0
    voice.velocity = 0.8
    instrument._spawn_grain(voice, 0, 0.75, snapshot)
    grain = instrument._pool.grains[0]
    assert grain.length == 4_800
    assert grain.source_position == pytest.approx(0.3)
    assert grain.ratio == pytest.approx(2.0)
    assert grain.pan == pytest.approx(0.5)
    assert grain.amplitude == pytest.approx(0.6)

    sources = {"noise": np.ones(2_048), "tone": np.zeros(2_048), "breath": np.zeros(2_048)}
    pool = GrainPool(16)
    pool.spawn(Grain(0, 128, 0.0, 1.0, 0.75, 1.0, "tukey"))
    rendered = pool.render(
        64, block_offset=0, sample_rate=SR, sources=sources, old_sources=None,
        source_fade=None, tone=0, breath=0,
    )
    angle = 0.75 * math.pi / 2
    index = 20
    assert rendered[index, 1] / rendered[index, 0] == pytest.approx(math.tan(angle), rel=1e-6)
    assert rendered[index, 0] ** 2 + rendered[index, 1] ** 2 == pytest.approx(1.0)


def test_single_grain_overlap_is_identical_across_block_straddles() -> None:
    sources = {
        "noise": np.sin(np.arange(4_096) * 0.04),
        "tone": np.cos(np.arange(4_096) * 0.03),
        "breath": np.sin(np.arange(4_096) * 0.07),
    }
    grain = Grain(250, 180, 0.13, 1.73, 0.31, 0.4, "expodec")

    whole = GrainPool(16)
    whole.spawn(grain)
    expected = whole.render(
        512, block_offset=0, sample_rate=SR, sources=sources, old_sources=None,
        source_fade=None, tone=0.4, breath=0.2,
    )

    split = GrainPool(16)
    split.spawn(Grain(250, 180, 0.13, 1.73, 0.31, 0.4, "expodec"))
    pieces = [
        split.render(
            256, block_offset=0, sample_rate=SR, sources=sources, old_sources=None,
            source_fade=None, tone=0.4, breath=0.2,
        ),
        split.render(
            256, block_offset=256, sample_rate=SR, sources=sources, old_sources=None,
            source_fade=None, tone=0.4, breath=0.2,
        ),
    ]
    np.testing.assert_array_equal(np.concatenate(pieces), expected)


@pytest.mark.parametrize("vowel, expected", [(0, (800, 1150)), (2, (270, 2140))])
def test_formant_noise_peaks_follow_a_and_i_tables(vowel: int, expected: tuple[int, int]) -> None:
    rng = np.random.default_rng(77 + vowel)
    noise = rng.standard_normal(4 * SR).astype(np.float32)
    stereo = np.column_stack((noise, noise))
    bank = FormantBank(SR)
    bank.configure(float(vowel), 1.0, 1.0)
    filtered = bank.process(stereo, 1.0)[:, 0]
    frequencies, power = welch(filtered, fs=SR, nperseg=16_384)
    for center in expected:
        selection = np.flatnonzero((frequencies >= center * 0.85) & (frequencies <= center * 1.15))
        peak = frequencies[selection[int(np.argmax(power[selection]))]]
        assert peak == pytest.approx(center, rel=0.15)


def test_formant_morph_interpolates_table_and_shift_scales_frequency() -> None:
    np.testing.assert_array_equal(vowel_formants(0), np.asarray((
        (800, 80, 0), (1150, 90, -6), (2900, 120, -32), (3900, 130, -20), (4950, 140, -50),
    )))
    np.testing.assert_array_equal(vowel_formants(2), np.asarray((
        (270, 60, 0), (2140, 90, -12), (2950, 100, -26), (3900, 120, -26), (4950, 120, -44),
    )))
    np.testing.assert_allclose(vowel_formants(1.5), (vowel_formants(1) + vowel_formants(2)) / 2)
    bank = FormantBank(SR)
    bank.configure(2.0, 1.25, 1.0)
    assert bank._filters[0]._target[0] == pytest.approx(270 * 1.25)
    assert bank._filters[1]._target[0] == pytest.approx(2_140 * 1.25)
    assert bank._filters[1]._target[1] == pytest.approx(2_140 * 1.25 / 90)


def test_field_endpoints_density_and_held_gust_ramps() -> None:
    instrument = DriftInstrument(seed=12)
    values = instrument.registry.defaults()
    values["field.amount"] = 1
    values["fmt.vowel"] = 1.25
    snapshot = ParamSnapshot(instrument.registry.validate(values))
    left = dict(snapshot)
    left["field.x"] = 0
    right = dict(snapshot)
    right["field.x"] = 1
    assert instrument._effective_vowel(ParamSnapshot(left)) == 0
    assert instrument._effective_vowel(ParamSnapshot(right)) == 4
    assert instrument.field_density_scale(0) == pytest.approx(0.25)
    assert instrument.field_density_scale(1) == pytest.approx(4.0)

    instrument._wind_value = 0.0
    calm = instrument.density_for(snapshot, 0.0)
    half_gust = instrument.density_for(snapshot, 0.5)
    full_gust = instrument.density_for(snapshot, 1.0)
    assert half_gust > calm
    assert full_gust == pytest.approx(calm * 2.0)

    instrument.set_gust_held(True)
    ramp = instrument._gust_ramp_frames
    assert instrument._gust_at(0) == 0
    assert instrument._gust_at(ramp // 2) == pytest.approx(0.5, abs=1 / ramp)
    assert instrument._gust_at(ramp) == pytest.approx(1.0)
    instrument._absolute_frame = ramp
    instrument.set_gust_held(False)
    assert instrument._gust_at(ramp + ramp // 2) == pytest.approx(0.5, abs=1 / ramp)
    assert instrument._gust_at(2 * ramp) == pytest.approx(0.0)


def test_source_colour_rebuilds_only_at_block_boundaries() -> None:
    instrument = DriftInstrument(seed=123)
    instrument.prepare(SR, 256)
    defaults = ParamSnapshot(instrument.registry.defaults())
    first = instrument._sources["noise"].copy()
    assert instrument._source_regenerations == 1
    for source in instrument._sources.values():
        assert float(np.sqrt(np.mean(np.square(source, dtype=np.float64)))) == pytest.approx(0.25, rel=2e-4)
    values = dict(defaults)
    values["src.color"] = 0.5
    changed = ParamSnapshot(instrument.registry.validate(values))
    instrument.on_block_boundary(changed)
    assert instrument._source_regenerations == 2
    assert instrument._old_sources is not None
    assert not np.array_equal(instrument._sources["noise"], first)
    instrument.on_block_boundary(changed)
    assert instrument._source_regenerations == 2


def test_drift_parameter_registry_is_complete_and_used_by_engine_code() -> None:
    registry = drift_registry()
    assert len(registry) == 34
    assert DriftInstrument.legato_glide is True
    source_root = Path(__file__).parents[1] / "src" / "trio_drift"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
        if path.name != "params.py"
    )
    for key in registry.specs:
        assert re.search(rf"{re.escape(key)}", source), f"unused parameter: {key}"
    assert registry["field.x"].modulatable
    assert registry["field.y"].modulatable


def test_factory_presets_have_exact_issue_ids_and_valid_parameters() -> None:
    presets = load_factory_presets()
    assert {preset.id for preset in presets} == {
        "squall-choir", "desert-flute", "monsoon-breath", "howling-pass",
        "whisper-field", "vowel-sweep", "glass-wind", "deep-exhale",
    }
    for preset in presets:
        assert preset.synth == "drift"
        resource = files("trio_drift").joinpath("data", "presets", f"{preset.id}.json")
        document = json.loads(resource.read_text(encoding="utf-8"))
        assert "field.x" not in document["params"]
        assert "field.y" not in document["params"]
        assert preset.params["gr.density"] > 0
        assert 0 <= preset.params["master.level"] <= 1


@pytest.mark.parametrize("preset", load_factory_presets(), ids=lambda preset: preset.id)
def test_factory_preset_engine_render_is_finite_audible_and_limited(preset: object) -> None:
    engine = Engine(
        DriftInstrument(seed=501),
        sample_rate=SR,
        seed=501,
        initial_params=preset.params,
        max_voices=6,
    )
    try:
        assert engine.push(NoteOn(1, 60, 0.8, "test"))
        rendered = engine.render(SR)
        assert np.isfinite(rendered).all()
        assert np.max(np.abs(rendered)) <= 0.966
        assert float(np.max(np.abs(rendered))) > 1e-5
        assert engine.telemetry().instrument["active_grains"] <= int(preset.params["gr.max"])
    finally:
        engine.close()


def test_equal_seeds_and_event_streams_render_identically() -> None:
    def render() -> np.ndarray:
        engine = Engine(DriftInstrument(seed=99), seed=99, max_voices=6)
        engine.push(NoteOn(1, 64, 0.7, "test", frame=32))
        try:
            return engine.render(2_048)
        finally:
            engine.close()

    np.testing.assert_array_equal(render(), render())


def test_engine_runs_at_44100_hz_without_rebuilding_nonfinite_filters() -> None:
    engine = Engine(DriftInstrument(seed=31), sample_rate=44_100, seed=31, max_voices=6)
    engine.push(NoteOn(1, 60, 0.75, "test"))
    try:
        rendered = engine.render(16_384)
        assert np.isfinite(rendered).all()
        assert np.max(np.abs(rendered)) <= 0.966
        assert np.max(np.abs(rendered)) > 1e-5
    finally:
        engine.close()


def test_dense_six_stream_96_grain_case_is_bounded_and_finishes_promptly() -> None:
    instrument = DriftInstrument(seed=700)
    params = instrument.registry.validate({
        "gr.density": 200,
        "gr.size": 500,
        "gr.size_jit": 1,
        "gr.max": 96,
        "amp.a": 0.001,
        "wind.gust": 1,
        "wind.howl": 0.5,
    })
    engine = Engine(instrument, seed=700, initial_params=params, max_voices=6)
    for note_id in range(1, 7):
        engine.push(NoteOn(note_id, 48 + note_id * 3, 0.9, "test"))
    started = time.perf_counter()
    try:
        rendered = engine.render(SR)
        elapsed = time.perf_counter() - started
        telemetry = engine.telemetry().instrument
        assert np.isfinite(rendered).all()
        assert 80 <= telemetry["active_grains"] <= 96
        assert telemetry["dropped_grains"] > 0
        assert elapsed < 10.0
    finally:
        engine.close()
