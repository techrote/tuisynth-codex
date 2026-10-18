"""Device-free and optional shared note-input adapters."""

from trio_kit.input.cc_learn import CcLearnMap, MidiMapWarning
from trio_kit.input.keyboard import KeyboardPiano
from trio_kit.input.midi import MidiCommand, MidiNoteMap, MidiNoteOff, MidiNoteOn, MidiParser, parse_midi
from trio_kit.input.midi_backend import FakeMidiBackend, FakeMidiPort, MidiInput, RtMidiBackend

__all__ = [
    "CcLearnMap",
    "FakeMidiBackend",
    "FakeMidiPort",
    "KeyboardPiano",
    "MidiCommand",
    "MidiInput",
    "MidiMapWarning",
    "MidiNoteMap",
    "MidiNoteOff",
    "MidiNoteOn",
    "MidiParser",
    "RtMidiBackend",
    "parse_midi",
]
