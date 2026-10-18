"""Lazy RtMidi input service with deterministic fake ports for tests."""

from __future__ import annotations

import importlib
import math
import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from trio_kit.events import ControlChange, Event, NoteIds, Panic, Sustain
from trio_kit.input.cc_learn import CcLearnMap
from trio_kit.input.midi import MidiNoteMap, MidiParser


class MidiPort(Protocol):
    name: str

    def close(self) -> None: ...


class MidiBackend(Protocol):
    def list_ports(self) -> Sequence[str]: ...

    def open_input(self, index: int, name: str, callback: Callable[[object], None]) -> MidiPort: ...


class _RtMidiPort:
    def __init__(self, midi_in: Any, name: str) -> None:
        self._midi_in = midi_in
        self.name = name
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._midi_in.cancel_callback()
        finally:
            self._midi_in.close_port()


class RtMidiBackend:
    """Adapter for `python-rtmidi`, imported only on first port query."""

    def __init__(self, module_loader: Callable[[], Any] | None = None) -> None:
        self._module_loader = module_loader
        self._midi_in: Any | None = None

    def _instance(self) -> Any:
        if self._midi_in is None:
            module = self._module_loader() if self._module_loader is not None else importlib.import_module("rtmidi")
            self._midi_in = module.MidiIn()
        return self._midi_in

    def list_ports(self) -> Sequence[str]:
        return tuple(str(name) for name in self._instance().get_ports())

    def open_input(self, index: int, name: str, callback: Callable[[object], None]) -> MidiPort:
        midi_in = self._instance()
        if midi_in.is_port_open():
            raise RuntimeError("an RtMidi input port is already open")
        midi_in.ignore_types(sysex=True, timing=True, active_sense=True)

        def dispatch(message_and_time: object, _data: object = None) -> None:
            if isinstance(message_and_time, (tuple, list)) and message_and_time:
                callback(message_and_time[0])
            else:
                callback(message_and_time)

        midi_in.set_callback(dispatch)
        try:
            midi_in.open_port(index)
        except Exception:
            try:
                midi_in.cancel_callback()
            except Exception:
                pass
            try:
                midi_in.close_port()
            except Exception:
                pass
            raise
        return _RtMidiPort(midi_in, name)


class FakeMidiPort:
    """In-memory MIDI input port; sending bytes never touches hardware."""

    def __init__(self, name: str, callback: Callable[[object], None]) -> None:
        self.name = name
        self._callback: Callable[[object], None] | None = callback
        self.is_open = True

    def send(self, message: object) -> bool:
        if not self.is_open or self._callback is None:
            return False
        self._callback(message)
        return True

    def close(self) -> None:
        self.is_open = False
        self._callback = None


class FakeMidiBackend:
    """Fake port registry for tests, previews, and device-free workflows."""

    def __init__(self, ports: Sequence[str] = ()) -> None:
        self._ports = [str(name) for name in ports]
        self.opened_ports: list[FakeMidiPort] = []

    def list_ports(self) -> Sequence[str]:
        return tuple(self._ports)

    def set_ports(self, ports: Sequence[str]) -> None:
        self._ports = [str(name) for name in ports]

    def open_input(self, index: int, name: str, callback: Callable[[object], None]) -> FakeMidiPort:
        if not 0 <= index < len(self._ports) or self._ports[index] != name:
            raise IndexError("fake MIDI port list changed before it could be opened")
        port = FakeMidiPort(name, callback)
        self.opened_ports.append(port)
        return port

    @property
    def active_port(self) -> FakeMidiPort | None:
        return next((port for port in reversed(self.opened_ports) if port.is_open), None)

    def send(self, message: object) -> bool:
        port = self.active_port
        return False if port is None else port.send(message)


def _positive_interval(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("poll_interval must be a finite positive number of seconds")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("poll_interval must be a finite positive number of seconds") from error
    if not math.isfinite(result) or not 0 < result <= 3_600:
        raise ValueError("poll_interval must be in the range (0, 3600] seconds")
    return result


def _port_selection(value: object) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("selection must be None, a non-negative port index, or a non-empty name substring")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("selection must be None, a non-negative port index, or a non-empty name substring")
        return value
    if isinstance(value, str):
        selected = value.strip()
        if selected:
            return selected
    raise ValueError("selection must be None, a non-negative port index, or a non-empty name substring")


class MidiInput:
    """Selectable, reconnecting MIDI input with a two-second background poll."""

    def __init__(
        self,
        on_event: Callable[[Event], None] | None = None,
        *,
        selection: int | str | None = None,
        channel: int | None = None,
        bend_range: float = 2.0,
        note_ids: NoteIds | None = None,
        cc_learn: CcLearnMap | None = None,
        backend: MidiBackend | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        selection = _port_selection(selection)
        if on_event is not None and not callable(on_event):
            raise ValueError("on_event must be callable")
        if cc_learn is not None and not isinstance(cc_learn, CcLearnMap):
            raise ValueError("cc_learn must be a CcLearnMap")
        self.selection = selection
        self.poll_interval = _positive_interval(poll_interval)
        self.parser = MidiParser(channel=channel, bend_range=bend_range)
        self.note_map = MidiNoteMap(note_ids)
        self.cc_learn = cc_learn
        self._on_event = on_event
        self._backend: MidiBackend = backend if backend is not None else RtMidiBackend()
        self._port: MidiPort | None = None
        self._port_name: str | None = None
        self._preferred_name: str | None = None
        self._ports: tuple[str, ...] = ()
        self._status = "MIDI: stopped"
        self._last_error: str | None = None
        self._sustain_on = False
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._closed = False
        self._generation = 0

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    @property
    def available_ports(self) -> tuple[str, ...]:
        with self._lock:
            return self._ports

    @property
    def connected_port(self) -> str | None:
        with self._lock:
            return self._port_name

    @property
    def malformed_count(self) -> int:
        return self.parser.malformed_count

    def start(self, *, background: bool = True) -> MidiInput:
        if not isinstance(background, bool):
            raise ValueError("background must be a boolean")
        with self._lock:
            if self._closed:
                raise RuntimeError("MIDI input is closed")
            if not self._started:
                self._started = True
                self._stop.clear()
        self.poll()
        if background and self._thread is None:
            with self._lock:
                if self._thread is None and not self._closed:
                    self._thread = threading.Thread(target=self._run, name="trio-midi-poll", daemon=True)
                    self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.poll_interval):
            self.poll()

    def _resolve(self, ports: tuple[str, ...]) -> tuple[int, str] | None:
        if self._preferred_name is not None:
            return next(((index, name) for index, name in enumerate(ports) if name == self._preferred_name), None)
        if not ports:
            return None
        if isinstance(self.selection, int):
            index = self.selection
            return (index, ports[index]) if index < len(ports) else None
        if isinstance(self.selection, str):
            needle = self.selection.casefold()
            return next(((index, name) for index, name in enumerate(ports) if needle in name.casefold()), None)
        return 0, ports[0]

    def _emit(self, event: Event) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception as error:
            self._last_error = f"MIDI event callback failed: {error}"[:256]

    def _on_message(self, message: object, generation: int) -> None:
        with self._lock:
            if self._closed or generation != self._generation:
                return
            try:
                commands = self.parser.parse(message)
                for command in commands:
                    if isinstance(command, Sustain):
                        self._sustain_on = command.on
                    elif isinstance(command, Panic):
                        self._sustain_on = False
                    if isinstance(command, ControlChange) and self.cc_learn is not None:
                        self.cc_learn.feed(command)
                    for event in self.note_map.translate([command]):
                        self._emit(event)
            except Exception as error:
                self._last_error = f"MIDI message rejected: {error}"[:256]

    def _disconnect(self, reason: str | None = None) -> None:
        port = self._port
        self._port = None
        self._port_name = None
        if port is not None:
            self._generation += 1
            try:
                port.close()
            except Exception as error:
                reason = reason or str(error)
            release_events = self.note_map.release_all()
            if self._sustain_on:
                release_events.append(Sustain(False))
                self._sustain_on = False
            for event in release_events:
                self._emit(event)
        if reason:
            self._last_error = reason[:256]

    def poll(self) -> None:
        """Refresh ports, open the selected device, or reconnect by name."""
        with self._lock:
            if self._closed:
                return
            try:
                ports = tuple(str(name) for name in self._backend.list_ports())
                if any(not name for name in ports):
                    raise ValueError("MIDI backend returned an empty port name")
                self._ports = ports
            except Exception as error:
                self._disconnect(str(error))
                self._ports = ()
                self._status = f"MIDI: unavailable ({error})"[:256]
                return

            if self._port is not None and self._port_name in ports:
                self._status = f"MIDI: {self._port_name}"
                self._last_error = None
                return
            if self._port is not None:
                self._disconnect("selected MIDI port disappeared")

            resolved = self._resolve(ports)
            if resolved is None:
                if not ports:
                    detail = "no input ports"
                elif isinstance(self.selection, int):
                    detail = f"port index {self.selection} is unavailable"
                else:
                    detail = f"port {self.selection!r} is unavailable"
                self._status = f"MIDI: unavailable ({detail})"
                return

            index, name = resolved
            self._generation += 1
            generation = self._generation
            try:
                callback = lambda message: self._on_message(message, generation)
                self._port = self._backend.open_input(index, name, callback)
                self._port_name = name
                self._preferred_name = name
                self._status = f"MIDI: {name}"
                self._last_error = None
            except Exception as error:
                self._generation += 1
                self._status = f"MIDI: unavailable ({error})"[:256]
                self._last_error = str(error)[:256]

    def select_port(self, selection: int | str | None) -> None:
        """Change the requested port and reconnect immediately if possible."""
        selection = _port_selection(selection)
        with self._lock:
            if self._closed:
                raise RuntimeError("MIDI input is closed")
            self._disconnect("MIDI port selection changed")
            self.selection = selection
            self._preferred_name = None
        self.poll()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.1, self.poll_interval + 0.1))
        with self._lock:
            self._disconnect("MIDI input closed")
            self._status = "MIDI: unavailable (closed)"

    def __enter__(self) -> MidiInput:
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


__all__ = ["FakeMidiBackend", "FakeMidiPort", "MidiBackend", "MidiInput", "MidiPort", "RtMidiBackend"]
