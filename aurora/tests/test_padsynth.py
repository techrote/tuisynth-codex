from __future__ import annotations

import time

import numpy as np
import pytest

from trio_aurora.padsynth import (
    TABLE_SIZE,
    PadsynthTableSet,
    PadsynthZone,
    TableSetCache,
    _paint_magnitude,
    generate_table_set,
    generate_zone,
    note_frequency,
)
from trio_aurora.params import aurora_registry


def _params(**updates: float | int) -> dict[str, float | int]:
    return aurora_registry().validate(updates)


def test_harmonic_peaks_follow_the_partial_series_and_bandwidth_control() -> None:
    params = _params(**{"spec.count": 0, "spec.bw": 24, "spec.bwscale": 0, "spec.seed": 27})
    zone = generate_zone(48_000, 24, params, [1.0] * 64)
    spectrum = np.abs(np.fft.rfft(zone.left.astype(np.float64)))
    spacing = 48_000 / TABLE_SIZE
    for harmonic in range(1, 9):
        expected = harmonic * zone.frequency
        center = int(round(expected / spacing))
        radius = max(2, int(np.ceil(expected * 0.01 / spacing)))
        peak = (np.argmax(spectrum[center - radius:center + radius + 1]) + center - radius) * spacing
        assert abs(peak - expected) <= expected * 0.01

    narrow = _paint_magnitude(48_000, note_frequency(24), 16, _params(**{"spec.count": 0, "spec.bw": 12, "spec.bwscale": 0}), [1.0] * 64)
    wide = _paint_magnitude(48_000, note_frequency(24), 16, _params(**{"spec.count": 0, "spec.bw": 360, "spec.bwscale": 0}), [1.0] * 64)

    def width_at_fourth(magnitude: np.ndarray) -> int:
        center = int(round(4 * note_frequency(24) / spacing))
        peak = float(magnitude[center - 20:center + 21].max())
        indexes = np.flatnonzero(magnitude >= peak * 0.501187)
        local = indexes[(indexes >= center - 64) & (indexes <= center + 64)]
        return int(local[-1] - local[0])

    assert width_at_fourth(wide) > width_at_fourth(narrow)


def test_phase_seed_changes_waveform_without_changing_magnitude_spectrum() -> None:
    params = _params(**{"spec.count": 0, "spec.bw": 60, "spec.seed": 9})
    first = generate_zone(44_100, 48, params, [1.0, 0.4, 0.2])
    second = generate_zone(44_100, 48, {**params, "spec.seed": 10}, [1.0, 0.4, 0.2])
    repeated = generate_zone(44_100, 48, params, [1.0, 0.4, 0.2])
    assert not np.array_equal(first.left, second.left)
    assert np.array_equal(first.left, repeated.left)
    magnitude_a = np.abs(np.fft.rfft(first.left.astype(np.float64)))
    magnitude_b = np.abs(np.fft.rfft(second.left.astype(np.float64)))
    painted_bins = magnitude_a > float(np.max(magnitude_a)) * 1e-4
    assert np.allclose(magnitude_a[painted_bins], magnitude_b[painted_bins], rtol=2e-5, atol=1e-6)
    assert np.sqrt(np.mean(first.left.astype(np.float64) ** 2)) == pytest.approx(0.16, abs=2e-6)


def test_partials_above_the_nyquist_policy_are_not_painted() -> None:
    params = _params(**{"spec.count": 2, "spec.bw": 1, "spec.bwscale": 0, "spec.seed": 1})
    magnitude = _paint_magnitude(48_000, note_frequency(96), 64, params, [1.0] * 64)
    frequencies = np.fft.rfftfreq(TABLE_SIZE, 1 / 48_000)
    assert np.any(magnitude > 0)
    assert np.count_nonzero(magnitude[frequencies > 0.45 * 48_000 + 100]) == 0


def test_seven_zone_generation_is_bounded_and_cache_holds_only_two_sets() -> None:
    params = _params(**{"spec.count": 2, "spec.seed": 314})
    started = time.perf_counter()
    table_set = generate_table_set(48_000, params, [1.0] * 64)
    elapsed = time.perf_counter() - started
    assert len(table_set.zones) == 7
    assert all(zone.left.shape == zone.right.shape == (TABLE_SIZE,) for zone in table_set.zones)
    assert all(not zone.left.flags.writeable and not zone.right.flags.writeable for zone in table_set.zones)
    assert elapsed < 10.0

    cache = TableSetCache()
    placeholder = PadsynthZone(24, 32.7, np.zeros(0), np.zeros(0))
    for index in range(3):
        cache.put(PadsynthTableSet(str(index), 48_000, (placeholder,)))
    assert len(cache) == 2
    assert cache.get("0") is None
