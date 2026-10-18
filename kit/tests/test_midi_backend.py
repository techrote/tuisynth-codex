from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from trio_kit.events import ControlChange, ModWheel, NoteOff, NoteOn, Panic, Sustain
from trio_kit.input import (
    CcLearnMap,
    FakeMidiBackend,
    MidiInput,
    RtMidiBackend,
)


def test_fake_backend_delivers_parsed_events_and_learns_raw_controller_changes(tmp_path) -> None:
    backend = FakeMidiBackend(("USB Piano", "Drum Pad"))
    events = []
    learn = CcLearnMap(tmp_path / "midi-map.json")
    learn.arm("filter.cutoff")
    service = MidiInput(events.append, selection="usb", backend=backend, cc_learn=learn)

    service.start(background=False)
    assert service.status == "MIDI: USB Piano"
    assert service.available_ports == ("USB Piano", "Drum Pad")
    assert backend.send([0x90, 60, 100])
    note_on = events[-1]
    assert isinstance(note_on, NoteOn)
    assert note_on.pitch == 60

    assert backend.send([0xB0, 74, 91])
    assert learn.lookup("filter.cutoff") == 74
    assert events[-1] == ControlChange(74, 91)
    assert backend.send([0xB0, 1, 64])
    assert events[-2:] == [ControlChange(1, 64), ModWheel(64 / 127)]
    assert backend.send([0xB0, 64, 127])
    assert events[-1] == Sustain(True)
    assert backend.send([0x80, 60, 0])
    assert events[-1] == NoteOff(note_on.note_id)
    assert service.malformed_count == 0

    service.close()
    assert events[-1] == Sustain(False)
    assert service.status == "MIDI: unavailable (closed)"


def test_missing_rtmidi_is_lazy_and_reports_a_usable_unavailable_state() -> None:
    loads = []

    def missing_dependency():
        loads.append(True)
        raise ImportError("python-rtmidi is not installed")

    backend = RtMidiBackend(module_loader=missing_dependency)
    service = MidiInput(backend=backend)
    assert loads == []
    assert service.status == "MIDI: stopped"
    service.start(background=False)
    assert loads == [True]
    assert service.status.startswith("MIDI: unavailable")
    assert "python-rtmidi is not installed" in service.status
    service.close()


def test_device_disappearance_releases_notes_and_reconnects_by_original_name() -> None:
    backend = FakeMidiBackend(("USB Piano", "Other Device"))
    events = []
    service = MidiInput(events.append, selection=0, backend=backend)
    service.start(background=False)
    assert service.connected_port == "USB Piano"
    backend.send([0x90, 62, 100])
    note_on = events[-1]
    assert isinstance(note_on, NoteOn)

    backend.set_ports(("Other Device",))
    service.poll()
    assert service.connected_port is None
    assert service.status.startswith("MIDI: unavailable")
    assert events[-1] == NoteOff(note_on.note_id)
    assert Panic() not in events
    assert not backend.opened_ports[0].is_open

    backend.set_ports(("Other Device", "USB Piano"))
    service.poll()
    assert service.connected_port == "USB Piano"
    assert service.status == "MIDI: USB Piano"
    assert backend.opened_ports[-1].is_open

    backend.send([0x90, 62, 100])
    current_note = events[-1]
    assert isinstance(current_note, NoteOn)
    assert current_note.note_id != note_on.note_id
    backend.send([0x80, 62, 0])
    assert events[-1] == NoteOff(current_note.note_id)
    service.close()


def test_background_port_poll_reconnects_and_close_stops_the_worker() -> None:
    backend = FakeMidiBackend(("Controller",))
    disconnected = threading.Event()

    def receive(event):
        if isinstance(event, NoteOff):
            disconnected.set()

    service = MidiInput(receive, backend=backend, poll_interval=0.01)
    service.start(background=True)
    assert service.connected_port == "Controller"
    backend.send([0x90, 60, 90])
    backend.set_ports(())
    assert disconnected.wait(1.0)
    assert service.connected_port is None
    backend.set_ports(("Controller",))
    # The background worker reconnects at its next deterministic polling boundary.
    deadline = threading.Event()
    for _ in range(100):
        if service.connected_port == "Controller":
            break
        deadline.wait(0.01)
    assert service.connected_port == "Controller"
    service.close()
    assert service._thread is None or not service._thread.is_alive()


def test_rt_midi_adapter_uses_lazy_instance_callback_and_closes_cleanly() -> None:
    instances = []

    class StubMidiIn:
        def __init__(self) -> None:
            self.callback = None
            self.open = False
            self.closed = False
            self.ignored = None
            instances.append(self)

        def get_ports(self):
            return ["Stub Device"]

        def is_port_open(self):
            return self.open

        def ignore_types(self, **kwargs):
            self.ignored = kwargs

        def set_callback(self, callback):
            self.callback = callback

        def open_port(self, index):
            assert index == 0
            self.open = True

        def cancel_callback(self):
            self.callback = None

        def close_port(self):
            self.open = False
            self.closed = True

    backend = RtMidiBackend(module_loader=lambda: SimpleNamespace(MidiIn=StubMidiIn))
    assert instances == []
    events = []
    service = MidiInput(events.append, backend=backend)
    service.start(background=False)
    assert len(instances) == 1
    instance = instances[0]
    assert instance.ignored == {"sysex": True, "timing": True, "active_sense": True}
    assert instance.callback is not None
    instance.callback(([0x90, 67, 110], 0.125), None)
    assert isinstance(events[-1], NoteOn)
    service.close()
    assert events[-1] == NoteOff(events[-2].note_id)
    assert instance.closed


def test_midi_input_validation_and_selection_switch() -> None:
    for selection in (True, -1, "  ", 1.5):
        with pytest.raises(ValueError, match="selection"):
            MidiInput(selection=selection)  # type: ignore[arg-type]

    backend = FakeMidiBackend(("First", "Second"))
    service = MidiInput(selection=0, backend=backend)
    service.start(background=False)
    assert service.connected_port == "First"
    service.select_port("second")
    assert service.connected_port == "Second"
    service.close()
