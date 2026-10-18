from __future__ import annotations

import math

import numpy as np
import pytest

from trio_kit import Engine, InstrumentEvent, NoteOn, NoteOff, ParamSet
from trio_kit.constants import OUTPUT_CEILING
from trio_kit.params import ParamSnapshot
from trio_loom.body import BODY_MODES, BodyResonator
from trio_loom.instrument import LoomInstrument
from trio_loom.params import loom_registry
from trio_loom.presets import load_factory_presets
from trio_loom.strum import DEFAULT_TUNING, StrumModel
from trio_loom.voice import LoomVoice
from trio_loom.waveguide import midi_frequency


def _params(**changes: object) -> ParamSnapshot:
    registry = loom_registry()
    return ParamSnapshot(registry.validate(changes))


def _sympathetic_energy(pitch: int) -> float:
    sample_rate = 48_000
    params = _params(
        **{
            "sym.mix": 1.0,
            "sym.couple": 1.0,
            "sym.decay": 12.0,
            "body.type": 0,
            "body.mix": 0.0,
            "fx.reverb.mix": 0.0,
            "master.level": 1.0,
            "master.drive": 0.0,
        }
    )
    instrument = LoomInstrument(seed=6)
    instrument.prepare(sample_rate, 256)
    instrument.on_block_boundary(params)
    frequency = midi_frequency(pitch)
    time_axis = np.arange(2 * sample_rate, dtype=np.float64) / sample_rate
    signal = (0.01 * np.sin(2.0 * math.pi * frequency * time_axis)).astype(np.float32)
    residuals: list[np.ndarray] = []
    for start in range(0, len(signal), 256):
        source = np.column_stack((signal[start : start + 256], signal[start : start + 256]))
        output = instrument.process_bus(source, params)
        residuals.append(output[:, 0] - source[:, 0])
    residual = np.concatenate(residuals)[sample_rate // 2 :]
    return float(np.mean(np.square(residual, dtype=np.float64)))


def test_sympathetic_bank_reinforces_in_tune_strings_and_has_no_return_at_zero_mix() -> None:
    matched = _sympathetic_energy(50)  # First Dorian resonator at the default root.
    absent = _sympathetic_energy(51)
    assert matched >= absent * (10.0 ** (6.0 / 10.0))

    source = np.random.default_rng(3).normal(0, 0.01, (256, 2)).astype(np.float32)
    outputs = []
    for coupling in (0.0, 1.0):
        params = _params(
            **{
                "sym.mix": 0.0,
                "sym.couple": coupling,
                "body.type": 0,
                "body.mix": 0.0,
                "fx.reverb.mix": 0.0,
                "master.level": 1.0,
                "master.drive": 0.0,
            }
        )
        instrument = LoomInstrument(seed=4)
        instrument.prepare(48_000, 256)
        instrument.on_block_boundary(params)
        outputs.append(instrument.process_bus(source, params))
    assert np.array_equal(outputs[0], outputs[1])
    assert np.array_equal(outputs[0], source)

    no_body_params = _params(
        **{
            "sym.mix": 0,
            "sym.couple": 1,
            "body.type": 0,
            "body.mix": 0.75,
            "fx.reverb.mix": 0,
            "master.level": 1,
            "master.drive": 0,
        }
    )
    no_body = LoomInstrument()
    no_body.prepare(48_000, 256)
    no_body.on_block_boundary(no_body_params)
    assert np.array_equal(no_body.process_bus(source, no_body_params), source)


def test_sympathetic_retuning_waits_until_the_old_string_is_quiet() -> None:
    instrument = LoomInstrument()
    instrument.prepare(48_000, 256)
    original = instrument._sympathetic[0].pitch
    instrument._sympathetic_levels[0] = 0.2
    changed = _params(**{"sym.root": 5})
    instrument.on_block_boundary(changed)
    assert instrument._sympathetic[0].pitch == original
    assert instrument._pending_retune[0] == 53.0
    instrument._sympathetic_levels[0] = 0.0
    instrument.on_block_boundary(changed)
    assert instrument._sympathetic[0].pitch == 53.0
    assert instrument._pending_retune[0] is None


def test_chord_tuning_folds_extreme_held_pitches_into_string_range() -> None:
    instrument = LoomInstrument()
    instrument._held_pitches = (127.0,)
    params = _params(**{"sym.tuning": 2})

    instrument.on_block_boundary(params)

    pitches = instrument.telemetry()["sympathetic_pitches"]
    assert len(pitches) == 12
    assert all(24.0 <= pitch <= 100.0 for pitch in pitches)
    assert all(pitch % 12 == 7 for pitch in pitches)


def test_body_modes_are_bounded_and_scale_their_modal_centers() -> None:
    body = BodyResonator(48_000)
    body.configure("violin", 1.0)
    assert 6 <= len(body.filters) <= 10
    first_center = body.filters[0].cutoff
    impulse = np.zeros((8_192, 2), dtype=np.float32)
    impulse[0] = 1.0
    output = np.concatenate([body.process(impulse[start : start + 256]) for start in range(0, len(impulse), 256)])
    assert np.isfinite(output).all()
    assert np.any(output)
    spectrum = np.abs(np.fft.rfft(output[:, 0] * np.hanning(len(output))))
    frequencies = np.fft.rfftfreq(len(output), 1.0 / 48_000)
    mode_frequency = BODY_MODES["violin"][2][0]
    local = np.abs(frequencies - mode_frequency) <= 30
    assert spectrum[local].max() > spectrum[np.abs(frequencies - 350) < 10].max()
    body.configure("violin", 2.0)
    assert body.filters[0].cutoff == pytest.approx(first_center / 2.0)
    assert body.filters[0].current_cutoff == pytest.approx(first_center)
    body.configure("none", 1.0)
    assert BODY_MODES["none"] == ()
    assert not body.filters


def test_strum_default_chord_direction_and_crossing_velocity() -> None:
    model = StrumModel(8)
    assert model.pitches() == DEFAULT_TUNING
    chord = model.pitches("chord", (50, 53, 57))
    assert chord[:4] == (50, 53, 57, 62)
    assert model.crossing_velocity(0) == 0.25
    assert model.crossing_velocity(20) == 0.75
    assert model.crossing_velocity(100) == 1.0
    assert model.ordered_crossings(6, 1) == (0, 1, 2, 3, 4, 5)
    assert model.ordered_crossings(6, -1) == (5, 4, 3, 2, 1, 0)
    model.set_string_count(12)
    pitches = model.pitches()
    assert len(pitches) == 12 and all(a < b for a, b in zip(pitches, pitches[1:]))


def test_instrument_event_strum_is_sample_aligned_spread_and_muteable() -> None:
    params = loom_registry().validate(
        {
            "body.type": 0,
            "body.mix": 0.0,
            "fx.reverb.mix": 0.0,
            "master.level": 1.0,
            "master.drive": 0.0,
        }
    )
    instrument = LoomInstrument(seed=18)
    engine = Engine(instrument, max_voices=8, initial_params=params)
    engine.push(InstrumentEvent("strum", (1, 40, 60, 64, 67), frame=64))
    rendered = engine.render(256)
    assert np.array_equal(rendered[:64], np.zeros((64, 2), dtype=np.float32))
    assert np.any(np.abs(rendered[64:]) > 0)
    assert engine.telemetry().instrument["pending_strums"] > 0
    assert engine.telemetry().instrument["event_voices"] > 0

    engine.push(InstrumentEvent("mute", (0,), frame=0))
    engine.render(256)
    assert engine.telemetry().last_error is None


def test_empty_strum_held_pitch_snapshot_clears_previous_chord() -> None:
    instrument = LoomInstrument()
    params = _params(**{"play.mode": 1, "sym.tuning": 2, "strum.spread": 0})
    instrument.on_block_boundary(params)
    default_tuning = instrument._desired_sympathetic_pitches(params)

    instrument.on_event("strum", (1, 40, 50, 53, 57))
    assert instrument._held_pitches == (50.0, 53.0, 57.0)
    assert instrument._desired_sympathetic_pitches(params) != default_tuning

    instrument.on_event("strum", (1, 40))
    assert instrument._held_pitches == ()
    assert instrument._desired_sympathetic_pitches(params) == default_tuning


def test_mute_instrument_event_chokes_matching_keyboard_string() -> None:
    params = loom_registry().validate(
        {
            "body.type": 0,
            "body.mix": 0,
            "sym.mix": 0,
            "fx.reverb.mix": 0,
            "master.level": 1,
            "master.drive": 0,
        }
    )
    engine = Engine(LoomInstrument(seed=21), max_voices=8, initial_params=params)
    engine.push(NoteOn(1, 40, 0.8, "test"))
    engine.push(NoteOn(2, 41, 0.8, "test"))
    engine.render(256)
    voices = {slot.note_id: slot.voice for slot in engine.voice_manager._slots if slot.note_id is not None}
    matching = voices[1]
    other = voices[2]
    assert matching is not None and other is not None
    assert not matching.finished and not other.finished

    engine.push(InstrumentEvent("mute", (0,)))
    engine.render(256)

    assert matching.finished
    assert matching._choke_total == round(0.005 * engine.sample_rate)
    assert matching._choke_position >= matching._choke_total
    assert not other.finished
    assert engine.telemetry().last_error is None


def test_instrument_events_start_pluck_and_bow_strings_and_mute_them() -> None:
    params = loom_registry().validate(
        {
            "body.type": 0,
            "body.mix": 0,
            "fx.reverb.mix": 0,
            "master.level": 1,
            "master.drive": 0,
        }
    )
    instrument = LoomInstrument(seed=12)
    engine = Engine(instrument, max_voices=8, initial_params=params)
    engine.push(InstrumentEvent("pluck", (52, 0.8, 2)))
    output = engine.render(256)
    assert np.isfinite(output).all() and np.any(output)
    assert engine.telemetry().instrument["event_voices"] == 1

    engine.push(InstrumentEvent("mute", (2,)))
    engine.push(InstrumentEvent("bow", (55, 0.6, 3)))
    output = engine.render(256)
    assert np.isfinite(output).all() and np.any(output)
    assert engine.telemetry().instrument["event_voices"] >= 1
    active_pitches = engine.telemetry().instrument["string_pitches"]
    assert 52.0 not in active_pitches
    assert 55.0 in active_pitches
    assert engine.telemetry().last_error is None


def test_event_voices_use_the_shared_engine_seed() -> None:
    params = loom_registry().validate(
        {
            "body.type": 0,
            "body.mix": 0,
            "sym.mix": 0,
            "fx.reverb.mix": 0,
            "master.level": 1,
            "master.drive": 0,
        }
    )

    def render(seed: int) -> np.ndarray:
        engine = Engine(LoomInstrument(), max_voices=8, initial_params=params, seed=seed)
        engine.push(InstrumentEvent("pluck", (60, 0.8, 0)))
        return engine.render(256)

    assert np.array_equal(render(19), render(19))
    assert not np.array_equal(render(19), render(20))


def test_released_string_finishes_after_it_stays_below_minus_ninety_dbfs() -> None:
    registry = loom_registry()
    params = ParamSnapshot(registry.validate({"str.decay": 0.2, "str.release": 0.05}))
    voice = LoomVoice(48_000, np.random.default_rng(14))
    voice.start(60, 0.8, params)
    voice.render(256, params)
    voice.release()
    rendered_after_release = 0
    while rendered_after_release < 48_000 and not voice.finished:
        voice.render(256, params)
        rendered_after_release += 256
    assert voice.finished
    assert rendered_after_release >= 4_800
    assert rendered_after_release < 48_000


def test_voice_limit_tracks_pluck_and_bow_mode_with_fade_tails() -> None:
    registry = loom_registry()
    instrument = LoomInstrument(seed=9)
    engine = Engine(instrument, max_voices=8, initial_params=registry.defaults())
    for note_id, pitch in enumerate((45, 48, 52, 55, 57, 60, 64), 1):
        engine.push(NoteOn(note_id, pitch, 0.5, "test"))
    engine.render(256)
    assert engine.telemetry().max_voices == 8
    assert engine.telemetry().active_voices == 7
    voices = [slot.voice for slot in engine.voice_manager._slots if slot.voice is not None]

    engine.push(ParamSet("exc.mode", 1))
    engine.render(256)
    assert engine.telemetry().max_voices == 4
    assert engine.telemetry().active_voices == 4
    assert sum(bool(voice._released) for voice in voices) >= 3


def test_surface_event_voices_share_the_main_note_polyphony_budget() -> None:
    params = loom_registry().validate(
        {
            "body.type": 0,
            "body.mix": 0,
            "fx.reverb.mix": 0,
            "master.level": 1,
            "master.drive": 0,
            "strum.spread": 0,
        }
    )
    instrument = LoomInstrument(seed=27)
    engine = Engine(instrument, max_voices=8, initial_params=params)
    for note_id in range(1, 8):
        engine.push(NoteOn(note_id, 45 + note_id, 0.5, "test"))
    engine.push(InstrumentEvent("strum", (1, 80)))
    engine.render(256)

    assert engine.telemetry().active_voices == 7
    assert engine.telemetry().max_voices == 8
    assert engine.telemetry().instrument["event_voices"] == 1
    assert len(instrument._event_voices) <= 24

    smaller_params = dict(params)
    small_instrument = LoomInstrument(seed=28)
    small_engine = Engine(small_instrument, max_voices=4, initial_params=smaller_params)
    for note_id in range(1, 4):
        small_engine.push(NoteOn(note_id, 48 + note_id, 0.5, "test"))
    small_engine.push(InstrumentEvent("strum", (1, 80)))
    small_engine.render(256)
    assert small_engine.telemetry().max_voices == 4
    assert small_engine.telemetry().active_voices == 3
    assert small_engine.telemetry().instrument["event_voices"] == 1
    assert small_engine.telemetry().last_error is None


def test_sustained_surface_bow_telemetry_marks_and_releases_string() -> None:
    instrument = LoomInstrument(seed=39)
    engine = Engine(instrument, max_voices=8, initial_params=loom_registry().defaults())
    engine.push(InstrumentEvent("bow_on", (55, 0.7, 4)))
    engine.render(256)
    assert engine.telemetry().instrument["bow_strings"] == (4.0,)

    engine.push(InstrumentEvent("bow_off", (4,)))
    engine.render(256)
    assert engine.telemetry().instrument["bow_strings"] == ()


def test_sustained_bow_requires_a_valid_string_index() -> None:
    instrument = LoomInstrument(seed=40)
    engine = Engine(instrument, max_voices=8, initial_params=loom_registry().defaults())
    engine.push(InstrumentEvent("bow_on", (55, 0.7)))
    engine.push(InstrumentEvent("bow_on", (55, 0.7, 8)))
    engine.render(256)
    telemetry = engine.telemetry().instrument
    assert telemetry["bow_strings"] == ()
    assert telemetry["event_voices"] == 0


def test_all_eight_factory_presets_render_finite_non_silent_stereo_audio() -> None:
    presets = load_factory_presets()
    assert {preset.id for preset in presets} >= {
        "rosewood-harp",
        "autoharp-dorian",
        "sitar-dawn",
        "cello-drone",
        "glass-koto",
        "hardingfele",
        "steel-shimmer",
        "muted-guitar",
    }
    for preset in presets:
        instrument = LoomInstrument(seed=17)
        engine = Engine(instrument, max_voices=8, initial_params=preset.params, seed=23)
        engine.push(NoteOn(1, 55, 0.7, "test"))
        audio = engine.render(4_096)
        assert audio.shape == (4_096, 2)
        assert np.isfinite(audio).all()
        assert np.max(np.abs(audio)) <= OUTPUT_CEILING
        assert float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))) > 1e-6
        assert engine.telemetry().max_voices == (4 if preset.params["exc.mode"] == 1 else 8)


def test_maximum_decay_brightness_and_sympathy_are_bounded_for_twenty_seconds() -> None:
    params = loom_registry().validate(
        {
            "str.decay": 30,
            "str.bright": 1,
            "sym.couple": 1,
            "sym.mix": 1,
            "sym.decay": 40,
            "body.type": 5,
            "body.mix": 0.6,
            "fx.reverb.mix": 0.3,
        }
    )
    instrument = LoomInstrument(seed=31)
    engine = Engine(instrument, max_voices=8, initial_params=params, seed=11)
    engine.push(NoteOn(1, 48, 0.75, "test"))
    audio = engine.render(20 * 48_000)

    assert np.isfinite(audio).all()
    assert np.max(np.abs(audio)) <= OUTPUT_CEILING
    assert instrument.telemetry()["pre_master_peak"] < 1.0
    assert engine.telemetry().limited_blocks == 0
    assert engine.telemetry().render_load < 1.0
