from __future__ import annotations

import pytest

from trio_kit.engine.voices import VoiceManager
from trio_kit.events import NoteOff, NoteOn
from trio_kit.params import ParamSnapshot

from engine_fakes import FakeInstrument


PARAMS = ParamSnapshot({})


def note(note_id: int, pitch: float = 60) -> NoteOn:
    return NoteOn(note_id, pitch, 1, "test")


def test_same_pitch_notes_have_independent_identity_and_release() -> None:
    instrument = FakeInstrument()
    manager = VoiceManager(instrument, max_voices=2, sample_rate=48_000)
    first = manager.note_on(note(1), PARAMS)
    second = manager.note_on(note(2), PARAMS)

    assert first is not second
    assert manager.note_ids == (1, 2)
    assert manager.note_off(NoteOff(1))
    assert first.release_calls == 1
    assert second.release_calls == 0
    assert manager.note_ids == (1, 2)


def test_retargeting_changes_pitch_without_changing_note_off_ownership() -> None:
    manager = VoiceManager(FakeInstrument(), max_voices=1, sample_rate=48_000)
    voice = manager.note_on(note(41, 48), PARAMS)

    assert manager.retarget(41, 72)
    assert voice.pitch == 72
    assert manager.note_off(NoteOff(41))
    assert voice.release_calls == 1
    assert not manager.note_off(NoteOff(48))
    for pitch in (True, -1, 128, float("nan")):
        with pytest.raises(ValueError, match="pitch"):
            manager.retarget(41, pitch)  # type: ignore[arg-type]


def test_stealing_prefers_the_quietest_released_voice_and_fades_it_for_five_ms() -> None:
    instrument = FakeInstrument(levels=(0.8, 0.1, 0.5))
    manager = VoiceManager(instrument, max_voices=2, sample_rate=48_000)
    voice1 = manager.note_on(note(1), PARAMS)
    voice2 = manager.note_on(note(2), PARAMS)
    manager.note_off(NoteOff(1))
    manager.note_off(NoteOff(2))
    manager.render(8, PARAMS)

    manager.note_on(note(3, 64), PARAMS)
    assert manager.note_ids == (1, 3)
    assert manager.tail_count == 1
    assert manager._tails[0].fade_frames == 240
    assert voice1.release_calls == 1
    assert voice2.release_calls == 1

    manager.render(239, PARAMS)
    assert manager.tail_count == 1
    manager.render(1, PARAMS)
    assert manager.tail_count == 0


def test_when_all_voices_are_held_the_oldest_voice_is_stolen() -> None:
    instrument = FakeInstrument()
    manager = VoiceManager(instrument, max_voices=2, sample_rate=48_000)
    oldest = manager.note_on(note(1), PARAMS)
    manager.note_on(note(2), PARAMS)

    manager.note_on(note(3), PARAMS)
    assert manager.note_ids == (2, 3)
    assert oldest.release_calls == 1
    assert manager.tail_count == 1


def test_sustain_delays_release_and_panic_clears_sustain_with_ten_ms_fades() -> None:
    instrument = FakeInstrument()
    manager = VoiceManager(instrument, max_voices=2, sample_rate=48_000)
    first = manager.note_on(note(1), PARAMS)
    second = manager.note_on(note(2), PARAMS)

    manager.set_sustain(True)
    assert manager.note_off(NoteOff(1))
    assert first.release_calls == 0
    manager.set_sustain(False)
    assert first.release_calls == 1
    assert second.release_calls == 0

    manager.panic()
    assert not manager.sustain
    assert manager.active_count == 0
    assert second.release_calls == 1
    assert manager.tail_count == 2
    assert all(tail.fade_frames == 480 for tail in manager._tails)
    manager.render(479, PARAMS)
    assert manager.tail_count == 2
    manager.render(1, PARAMS)
    assert manager.tail_count == 0


def test_unknown_and_duplicate_note_ids_do_not_corrupt_voice_ownership() -> None:
    manager = VoiceManager(FakeInstrument(), max_voices=1, sample_rate=48_000)
    manager.note_on(note(1), PARAMS)

    assert not manager.note_off(NoteOff(999))
    try:
        manager.note_on(note(1, 64), PARAMS)
    except ValueError as error:
        assert "already active" in str(error)
    else:
        raise AssertionError("duplicate note ids must be rejected")
    assert manager.note_ids == (1,)
