from __future__ import annotations

import numpy as np
import pytest

from trio_kit.engine import Engine, EngineTelemetry, MasterBus, OfflineEngine
from trio_kit.events import EventQueue, InstrumentEvent, NoteOff, NoteOn, ParamSet
from trio_kit.params import ParamRegistry, ParamSpec

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
        instrument={f"key{index}": index for index in range(50)},
    )
    assert len(oversized.instrument) == 16

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
