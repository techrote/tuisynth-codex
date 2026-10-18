from __future__ import annotations

import time

import pytest

from trio_kit.events import NoteOff, NoteOn, RetargetNote
from trio_kit.tui import FocusRing, PianoWidget, Rect
from trio_kit.tui.testing import HeadlessApp


def make_piano(*, legato: bool = False) -> PianoWidget:
    return PianoWidget("piano", Rect(2, 3, 42, 7), legato_glide=legato)


def test_geometry_covers_every_visible_cell_and_black_key_hits_overlay_white_keys() -> None:
    piano = make_piano()
    for y in range(piano.bounds.y, piano.bounds.bottom):
        for x in range(piano.bounds.x, piano.bounds.right):
            assert piano.pitch_at(x, y) is not None
    assert piano.pitch_at(2, 3) == 48
    assert piano.pitch_at(4, 3) == 49
    assert piano.pitch_at(4, 6) == 48
    assert piano.pitch_at(43, 3) == 71
    assert piano.pitch_at(43, 6) == 71
    assert piano.pitch_at(1, 3) is None
    assert piano.pitch_at(2, 10) is None


def test_real_sgr_clicks_each_visible_piano_cell_with_exact_pitch_and_depth_velocity() -> None:
    piano = make_piano()
    with HeadlessApp(size=(80, 24), widgets=FocusRing((piano,)), event_source=piano) as app:
        for y in range(piano.bounds.y, piano.bounds.bottom):
            for x in range(piano.bounds.x, piano.bounds.right):
                pitch = piano.pitch_at(x, y)
                assert pitch is not None
                app.click(x, y)
                on, off = piano.drain_events()
                expected = 0.35 + 0.65 * (y - piano.bounds.y) / (piano.bounds.height - 1)
                if pitch % 12 in {1, 3, 6, 8, 10}:
                    expected = 0.35 + 0.65 * min(y - piano.bounds.y, piano.black_height - 1) / (piano.black_height - 1)
                assert isinstance(on, NoteOn)
                assert on.pitch == pitch
                assert on.velocity == pytest.approx(expected)
                assert isinstance(off, NoteOff) and off.note_id == on.note_id


def test_real_sgr_gliss_latch_wheel_and_release_outside() -> None:
    piano = make_piano()
    with HeadlessApp(size=(80, 24), widgets=FocusRing((piano,)), event_source=piano) as app:
        app.drag(((2, 4), (4, 4), (6, 4)))
        events = piano.drain_events()
        assert [type(event) for event in events] == [NoteOn, NoteOff, NoteOn, NoteOff, NoteOn, NoteOff]
        assert [event.pitch for event in events if isinstance(event, NoteOn)] == [48, 49, 50]

        app.click(2, 4, button="right")
        assert 48 in piano.latched_pitches
        app.click(2, 4)
        assert isinstance(piano.drain_events()[0], NoteOn)
        app.click(2, 4)
        assert [type(event) for event in piano.drain_events()] == [NoteOff]
        app.click(2, 4, button="right")
        app.drag(((2, 4), (70, 18)))
        assert [type(event) for event in piano.drain_events()] == [NoteOn, NoteOff]
        app.wheel(2, 4, "up")
        assert piano.octave == 1
        app.wheel(2, 4, "down")
        assert piano.octave == 0


def test_legato_gliss_retargets_the_existing_note_and_keyboard_twin_has_a_timed_gate() -> None:
    piano = make_piano(legato=True)
    with HeadlessApp(size=(80, 24), widgets=FocusRing((piano,)), event_source=piano) as app:
        app.drag(((2, 4), (4, 4)))
        events = piano.drain_events()
        assert isinstance(events[0], NoteOn)
        assert isinstance(events[1], RetargetNote) and events[1].note_id == events[0].note_id
        assert isinstance(events[2], NoteOff) and events[2].note_id == events[0].note_id

    assert piano.handle_key("right")
    assert piano.handle_key("up")
    assert piano.cursor_pitch == 61
    assert piano.handle_key("enter")
    note_on = piano.drain_events()[0]
    assert isinstance(note_on, NoteOn) and note_on.pitch == 61
    assert piano.tick(time.monotonic() + 1.0)
    assert isinstance(piano.drain_events()[0], NoteOff)
