from __future__ import annotations

from trio_aurora.instrument import aurora_spec
from trio_aurora.params import validate_extras
from trio_kit.cli import _preset_library, _selftest


EXPECTED_PRESETS = {
    "glacier-choir",
    "northern-veil",
    "cathedral-air",
    "solar-bloom",
    "ice-strings",
    "deep-ocean",
    "hollow-partials",
    "stretch-bells",
}


def test_factory_presets_are_distinct_documented_harmonic_profiles() -> None:
    spec = aurora_spec()
    presets = _preset_library(spec, None).list_factory_presets()
    assert {preset.id for preset in presets} == EXPECTED_PRESETS
    assert all(preset.description for preset in presets)
    assert all("sequencer" in preset.extras for preset in presets)
    profiles = [
        tuple(validate_extras({key: value for key, value in preset.extras.items() if key != "sequencer"})["harmonics"])
        for preset in presets
    ]
    assert len(set(profiles)) == len(EXPECTED_PRESETS)


def test_selftest_renders_every_preset_and_headless_factory_skin() -> None:
    renders, summary = _selftest(aurora_spec(), None, 48_000, 2718)
    assert renders == len(EXPECTED_PRESETS)
    assert "8 presets" in summary
