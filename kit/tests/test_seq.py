from __future__ import annotations

import pytest

from trio_kit.engine import Engine
from trio_kit.events import NoteOff, NoteOn, Panic, Transport
from trio_kit.params import ParamRegistry, ParamSpec
from trio_kit.preset import Preset, PresetLibrary
from trio_kit.seq import (
    Arpeggiator,
    ArpeggiatorConfig,
    Pattern,
    SequenceConfig,
    SequencerProcessor,
    Step,
    arp_interval_frames,
    validate_extras,
)

from engine_fakes import FakeInstrument


def _on_pattern(length: int = 16, *, note: int | None = 60, gate: float = 0.5, probability: float = 1.0) -> Pattern:
    return Pattern(length, (tuple(Step(True, note, 0.7, gate, probability) for _ in range(length)),))


def _render_processor(processor: SequencerProcessor, frames: int) -> list[tuple[int, object]]:
    events: list[tuple[int, object]] = []
    for start in range(0, frames, 256):
        events.extend((start + event.frame, event) for event in processor.process_block(start, ()))
    return events


def test_step_boundaries_are_sample_accurate_for_64_steps_at_supported_rates() -> None:
    for sample_rate in (44_100, 48_000):
        processor = SequencerProcessor(sample_rate)
        processor.set_config(SequenceConfig(pattern=_on_pattern(), playing=True))
        step_frames = sample_rate * 60 / 120 / 4
        rendered = _render_processor(processor, round(step_frames * 66))
        note_ons = [(frame, event) for frame, event in rendered if isinstance(event, NoteOn) and event.source == "sequencer"]
        note_off_ids = {event.note_id for _frame, event in rendered if isinstance(event, NoteOff)}

        assert len(note_ons) >= 64
        for index, (frame, _event) in enumerate(note_ons[:64]):
            assert abs(frame - round(index * step_frames)) <= 1
        assert all(event.note_id in note_off_ids for _frame, event in note_ons[:64])


def test_swing_delays_even_numbered_sixteenth_steps_and_tempo_change_releases() -> None:
    processor = SequencerProcessor(48_000)
    processor.set_config(SequenceConfig(pattern=_on_pattern(), swing=0.5, playing=True))
    rendered = _render_processor(processor, 10_000)
    note_ons = [(frame, event) for frame, event in rendered if isinstance(event, NoteOn) and event.source == "sequencer"]
    assert [frame for frame, _event in note_ons[:2]] == [0, 9_000]

    tempo_change = processor.process_block(10_240, (Transport(tempo=90, swing=0.0, playing=True, frame=32),))
    offs = [event for event in tempo_change if isinstance(event, NoteOff)]
    assert any(event.frame == 32 for event in offs)
    on = next(event for event in tempo_change if isinstance(event, NoteOn) and event.source == "sequencer")
    assert on.frame == 32


def test_gate_tracks_swing_adjusted_sixteenth_duration() -> None:
    processor = SequencerProcessor(48_000)
    processor.set_config(SequenceConfig(pattern=_on_pattern(gate=0.5), swing=0.5, playing=True))
    rendered = _render_processor(processor, 11_000)
    note_ids = {event.note_id: frame for frame, event in rendered if isinstance(event, NoteOn) and event.source == "sequencer"}
    off_frames = {event.note_id: frame for frame, event in rendered if isinstance(event, NoteOff)}
    assert sorted(note_ids.values())[:2] == [0, 9_000]
    assert off_frames[next(note_id for note_id, frame in note_ids.items() if frame == 0)] == 4_500
    assert off_frames[next(note_id for note_id, frame in note_ids.items() if frame == 9_000)] == 10_500


def test_arp_setting_edits_do_not_restart_or_release_the_step_transport() -> None:
    processor = SequencerProcessor(48_000)
    pattern = _on_pattern(gate=1.0)
    processor.set_config(SequenceConfig(pattern=pattern, playing=True))
    first = processor.process_block(0, ())
    active = next(event for event in first if isinstance(event, NoteOn) and event.source == "sequencer")
    arp = ArpeggiatorConfig(enabled=True)
    processor.set_config(SequenceConfig(pattern=pattern, playing=True, arpeggiator=arp))
    changed = processor.process_block(256, (NoteOn(12, 64, 0.6, "keyboard"),))
    assert not any(isinstance(event, NoteOff) and event.note_id == active.note_id for event in changed)
    assert not any(isinstance(event, NoteOn) and event.source == "sequencer" for event in changed)
    assert any(isinstance(event, NoteOn) and event.source == "arpeggiator" for event in changed)


def test_arpeggiator_seed_does_not_change_seeded_step_probability() -> None:
    pattern = _on_pattern(16, probability=0.5)
    traces = []
    for arp_seed in (0, 177):
        processor = SequencerProcessor(48_000, seed=11)
        processor.set_config(SequenceConfig(
            pattern=pattern,
            playing=True,
            arpeggiator=ArpeggiatorConfig(seed=arp_seed),
        ))
        rendered = _render_processor(processor, 48_000 * 2)
        traces.append(tuple(
            frame for frame, event in rendered
            if isinstance(event, NoteOn) and event.source == "sequencer"
        ))
    assert traces[0] == traces[1]


def test_stop_edit_panic_and_probability_preserve_note_release_ownership() -> None:
    processor = SequencerProcessor(48_000, seed=10)
    processor.set_config(SequenceConfig(pattern=_on_pattern(), playing=True))
    started = processor.process_block(0, ())
    active = next(event for event in started if isinstance(event, NoteOn))

    stopped = processor.process_block(256, (Transport(playing=False, frame=40),))
    assert NoteOff(active.note_id, frame=40) in stopped
    assert not any(isinstance(event, NoteOn) and event.source == "sequencer" for event in stopped)

    processor.set_config(SequenceConfig(pattern=_on_pattern(), playing=True))
    started_again = processor.process_block(512, ())
    active_again = next(event for event in started_again if isinstance(event, NoteOn) and event.source == "sequencer")
    processor.set_config(SequenceConfig(pattern=_on_pattern(probability=0.0), playing=True))
    edited = processor.process_block(768, ())
    assert any(isinstance(event, NoteOff) for event in edited)
    assert any(isinstance(event, NoteOff) and event.note_id == active_again.note_id for event in edited)
    assert not any(isinstance(event, NoteOn) and event.source == "sequencer" for event in edited)

    processor.set_config(SequenceConfig(pattern=_on_pattern(), playing=True))
    started_again = processor.process_block(1_024, ())
    active_again = next(event for event in started_again if isinstance(event, NoteOn) and event.source == "sequencer")
    panicked = processor.process_block(1_280, (Panic(),))
    assert NoteOff(active_again.note_id, frame=0) in panicked
    assert any(isinstance(event, Panic) for event in panicked)
    assert not any(isinstance(event, NoteOn) and event.source == "sequencer" for event in panicked)


def test_arpeggiator_orders_modes_octaves_rates_latch_and_seeded_random() -> None:
    notes = (60.0, 64.0, 67.0)
    assert Arpeggiator(ArpeggiatorConfig(mode="up")).order(notes) == notes
    assert Arpeggiator(ArpeggiatorConfig(mode="down")).order(notes) == tuple(reversed(notes))
    assert Arpeggiator(ArpeggiatorConfig(mode="updown")).order(notes) == (60.0, 64.0, 67.0, 64.0)
    assert Arpeggiator(ArpeggiatorConfig(mode="as-played")).order((67, 60, 64)) == (67.0, 60.0, 64.0)
    first = Arpeggiator(ArpeggiatorConfig(mode="random", seed=9)).order(notes)
    second = Arpeggiator(ArpeggiatorConfig(mode="random", seed=9)).order(notes)
    assert first == second
    assert Arpeggiator(ArpeggiatorConfig(octaves=2)).order((60, 64)) == (60, 64, 72, 76)
    assert {
        rate: arp_interval_frames(48_000, 120, rate)
        for rate in ("1/4", "1/8", "1/8T", "1/16", "1/16T", "1/32")
    } == {"1/4": 24_000, "1/8": 12_000, "1/8T": 8_000, "1/16": 6_000, "1/16T": 4_000, "1/32": 3_000}

    processor = SequencerProcessor(48_000)
    arp = ArpeggiatorConfig(enabled=True, mode="up", latch=True, rate="1/32")
    processor.set_config(SequenceConfig(arpeggiator=arp))
    events = processor.process_block(0, (NoteOn(42, 64, 0.9, "midi"), NoteOff(42, frame=20)))
    arp_notes = [event for event in events if isinstance(event, NoteOn) and event.source == "arpeggiator"]
    assert len(arp_notes) == 1
    assert arp_notes[0].velocity == 0.9
    assert not any(isinstance(event, NoteOn) and event.source == "midi" for event in events)
    later = _render_processor(processor, 4_096)
    assert any(isinstance(event, NoteOn) and event.source == "arpeggiator" for _frame, event in later)
    processor.set_config(SequenceConfig(arpeggiator=ArpeggiatorConfig(enabled=True, latch=False, rate="1/32")))
    unlatch = processor.process_block(4_352, ())
    assert any(isinstance(event, NoteOff) for event in unlatch)
    assert not any(isinstance(event, NoteOn) and event.source == "arpeggiator" for event in _render_processor(processor, 4_096))


def test_engine_owns_block_scheduler_and_shared_extras_round_trip_through_preset(tmp_path) -> None:
    registry = ParamRegistry((ParamSpec("amp.gain", "Gain", "", 0, 1, 0.5),))
    library = PresetLibrary("demo", registry, data_dir=tmp_path, extras_validator=validate_extras)
    config = SequenceConfig(pattern=_on_pattern(4, note=48), tempo=100, swing=0.2, playing=True)
    preset = Preset("demo", "sequenced", "Sequenced", registry.defaults(), {"sequencer": config.to_dict()})
    library.save(preset)
    loaded = library.get("sequenced")
    assert SequenceConfig.from_dict(loaded.extras["sequencer"]) == config

    engine = Engine(FakeInstrument(), sample_rate=48_000, registry=registry)
    try:
        engine.set_extras(validate_extras({"sequencer": config.to_dict()}))
        engine.render(256)
        assert SequenceConfig.from_dict(engine.get_extras()["sequencer"]) == config
        assert engine.sequencer.config == config
        assert engine.voice_manager.active_count == 1
    finally:
        engine.close()


@pytest.mark.parametrize(
    "raw",
    (
        {"pattern": {"length": 0}},
        {"pattern": {"length": 33}},
        {"pattern": {"length": 2, "lanes": [[], [], [], [], []]}},
        {"pattern": {"length": 1, "lanes": [[{"on": True, "note": 128}]]}},
        {"pattern": {"length": 1, "lanes": [[{"velocity": -0.01}]]}},
        {"pattern": {"length": 1, "lanes": [[{"gate": 0.01}]]}},
        {"pattern": {"length": 1, "lanes": [[{"probability": 1.01}]]}},
        {"tempo": 39},
        {"swing": 0.61},
        {"arpeggiator": {"mode": "sideways"}},
        {"arpeggiator": {"rate": "1/128"}},
        {"unknown": True},
    ),
)
def test_sequence_config_rejects_invalid_pattern_transport_and_arp_fields(raw: object) -> None:
    with pytest.raises(ValueError):
        SequenceConfig.from_dict(raw)
