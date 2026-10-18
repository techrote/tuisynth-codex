"""Vectorized, deterministic PADsynth spectral table generation."""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import threading

import numpy as np

from trio_aurora.params import DEFAULT_HARMONICS, aurora_registry, choice_label, validate_extras
from trio_kit.params import ParamRegistry


TABLE_SIZE = 1 << 18
ZONE_NOTES = tuple(24 + 12 * index for index in range(7))
_PHASE_TAU = 2.0 * math.pi


def _normalized_harmonics(harmonics: Sequence[float]) -> tuple[float, ...]:
    normalized = validate_extras({"harmonics": list(harmonics)})["harmonics"]
    return tuple(float(value) for value in normalized)


def note_frequency(note: float) -> float:
    """Convert a MIDI note to equal-tempered frequency."""
    return 440.0 * 2.0 ** ((float(note) - 69.0) / 12.0)


@dataclass(frozen=True, slots=True)
class PadsynthZone:
    base_note: int
    frequency: float
    left: np.ndarray
    right: np.ndarray


@dataclass(frozen=True, slots=True)
class PadsynthTableSet:
    key: str
    sample_rate: int
    zones: tuple[PadsynthZone, ...]

    def zone_for_pitch(self, pitch: float) -> PadsynthZone:
        index = int(math.floor((float(pitch) - ZONE_NOTES[0]) / 12.0))
        return self.zones[min(max(index, 0), len(self.zones) - 1)]


def table_set_key(
    sample_rate: int,
    params: Mapping[str, object],
    harmonics: Sequence[float],
) -> str:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate not in (44_100, 48_000):
        raise ValueError("sample_rate must be 44100 or 48000 Hz")
    params = aurora_registry().validate(params)
    harmonics = _normalized_harmonics(harmonics)
    payload = {
        "sample_rate": sample_rate,
        "zones": ZONE_NOTES,
        "spectral": {
            key: params[key]
            for key in ("spec.count", "spec.bw", "spec.bwscale", "spec.stretch", "spec.tilt", "spec.noise", "spec.seed")
        },
        "harmonics": list(harmonics),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def generate_zone(
    sample_rate: int,
    base_note: int,
    params: Mapping[str, object],
    harmonics: Sequence[float] = DEFAULT_HARMONICS,
    *,
    registry: ParamRegistry | None = None,
) -> PadsynthZone:
    """Generate one normalized stereo wavetable with bounded Gaussian windows."""
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate not in (44_100, 48_000):
        raise ValueError("sample_rate must be 44100 or 48000 Hz")
    if isinstance(base_note, bool) or not isinstance(base_note, int) or base_note not in ZONE_NOTES:
        raise ValueError("base_note must be one of the seven C1..C7 zones")
    harmonics = _normalized_harmonics(harmonics)
    active_registry = aurora_registry() if registry is None else registry
    params = active_registry.validate(params)
    count = int(choice_label(active_registry, "spec.count", params["spec.count"]))

    fundamental = note_frequency(base_note)
    magnitude = _paint_magnitude(sample_rate, fundamental, count, params, harmonics)
    bin_count = len(magnitude)

    if not np.any(magnitude > 0.0):
        silence = np.zeros(TABLE_SIZE, dtype=np.float32)
        silence.flags.writeable = False
        return PadsynthZone(base_note, fundamental, silence, silence)

    seed = int(params["spec.seed"])
    left_phase = np.random.default_rng(seed * 2).uniform(0.0, _PHASE_TAU, size=bin_count)
    right_phase = np.random.default_rng(seed * 2 + 1).uniform(0.0, _PHASE_TAU, size=bin_count)
    # DC and Nyquist bins are real-only in an rFFT; assigning them complex
    # phases would attenuate their magnitudes differently for each seed.
    left_phase[0] = left_phase[-1] = 0.0
    right_phase[0] = right_phase[-1] = 0.0
    left = np.fft.irfft(magnitude * np.exp(1j * left_phase), n=TABLE_SIZE)
    right = np.fft.irfft(magnitude * np.exp(1j * right_phase), n=TABLE_SIZE)
    # Parseval's theorem gives the same RMS for every phase realization, so
    # this shared scale preserves exact magnitude spectra across spec.seed.
    power = magnitude[0] ** 2 + magnitude[-1] ** 2 + 2.0 * np.sum(magnitude[1:-1] ** 2)
    spectral_rms = math.sqrt(float(power)) / TABLE_SIZE
    if spectral_rms > 0.0:
        normalizer = 0.16 / spectral_rms
        left = np.asarray(left * normalizer, dtype=np.float32)
        right = np.asarray(right * normalizer, dtype=np.float32)
    else:
        left = np.zeros(TABLE_SIZE, dtype=np.float32)
        right = np.zeros(TABLE_SIZE, dtype=np.float32)
    left.flags.writeable = False
    right.flags.writeable = False
    return PadsynthZone(base_note, fundamental, left, right)


def _paint_magnitude(
    sample_rate: int,
    fundamental: float,
    count: int,
    params: Mapping[str, int | float],
    harmonics: Sequence[float],
) -> np.ndarray:
    """Paint each partial into a four-sigma bounded Gaussian frequency window."""
    bin_hz = sample_rate / TABLE_SIZE
    bin_count = TABLE_SIZE // 2 + 1
    magnitude = np.zeros(bin_count, dtype=np.float64)
    bandwidth = float(params["spec.bw"])
    bandwidth_scale = float(params["spec.bwscale"])
    stretch = float(params["spec.stretch"])
    tilt = float(params["spec.tilt"])
    noise = float(params["spec.noise"])
    max_bin = bin_count - 1

    for harmonic in range(1, count + 1):
        partial_hz = fundamental * harmonic**stretch
        if partial_hz > 0.45 * sample_rate:
            continue
        width_hz = (2.0 ** (bandwidth / 1200.0) - 1.0) * fundamental * harmonic**bandwidth_scale
        sigma_bins = max(0.25, (width_hz / 2.0) / bin_hz)
        center_bin = partial_hz / bin_hz
        radius_bins = 4.0 * sigma_bins
        start = max(0, int(math.floor(center_bin - radius_bins)))
        stop = min(max_bin + 1, int(math.ceil(center_bin + radius_bins)) + 1)
        if stop <= start:
            continue
        bins = np.arange(start, stop, dtype=np.float64)
        gaussian = np.exp(-0.5 * ((bins - center_bin) / sigma_bins) ** 2)
        amplitude = float(harmonics[harmonic - 1]) * 10.0 ** (tilt * math.log2(harmonic) / 20.0)
        magnitude[start:stop] += amplitude * gaussian

    if noise:
        magnitude += noise * 1e-3 * float(np.mean(magnitude))
    return magnitude


def generate_table_set(
    sample_rate: int,
    params: Mapping[str, object],
    harmonics: Sequence[float] = DEFAULT_HARMONICS,
    *,
    registry: ParamRegistry | None = None,
) -> PadsynthTableSet:
    """Generate all seven octave zones, using only a bounded window per partial."""
    active_registry = aurora_registry() if registry is None else registry
    params = active_registry.validate(params)
    harmonics = _normalized_harmonics(harmonics)
    key = table_set_key(sample_rate, params, harmonics)
    zones = tuple(
        generate_zone(sample_rate, note, params, harmonics, registry=active_registry)
        for note in ZONE_NOTES
    )
    return PadsynthTableSet(key, sample_rate, zones)


class TableSetCache:
    """Small thread-safe LRU that retains no more than two complete table sets."""

    def __init__(self, maximum_sets: int = 2) -> None:
        if isinstance(maximum_sets, bool) or not isinstance(maximum_sets, int) or maximum_sets != 2:
            raise ValueError("PADsynth cache retains exactly two table sets")
        self.maximum_sets = maximum_sets
        self._sets: OrderedDict[str, PadsynthTableSet] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> PadsynthTableSet | None:
        with self._lock:
            table_set = self._sets.get(key)
            if table_set is not None:
                self._sets.move_to_end(key)
            return table_set

    def put(self, table_set: PadsynthTableSet) -> PadsynthTableSet:
        if not isinstance(table_set, PadsynthTableSet):
            raise TypeError("cache accepts PadsynthTableSet objects")
        with self._lock:
            self._sets[table_set.key] = table_set
            self._sets.move_to_end(table_set.key)
            while len(self._sets) > self.maximum_sets:
                self._sets.popitem(last=False)
        return table_set

    def get_or_generate(
        self,
        sample_rate: int,
        params: Mapping[str, object],
        harmonics: Sequence[float],
        *,
        registry: ParamRegistry,
        keep_key: str | None = None,
    ) -> PadsynthTableSet:
        normalized = registry.validate(params)
        normalized_harmonics = _normalized_harmonics(harmonics)
        key = table_set_key(sample_rate, normalized, normalized_harmonics)
        cached = self.get(key)
        if cached is not None:
            return cached
        self.retain(keep_key)
        return self.put(generate_table_set(sample_rate, normalized, normalized_harmonics, registry=registry))

    def retain(self, key: str | None) -> None:
        """Drop cached sets other than the set currently used by the audio thread."""
        with self._lock:
            if key is None:
                self._sets.clear()
                return
            keep = self._sets.get(key)
            self._sets.clear()
            if keep is not None:
                self._sets[key] = keep

    def clear(self) -> None:
        with self._lock:
            self._sets.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sets)


__all__ = [
    "PadsynthTableSet",
    "PadsynthZone",
    "TABLE_SIZE",
    "TableSetCache",
    "ZONE_NOTES",
    "generate_table_set",
    "generate_zone",
    "note_frequency",
    "table_set_key",
]
