from __future__ import annotations

import numpy as np
import pytest

from trio_kit.engine import Engine, EngineTelemetry, MasterBus, OfflineEngine
from trio_kit.events import EventQueue, InstrumentEvent, NoteOff, NoteOn, ParamSet, PresetApply, RetargetNote
from trio_kit.modulation import ModulationConfig, ModulationProcessor
from trio_kit.params import ParamRegistry, ParamSnapshot, ParamSpec
from trio_kit.engine.voices import VoiceManager

from engine_fakes import FakeInstrument


def gain_registry() -> ParamRegistry:
    return ParamRegistry((ParamSpec("amp.gain", "Gain", "", 0, 2, 1),))


def test_arbitrary_positive_frame_sizes_are_finite_stereo_and_chunk_equivalent() -> None:
    sizes = (1, 255, 256, 257, 1_024, 1_537)
    engine = Engine(FakeInstrument(), seed=74)
    outputs = [engine.render(size) for size in sizes]

    assert all(output.shape == (size, 2) for output, size in zip(outputs, sizes))
    assert all(output.dtype == np.float32 and np.isfinite(output).all() for output in outputs)

    whole = Engine(FakeInstrument(), seed=74).render(sum(sizes))
    assert np.array_equal(np.concatenate(outputs), whole)


def test_random_chunking_is_bit_identical_to_rendering_whole_blocks() -> None:
    events = (
        NoteOn(1, 60, 0.7, "keyboard", frame=10),
        NoteOn(2, 60, 0.4, "keyboard", frame=80),
        NoteOff(1, frame=150),
        NoteOff(2, frame=220),
    )
    whole_engine = Engine(FakeInstrument(random_level=True), seed=902)
    chunked_engine = Engine(FakeInstrument(random_level=True), seed=902)
    for event in events:
        whole_engine.push(event)
        chunked_engine.push(event)
    whole = whole_engine.render(4_096)

    rng = np.random.default_rng(7)
    pieces: list[np.ndarray] = []
    remaining = len(whole)
    while remaining:
        count = min(remaining, int(rng.integers(1, 513)))
        pieces.append(chunked_engine.render(count))
        remaining -= count

    assert np.array_equal(np.concatenate(pieces), whole)


def test_equal_seeds_reproduce_random_voices_and_different_seeds_change_them() -> None:
    def render(seed: int) -> np.ndarray:
        engine = Engine(FakeInstrument(random_level=True), seed=seed)
        engine.push(NoteOn(1, 60, 1, "test"))
        return engine.render(256)

    first = render(4)
    assert np.array_equal(first, render(4))
    assert not np.array_equal(first, render(5))


def test_instrument_event_is_delivered_at_its_sample_frame() -> None:
    instrument = FakeInstrument()
    engine = Engine(instrument)
    engine.push(InstrumentEvent("pluck", (60, 0.8), frame=64))

    engine.render(256)

    assert instrument.events == [("pluck", (60, 0.8), 64)]
    assert instrument.bus_frames == 256


def test_parameter_changes_are_published_only_at_internal_block_boundaries() -> None:
    instrument = FakeInstrument()
    engine = Engine(instrument, registry=gain_registry())
    engine.push(NoteOn(1, 60, 1, "test"))
    engine.render(1)
    assert instrument.render_params[-1][0] == 0

    engine.push(ParamSet("amp.gain", 0.25))
    engine.render(255)
    assert engine.param_snapshot.version == 0
    assert instrument.render_params[-1][0] == 0

    engine.render(1)
    assert engine.param_snapshot.version == 1
    assert instrument.render_params[-1] == (1, 0.25)


def test_preset_extras_and_legato_retarget_apply_at_the_next_block_boundary() -> None:
    instrument = FakeInstrument()
    engine = Engine(instrument, registry=gain_registry())
    engine.push(NoteOn(1, 60, 0.8, "onscreen"))
    engine.render(1)
    voice = instrument.created[0]

    engine.push(PresetApply({"amp.gain": 0.25}, {"character": ["soft"]}))
    engine.render(255)
    assert engine.param_snapshot.version == 0
    assert instrument.extras == {}
    engine.render(1)
    assert engine.param_snapshot["amp.gain"] == 0.25
    assert instrument.extras == {"character": ["soft"]}

    engine.push(RetargetNote(1, 64))
    engine.render(255)
    assert voice.pitch == 60
    engine.render(1)
    assert voice.pitch == 64


def test_optional_instrument_block_boundary_hook_runs_after_snapshot_and_extras_before_voices() -> None:
    class BoundaryInstrument(FakeInstrument):
        def __init__(self) -> None:
            super().__init__()
            self.boundaries: list[tuple[int, int, dict[str, object]]] = []

        def on_block_boundary(self, params) -> None:
            self.boundaries.append((self.bus_frames, params.version, dict(self.extras)))

    instrument = BoundaryInstrument()
    engine = Engine(instrument, registry=gain_registry())
    engine.push(PresetApply({"amp.gain": 0.25}, {"character": ["soft"]}))
    engine.push(NoteOn(1, 60, 0.8, "test"))

    engine.render(1)
    engine.render(255)
    assert instrument.boundaries == [(0, 1, {"character": ["soft"]})]
    assert len(instrument.created) == 1

    engine.render(1)
    assert len(instrument.boundaries) == 2


def test_engine_modulation_and_rack_edits_commit_together_without_resetting_lfo_phase() -> None:
    engine = Engine(FakeInstrument(), registry=gain_registry(), seed=23)
    config_data = ModulationConfig.defaults().to_dict()
    config_data["lfos"][0] = {"rate": 1.0}
    config = ModulationConfig.from_dict(config_data)
    try:
        engine.set_extras({"modulation": config.to_dict()})
        engine.render(256)
        initial_phase = engine.modulation._global_lfos[0].phase
        assert engine.modulation.config == config

        changed_data = config.to_dict()
        changed_data["rack"]["units"]["tremolo"]["mix"] = 0.25
        changed = ModulationConfig.from_dict(changed_data)
        engine.set_extras({"modulation": changed.to_dict()})
        assert engine.modulation.config == config
        assert engine.modulation.requested_config == changed
        assert engine.modulation._global_lfos[0].phase == pytest.approx(initial_phase)

        engine.render(256)
        assert engine.modulation.config == changed
        assert engine.fx_rack.config == changed
        assert engine.modulation._global_lfos[0].phase == pytest.approx(initial_phase + 256 / engine.sample_rate)
    finally:
        engine.close()


def test_optional_dynamic_voice_limit_is_applied_per_block_and_reported() -> None:
    class DynamicLimitInstrument(FakeInstrument):
        def __init__(self) -> None:
            super().__init__()
            self.limit = 2

        def voice_limit(self, params) -> int:
            del params
            return self.limit

    instrument = DynamicLimitInstrument()
    engine = Engine(instrument, max_voices=4)
    engine.push(NoteOn(1, 48, 0.7, "test"))
    engine.push(NoteOn(2, 52, 0.7, "test"))
    engine.push(NoteOn(3, 55, 0.7, "test"))
    engine.render(256)
    assert engine.telemetry().active_voices == 2
    assert engine.telemetry().max_voices == 2

    instrument.limit = 1
    engine.render(256)
    assert engine.telemetry().active_voices == 1
    assert engine.telemetry().max_voices == 1
    assert sum(voice.release_calls for voice in instrument.created) >= 2

    instrument.limit = 4
    engine.render(256)
    assert engine.telemetry().max_voices == 4


def test_invalid_queued_parameter_is_reported_and_does_not_break_audio() -> None:
    engine = Engine(FakeInstrument(), registry=gain_registry())
    engine.push(ParamSet("unknown.key", 1))

    output = engine.render(256)

    assert output.shape == (256, 2)
    assert np.isfinite(output).all()
    assert "unknown parameter" in (engine.telemetry().last_error or "")


def test_nonfinite_voice_output_silences_the_block_and_resets_voice_instrument_and_master() -> None:
    instrument = FakeInstrument(bad_voice_indices={0})
    engine = Engine(instrument)
    engine.push(NoteOn(1, 60, 1, "test"))

    output = engine.render(256)

    assert np.array_equal(output, np.zeros((256, 2), dtype=np.float32))
    telemetry = engine.telemetry()
    assert telemetry.nonfinite_resets == 1
    assert telemetry.active_voices == 0
    assert instrument.reset_calls == 1


def test_engine_telemetry_is_small_immutable_and_instrument_close_is_idempotent() -> None:
    instrument = FakeInstrument()
    engine = Engine(instrument)
    telemetry = engine.telemetry()
    assert telemetry.instrument["created"] == 0
    with pytest.raises(TypeError):
        telemetry.instrument["created"] = 1  # type: ignore[index]

    oversized = EngineTelemetry(
        sample_rate=48_000,
        block=256,
        active_voices=0,
        max_voices=1,
        event_queue_depth=0,
        dropped_events=0,
        overflow_count=0,
        overflow_panics=0,
        nonfinite_resets=0,
        limited_blocks=0,
        limiter_gain=1,
        render_load=0,
        callback_seconds=0,
        callback_errors=0,
        backend="offline",
        last_error=None,
        instrument={
            "grains": tuple(index / 95 for index in range(96)),
            "oversized_vector": tuple(range(97)),
            "invalid_vector": (1.0, float("nan")),
            "huge_vector": (1.0, 10**10000),
            **{f"key{index}": index for index in range(50)},
        },
    )
    assert len(oversized.instrument) == 16
    assert oversized.instrument["grains"] == tuple(index / 95 for index in range(96))
    assert "oversized_vector" not in oversized.instrument
    assert "invalid_vector" not in oversized.instrument
    assert "huge_vector" not in oversized.instrument

    engine.close()
    engine.close()
    assert instrument.close_calls == 1
    with pytest.raises(RuntimeError, match="closed"):
        engine.render(1)


def test_engine_rejects_unsupported_construction_and_nonpositive_render_sizes() -> None:
    with pytest.raises(ValueError, match="sample_rate"):
        Engine(FakeInstrument(), sample_rate=44_000)
    with pytest.raises(ValueError, match="block"):
        Engine(FakeInstrument(), block=128)
    with pytest.raises(ValueError, match="master sample rate"):
        Engine(FakeInstrument(), sample_rate=44_100, master=MasterBus(48_000))
    with pytest.raises(ValueError, match="master ceiling"):
        Engine(FakeInstrument(), master=MasterBus(ceiling=1))
    engine = OfflineEngine(FakeInstrument())
    for frames in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            engine.render(frames)  # type: ignore[arg-type]


def test_note_events_and_instrument_commands_are_dispatched_at_sample_offsets() -> None:
    instrument = FakeInstrument()
    engine = Engine(instrument)
    engine.push(NoteOn(1, 60, 1, "test", frame=20))
    engine.push(InstrumentEvent("bend", (2,), frame=70))
    engine.push(NoteOff(1, frame=90))

    engine.render(256)

    assert instrument.bus_frames == 256
    assert instrument.events == [("bend", (2,), 70)]
    assert instrument.created[0].release_calls == 1
    assert engine.telemetry().active_voices == 1


def test_voice_steal_fades_survive_a_full_burst_at_the_end_of_a_block() -> None:
    engine = Engine(FakeInstrument(), max_voices=1, event_queue=EventQueue(maxsize=10))
    for note_id in range(1, 11):
        engine.push(NoteOn(note_id, 60, 1, "burst", frame=255))

    engine.render(1)

    assert engine.voice_manager.active_count == 1
    assert engine.voice_manager.tail_count == 9


@pytest.mark.parametrize("tail_trigger", ("steal", "limit", "panic"))
def test_fade_tails_keep_the_last_per_voice_modulation_snapshot(tail_trigger: str) -> None:
    class ScopedVoice:
        finished = False

        def start(self, pitch: float, velocity: float, params: ParamSnapshot) -> None:
            del pitch, velocity, params

        def release(self) -> None:
            pass

        def render(self, frames: int, params: ParamSnapshot) -> np.ndarray:
            return np.full((frames, 2), params["voice.level"], dtype=np.float32)

    class ScopedInstrument:
        def create_voice(self, rng: np.random.Generator) -> ScopedVoice:
            del rng
            return ScopedVoice()

    registry = ParamRegistry((
        ParamSpec("voice.level", "Voice level", "", 0, 1, 0.5, modulatable=True, modulation_scope="voice"),
    ))
    data = ModulationConfig.defaults().to_dict()
    data["slots"][0] = {"source": "velocity", "destination": "voice.level", "amount": 1.0}
    modulation = ModulationProcessor(registry, 48_000)
    modulation.set_config(ModulationConfig.from_dict(data))
    modulation.begin_block(0, 256)
    params = ParamSnapshot(registry.defaults())
    manager = VoiceManager(ScopedInstrument(), 1 if tail_trigger == "steal" else 2, 48_000)

    if tail_trigger == "steal":
        manager.note_on(NoteOn(1, 60, 0.1, "test"), params, modulation=modulation)
        before = manager.render(1, params, modulation=modulation)
        manager.note_on(NoteOn(2, 64, 0.5, "test"), params, modulation=modulation)
    else:
        manager.note_on(NoteOn(1, 60, 0.5, "test"), params, modulation=modulation)
        manager.note_on(NoteOn(2, 64, 0.1, "test"), params, modulation=modulation)
        before = manager.render(1, params, modulation=modulation)
        if tail_trigger == "limit":
            manager.set_limit(1)
        else:
            manager.panic()

    after = manager.render(1, params, modulation=modulation, frame_index=1)

    np.testing.assert_allclose(before[0], (0.1, 0.1) if tail_trigger == "steal" else (0.6, 0.6))
    np.testing.assert_allclose(after[0], (0.6, 0.6))
