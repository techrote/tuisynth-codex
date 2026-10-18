from __future__ import annotations

import pytest
import numpy as np

from trio_kit.modulation import LfoConfig, ModulationConfig, ModulationProcessor
from trio_kit.params import ParamRegistry, ParamSnapshot, ParamSpec
from trio_kit.seq import validate_extras


def _config_with_slots(*slots: dict[str, object]) -> ModulationConfig:
    data = ModulationConfig.defaults().to_dict()
    for index, slot in enumerate(slots):
        data["slots"][index] = slot
    return ModulationConfig.from_dict(data)


def test_modulation_defaults_are_empty_and_round_trip_all_seven_rack_units() -> None:
    config = ModulationConfig.defaults()
    assert len(config.lfos) == 3
    assert len(config.slots) == 8
    assert config.rack_order == ("tremolo", "ring-mod", "phaser", "tape", "chorus", "delay", "reverb")
    assert all(slot.source is None and slot.destination is None and slot.amount == 0 for slot in config.slots)
    assert all(config.rack_units[name]["bypass"] for name in ("tremolo", "ring-mod", "phaser", "tape"))
    assert not any(config.rack_units[name]["bypass"] for name in ("chorus", "delay", "reverb"))
    assert ModulationConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()


@pytest.mark.parametrize(
    "updates",
    [
        {"slots": [{}]},
        {"lfos": [{}]},
        {"rack": {"order": ["tremolo"]}},
        {"slots": [{"source": "unknown", "destination": "field.x", "amount": 1}] + [{}] * 7},
        {"rack": {"order": ["tremolo", "ring-mod", "phaser", "tape", "chorus", "delay", "delay"]}},
    ],
)
def test_modulation_rejects_malformed_presets(updates: dict[str, object]) -> None:
    data = ModulationConfig.defaults().to_dict()
    data.update(updates)
    with pytest.raises(ValueError):
        ModulationConfig.from_dict(data)


def test_empty_matrix_is_snapshot_identity_and_global_voice_routes_are_scoped() -> None:
    registry = ParamRegistry((
        ParamSpec("global.level", "Global", "", 0, 1, 0.5, modulatable=True),
        ParamSpec("voice.level", "Voice", "", 0, 1, 0.5, modulatable=True, modulation_scope="voice"),
        ParamSpec("locked.step", "Locked", "", 0, 3, 1, kind="discrete"),
    ))
    snapshot = ParamSnapshot(registry.defaults())
    processor = ModulationProcessor(registry, 48_000, seed=33)
    assert processor.apply_global(snapshot) is snapshot

    processor.set_config(_config_with_slots(
        {"source": "modwheel", "destination": "global.level", "amount": 1},
        {"source": "velocity", "destination": "voice.level", "amount": 1},
    ))
    processor.on_event("mod_wheel", (1.0,))
    processor.begin_block(0, 256, tempo=120)
    global_snapshot = processor.apply_global(snapshot)
    assert global_snapshot["global.level"] > 0.5
    assert global_snapshot["voice.level"] == 0.5
    voice_snapshot = processor.voice_snapshot(
        global_snapshot, note_id=1, pitch=72, velocity=1, age_frames=0,
        released_frames=None, frames=256,
    )
    assert voice_snapshot["voice.level"] > global_snapshot["voice.level"]
    assert voice_snapshot["locked.step"] == 1


def test_seeded_note_random_is_constant_per_note_and_repeatable() -> None:
    registry = ParamRegistry((ParamSpec("tone.level", "Tone", "", 0, 1, 0.5, modulatable=True),))
    first = ModulationProcessor(registry, 48_000, seed=901)
    second = ModulationProcessor(registry, 48_000, seed=901)
    value = first._random_for_note(12)
    assert first._random_for_note(12) == value
    assert second._random_for_note(12) == value
    assert first._random_for_note(13) != value


def test_tempo_sync_uses_note_divisions_at_120_bpm() -> None:
    from trio_kit.modulation import _lfo_rate

    assert _lfo_rate(LfoConfig(sync=True, division="1/4"), 120) == pytest.approx(2.0)
    assert _lfo_rate(LfoConfig(sync=True, division="1/8T"), 120) == pytest.approx(6.0)
    assert _lfo_rate(LfoConfig(sync=True, division="1/32"), 120) == pytest.approx(16.0)


def test_tempo_sync_tracks_fast_divisions_through_the_full_tempo_range() -> None:
    from trio_kit.modulation import _lfo_rate

    assert _lfo_rate(LfoConfig(sync=True, division="1/16T"), 240) == pytest.approx(24.0)
    assert _lfo_rate(LfoConfig(sync=True, division="1/32"), 240) == pytest.approx(32.0)
    processor = ModulationProcessor(ParamRegistry(), 48_000)
    config = ModulationConfig.from_dict({"lfos": [{"sync": True, "division": "1/32"}, {}, {}]})
    processor.set_config(config)
    processor.begin_block(0, 256, tempo=240)
    assert processor._global_lfos[0].rate == pytest.approx(32.0)
    assert processor._global_lfos[0].phase == pytest.approx(256 * 32 / 48_000)


def test_global_matrix_smoothing_clamps_at_parameter_bounds() -> None:
    registry = ParamRegistry((ParamSpec("gain.level", "Gain", "", 0, 1, 0.5, modulatable=True),))
    processor = ModulationProcessor(registry, 48_000, seed=1)
    processor.set_config(_config_with_slots({"source": "modwheel", "destination": "gain.level", "amount": 1}))
    base = ParamSnapshot({"gain.level": 0.5})
    processor.on_event("mod_wheel", (0.0,))
    processor.begin_block(0, 256)
    falling = processor.apply_global(base)["gain.level"]
    assert 0.0 < falling < 0.5
    processor.on_event("mod_wheel", (1.0,))
    processor.begin_block(256, 256)
    value = processor.apply_global(base)["gain.level"]
    assert falling < value < 1.0
    for frame in range(512, 256 * 82, 256):
        processor.begin_block(frame, 256)
        value = processor.apply_global(base)["gain.level"]
        assert 0.0 <= value <= 1.0
    assert value == pytest.approx(1.0)


def test_global_and_voice_routes_sum_before_one_parameter_clamp() -> None:
    registry = ParamRegistry((
        ParamSpec("voice.level", "Voice", "", 0, 1, 0.9, modulatable=True, modulation_scope="both"),
    ))
    processor = ModulationProcessor(registry, 48_000)
    processor.set_config(_config_with_slots(
        {"source": "modwheel", "destination": "voice.level", "amount": 1.0},
        {"source": "velocity", "destination": "voice.level", "amount": -1.0},
    ))
    processor.on_event("mod_wheel", (1.0,))
    base = ParamSnapshot({"voice.level": 0.9})
    for frame in range(0, 256 * 128, 256):
        processor.begin_block(frame, 256)
        global_snapshot = processor.apply_global(base)
    assert global_snapshot["voice.level"] == 1.0
    combined = processor.voice_snapshot(
        global_snapshot, note_id=99, pitch=60, velocity=1.0,
        age_frames=0, released_frames=None, frames=0,
    )
    assert combined["voice.level"] == pytest.approx(0.9)


def test_shared_preset_validation_requires_a_known_modulatable_destination() -> None:
    registry = ParamRegistry((
        ParamSpec("voice.cutoff", "Cutoff", "Hz", 20, 20_000, 1000, modulatable=True, modulation_scope="voice"),
        ParamSpec("play.mode", "Mode", "", 0, 1, 0, kind="choice", choices=("a", "b")),
    ))
    extras = {"modulation": ModulationConfig.defaults().to_dict()}
    extras["modulation"]["slots"][0] = {"source": "lfo1", "destination": "voice.cutoff", "amount": 0.5}
    assert validate_extras(extras, registry=registry)["modulation"]["slots"][0]["destination"] == "voice.cutoff"

    extras["modulation"]["slots"][0]["destination"] = "voice.typo"
    with pytest.raises(ValueError, match="unknown destination"):
        validate_extras(extras, registry=registry)
    extras["modulation"]["slots"][0]["destination"] = "play.mode"
    with pytest.raises(ValueError, match="not a modulatable continuous parameter"):
        validate_extras(extras, registry=registry)


def test_modulation_envelope_releases_from_its_held_level() -> None:
    registry = ParamRegistry((ParamSpec("voice.level", "Level", "", 0, 1, 0.5, modulatable=True, modulation_scope="voice"),))
    processor = ModulationProcessor(registry, 48_000)
    config = ModulationConfig.from_dict({"mod_env": {"attack": 0.1, "decay": 0.1, "sustain": 0.7, "release": 0.2}})
    processor.set_config(config)
    processor.begin_block(0, 0)

    assert processor._mod_env(0.5, None) == pytest.approx(0.7)
    assert processor._mod_env(0.5, 0.0) == pytest.approx(0.7)
    assert processor._mod_env(0.6, 0.1) == pytest.approx(0.35)
    assert processor._mod_env(0.7, 0.2) == 0.0


def test_multiple_routes_to_one_effect_parameter_are_summed() -> None:
    registry = ParamRegistry((ParamSpec("tone.level", "Level", "", 0, 1, 0.5, modulatable=True),))
    processor = ModulationProcessor(registry, 48_000)
    processor.set_config(_config_with_slots(
        {"source": "modwheel", "destination": "fx.ring.frequency", "amount": 0.5},
        {"source": "modwheel", "destination": "fx.ring.frequency", "amount": 0.5},
    ))
    processor.on_event("mod_wheel", (1.0,))
    processor.begin_block(0, 256)
    first = processor.fx_overrides["fx.ring.frequency"]
    assert 440.0 < first < 1440.0
    for frame in range(256, 256 * 50, 256):
        processor.begin_block(frame, 256)
    assert processor.fx_overrides["fx.ring.frequency"] == pytest.approx(1439.75, abs=0.01)


def test_voice_smoothing_tracks_control_changes_and_note_start_is_initialized() -> None:
    registry = ParamRegistry((
        ParamSpec("voice.level", "Level", "", 0, 1, 0.5, modulatable=True, modulation_scope="voice"),
    ))
    data = ModulationConfig.defaults().to_dict()
    data["slots"][0] = {"source": "keytrack", "destination": "voice.level", "amount": 1.0}
    config = ModulationConfig.from_dict(data)
    base = ParamSnapshot({"voice.level": 0.5})
    processor = ModulationProcessor(registry, 48_000)
    processor.set_config(config)
    processor.begin_block(0, 256)
    start = processor.voice_snapshot(
        base, note_id=1, pitch=60, velocity=1, age_frames=0,
        released_frames=None, frames=0,
    )
    assert start["voice.level"] == 0.5
    changed = processor.voice_snapshot(
        base, note_id=1, pitch=120, velocity=1, age_frames=128,
        released_frames=None, frames=128,
    )
    alpha = 1.0 - np.exp(-128 / (48_000 * 0.02))
    assert changed["voice.level"] == pytest.approx(0.5 + 0.5 * alpha)


def test_note_start_peeks_voice_lfo_without_advancing_its_phase() -> None:
    registry = ParamRegistry((
        ParamSpec("voice.level", "Level", "", 0, 1, 0.5, modulatable=True, modulation_scope="voice"),
    ))
    config = ModulationConfig.from_dict({
        "lfos": [{"mode": "voice", "phase": 0.25}, {}, {}],
        "slots": [{"source": "lfo1", "destination": "voice.level", "amount": 1.0}] + [{}] * 7,
    })
    processor = ModulationProcessor(registry, 48_000)
    processor.set_config(config)
    processor.begin_block(0, 256)
    start = processor.voice_snapshot(
        ParamSnapshot({"voice.level": 0.5}), note_id=5, pitch=60,
        velocity=1, age_frames=0, released_frames=None, frames=0,
    )
    oscillator = processor._voice_lfos[(5, 0)]
    assert start["voice.level"] == pytest.approx(1.0)
    assert oscillator.phase == pytest.approx(0.25)


def test_rack_only_edit_waits_for_a_block_and_preserves_unrelated_modulation_state() -> None:
    registry = ParamRegistry((ParamSpec("gain.level", "Gain", "", 0, 1, 0.5, modulatable=True),))
    processor = ModulationProcessor(registry, 48_000, seed=22)
    data = ModulationConfig.defaults().to_dict()
    data["lfos"][0] = {"rate": 1.0}
    data["slots"][0] = {"source": "modwheel", "destination": "gain.level", "amount": 0.8}
    initial = ModulationConfig.from_dict(data)
    processor.set_config(initial)
    processor.on_event("mod_wheel", (1.0,))
    base = ParamSnapshot({"gain.level": 0.5})
    processor.begin_block(0, 256)
    processor.apply_global(base)
    phase_before = processor._global_lfos[0].phase
    smoothing_before = processor._global_smoothed[(0, "gain.level")]

    changed_data = initial.to_dict()
    changed_data["rack"]["units"]["tremolo"]["mix"] = 0.4
    changed = ModulationConfig.from_dict(changed_data)
    processor.set_config(changed)

    assert processor.config == initial
    assert processor.requested_config == changed
    assert processor._global_lfos[0].phase == pytest.approx(phase_before)
    processor.begin_block(256, 256)
    processor.apply_global(base)
    assert processor.config == changed
    assert processor._global_lfos[0].phase == pytest.approx(phase_before + 256 / 48_000)
    alpha = 1.0 - np.exp(-256 / (48_000 * 0.02))
    expected_smoothing = smoothing_before + (0.4 - smoothing_before) * alpha
    assert processor._global_smoothed[(0, "gain.level")] == pytest.approx(expected_smoothing)


def test_global_route_amount_edit_preserves_smoothing_history() -> None:
    registry = ParamRegistry((ParamSpec("gain.level", "Gain", "", 0, 1, 0.5, modulatable=True),))
    processor = ModulationProcessor(registry, 48_000)
    data = ModulationConfig.defaults().to_dict()
    data["slots"][0] = {"source": "modwheel", "destination": "gain.level", "amount": 0.8}
    processor.set_config(ModulationConfig.from_dict(data))
    processor.on_event("mod_wheel", (1.0,))
    base = ParamSnapshot({"gain.level": 0.5})
    for frame in range(0, 256 * 80, 256):
        processor.begin_block(frame, 256)
        processor.apply_global(base)

    previous = processor._global_smoothed[(0, "gain.level")]
    data["slots"][0]["amount"] = 0.75
    processor.set_config(ModulationConfig.from_dict(data))
    processor.begin_block(256 * 80, 256)
    result = processor.apply_global(base)

    alpha = 1.0 - np.exp(-256 / (48_000 * 0.02))
    expected_delta = previous + (0.375 - previous) * alpha
    assert processor._global_smoothed[(0, "gain.level")] == pytest.approx(expected_delta)
    assert result["gain.level"] == pytest.approx(0.5 + expected_delta)


def test_voice_route_amount_edit_preserves_per_note_smoothing_history() -> None:
    registry = ParamRegistry((
        ParamSpec("voice.level", "Voice level", "", 0, 1, 0.5, modulatable=True, modulation_scope="voice"),
    ))
    processor = ModulationProcessor(registry, 48_000)
    data = ModulationConfig.defaults().to_dict()
    data["slots"][0] = {"source": "velocity", "destination": "voice.level", "amount": 1.0}
    processor.set_config(ModulationConfig.from_dict(data))
    base = ParamSnapshot({"voice.level": 0.5})
    for frame in range(0, 256 * 80, 256):
        processor.begin_block(frame, 256)
        processor.voice_snapshot(
            base, note_id=4, pitch=60, velocity=1.0, age_frames=frame,
            released_frames=None, frames=256,
        )

    previous = processor._voice_smoothed[(4, 0, "voice.level")]
    data["slots"][0]["amount"] = 0.7
    processor.set_config(ModulationConfig.from_dict(data))
    processor.begin_block(256 * 80, 256)
    result = processor.voice_snapshot(
        base, note_id=4, pitch=60, velocity=1.0, age_frames=256 * 80,
        released_frames=None, frames=256,
    )

    alpha = 1.0 - np.exp(-256 / (48_000 * 0.02))
    expected_delta = previous + (0.35 - previous) * alpha
    assert processor._voice_smoothed[(4, 0, "voice.level")] == pytest.approx(expected_delta)
    assert result["voice.level"] == pytest.approx(0.5 + expected_delta)


def test_effect_route_amount_edit_preserves_smoothing_history() -> None:
    processor = ModulationProcessor(ParamRegistry(), 48_000)
    data = ModulationConfig.defaults().to_dict()
    data["slots"][0] = {"source": "modwheel", "destination": "fx.tremolo.rate", "amount": 0.8}
    processor.set_config(ModulationConfig.from_dict(data))
    processor.on_event("mod_wheel", (1.0,))
    for frame in range(0, 256 * 80, 256):
        processor.begin_block(frame, 256)

    previous = processor._fx_smoothed["fx.tremolo.rate"]
    data["slots"][0]["amount"] = 0.75
    processor.set_config(ModulationConfig.from_dict(data))
    processor.begin_block(256 * 80, 256)

    alpha = 1.0 - np.exp(-256 / (48_000 * 0.02))
    expected_delta = previous + (7.49625 - previous) * alpha
    assert processor._fx_smoothed["fx.tremolo.rate"] == pytest.approx(expected_delta)
    assert processor.fx_overrides["fx.tremolo.rate"] == pytest.approx(5.0 + expected_delta)


def test_voice_sources_cannot_target_global_only_or_shared_effect_destinations() -> None:
    registry = ParamRegistry((
        ParamSpec("bus.level", "Bus", "", 0, 1, 0.5, modulatable=True),
        ParamSpec("note.level", "Note", "", 0, 1, 0.5, modulatable=True, modulation_scope="both"),
    ))
    data = ModulationConfig.defaults().to_dict()
    data["slots"][0] = {"source": "velocity", "destination": "bus.level", "amount": 0.5}
    with pytest.raises(ValueError, match="global-only destination"):
        from trio_kit.modulation import validate_modulation

        validate_modulation(data, registry)
    data["slots"][0] = {"source": "velocity", "destination": "note.level", "amount": 0.5}
    assert validate_modulation(data, registry)["slots"][0]["destination"] == "note.level"
    data["slots"][0] = {"source": "velocity", "destination": "fx.tremolo.depth", "amount": 0.5}
    with pytest.raises(ValueError, match="shared effect"):
        validate_modulation(data, registry)
