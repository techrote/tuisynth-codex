"""LOOM, the plucked and strummed string synthesizer."""

__version__ = "0.1.0"

from trio_loom.instrument import LoomInstrument
from trio_loom.params import loom_registry
from trio_loom.presets import load_factory_preset, load_factory_presets
from trio_loom.strum import StrumModel
from trio_loom.waveguide import WaveguideString, midi_frequency

__all__ = [
    "LoomInstrument",
    "StrumModel",
    "WaveguideString",
    "load_factory_preset",
    "load_factory_presets",
    "loom_registry",
    "midi_frequency",
]
