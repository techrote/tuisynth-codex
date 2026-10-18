"""AURORA, the evolving spectral pad synthesizer."""

__version__ = "0.1.0"

from trio_aurora.instrument import AuroraInstrument, AuroraVoice, aurora_spec
from trio_aurora.params import aurora_registry, validate_extras
from trio_aurora.padsynth import PadsynthTableSet, PadsynthZone, generate_table_set, generate_zone

__all__ = [
    "AuroraInstrument",
    "AuroraVoice",
    "PadsynthTableSet",
    "PadsynthZone",
    "aurora_registry",
    "aurora_spec",
    "generate_table_set",
    "generate_zone",
    "validate_extras",
]
