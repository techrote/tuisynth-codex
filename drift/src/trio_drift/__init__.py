"""DRIFT, the granular air and formant cloud synthesizer."""

__version__ = "0.1.0"

from trio_drift.formant import FORMANTS, FormantBank, vowel_formants
from trio_drift.grain import Grain, GrainPool, poisson_arrivals, window_values
from trio_drift.instrument import DriftInstrument
from trio_drift.params import WINDOWS, drift_registry
from trio_drift.presets import load_factory_preset, load_factory_presets
from trio_drift.voice import DriftVoice

__all__ = [
    "DriftInstrument",
    "DriftVoice",
    "FORMANTS",
    "FormantBank",
    "Grain",
    "GrainPool",
    "WINDOWS",
    "drift_registry",
    "load_factory_preset",
    "load_factory_presets",
    "poisson_arrivals",
    "vowel_formants",
    "window_values",
]
