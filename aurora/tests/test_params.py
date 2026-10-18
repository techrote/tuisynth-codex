from __future__ import annotations

from pathlib import Path

import pytest

from trio_aurora.params import DEFAULT_HARMONICS, aurora_registry, validate_extras


EXPECTED_KEYS = {
    "spec.count", "spec.bw", "spec.bwscale", "spec.stretch", "spec.tilt", "spec.noise", "spec.seed",
    "osc.octave", "osc.detune", "osc.width",
    "amp.a", "amp.d", "amp.s", "amp.r", "amp.vel",
    "flt.mode", "flt.cut", "flt.res", "flt.env", "flt.key",
    "fenv.a", "fenv.d", "fenv.s", "fenv.r",
    "lfo.rate", "lfo.depth", "lfo.wave", "lfo.tgt",
    "fx.chorus.mix", "fx.delay.time", "fx.delay.fb", "fx.delay.mix",
    "fx.reverb.size", "fx.reverb.damp", "fx.reverb.mix", "master.level", "master.drive",
}


def test_registry_matches_the_complete_aurora_surface_and_dsp_references() -> None:
    registry = aurora_registry()
    assert len(registry) == 37
    assert set(registry.specs) == EXPECTED_KEYS
    assert set(registry.defaults()) == EXPECTED_KEYS

    package = Path(__file__).parents[1] / "src" / "trio_aurora"
    source = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    assert all(f'"{key}"' in source for key in EXPECTED_KEYS)


def test_harmonic_extras_are_finite_bounded_and_padded_to_64() -> None:
    extras = validate_extras({"harmonics": [1.0, 0.5, 0.25]})
    assert extras["harmonics"][:3] == [1.0, 0.5, 0.25]
    assert len(extras["harmonics"]) == 64
    assert extras["harmonics"][3:] == [0.0] * 61
    assert len(DEFAULT_HARMONICS) == 64

    for invalid in ([True], [float("nan")], [-0.01], [1.01], [0.0] * 65):
        with pytest.raises(ValueError):
            validate_extras({"harmonics": invalid})
    with pytest.raises(ValueError, match="unknown AURORA extra"):
        validate_extras({"unknown": 1})
