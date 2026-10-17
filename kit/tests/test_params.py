from __future__ import annotations

import pytest

from trio_kit.params import ParamError, ParamRegistry, ParamSpec, ParamWarning


def make_registry() -> ParamRegistry:
    return ParamRegistry(
        (
            ParamSpec("amp.level", "Level", "dB", -60, 6, 0),
            ParamSpec("filter.cutoff", "Cutoff", "Hz", 20, 20000, 440, curve="log"),
            ParamSpec("env.release", "Release", "ms", 0, 5000, 250),
            ParamSpec("osc.count", "Oscillators", "", 1, 8, 3, kind="discrete"),
            ParamSpec("voice.mode", "Mode", "", 0, 2, 1, kind="choice", choices=("Soft", "Bright", "Noise")),
            ParamSpec("mod.depth", "Depth", "%", 0, 1, 0.25, curve="exp", modulatable=True),
            ParamSpec("pitch.detune", "Detune", "cents", -50, 50, 0),
            ParamSpec("pitch.interval", "Interval", "semitones", -12, 12, 0),
            ParamSpec("fx.mix", "Mix", "%", 0, 100, 25),
        )
    )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"key": "bad", "minimum": 0, "maximum": 1, "default": 0},
        {"key": "amp.level", "minimum": 1, "maximum": 1, "default": 1},
        {"key": "amp.level", "minimum": 0, "maximum": 1, "default": 2},
        {"key": "amp.level", "minimum": 0, "maximum": 1, "default": True},
        {"key": "amp.level", "minimum": 0, "maximum": 1, "default": 0, "kind": "unknown"},
        {"key": "amp.level", "minimum": 0, "maximum": 1, "default": 0, "curve": "cubic"},
        {"key": "amp.level", "minimum": 0, "maximum": 1, "default": 0, "curve": "log"},
        {"key": "amp.level", "minimum": 0, "maximum": 2.5, "default": 0, "kind": "discrete"},
        {"key": "amp.level", "minimum": 1, "maximum": 2, "default": 1, "kind": "choice", "choices": ("a", "b")},
        {"key": "amp.level", "minimum": 0, "maximum": 2, "default": 1, "kind": "choice", "choices": ("a", "a", "b")},
        {"key": "amp.level", "minimum": 0, "maximum": 1, "default": 0, "kind": "choice", "choices": {"a", "b"}},
    ),
)
def test_invalid_specifications_are_rejected(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {"label": "Value", "unit": "", "minimum": 0, "maximum": 1, "default": 0}
    base.update(kwargs)

    with pytest.raises(ParamError):
        ParamSpec(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", (True, False, None, "1", float("nan"), float("inf"), float("-inf"), 10**1000))
def test_hostile_parameter_values_are_rejected_with_the_key(value: object) -> None:
    with pytest.raises(ParamError, match="amp.level"):
        make_registry().validate_value("amp.level", value)


def test_out_of_range_values_are_clamped_and_warned() -> None:
    registry = make_registry()

    with pytest.warns(ParamWarning, match="clamped"):
        assert registry.validate_value("amp.level", 20) == 6
    with pytest.warns(ParamWarning, match="clamped"):
        assert registry.clamp("amp.level", -100) == -60


def test_discrete_and_choice_values_round_to_nearest_integer_and_warn() -> None:
    registry = make_registry()

    with pytest.warns(ParamWarning, match="rounded"):
        assert registry.validate_value("osc.count", 3.6) == 4
    with pytest.warns(ParamWarning, match="rounded"):
        assert registry.validate_value("voice.mode", 0.6) == 1
    assert registry.format("voice.mode", 2) == "Noise"


def test_registry_preserves_spec_order_and_fills_defaults() -> None:
    registry = make_registry()

    assert tuple(registry.specs) == (
        "amp.level",
        "filter.cutoff",
        "env.release",
        "osc.count",
        "voice.mode",
        "mod.depth",
        "pitch.detune",
        "pitch.interval",
        "fx.mix",
    )
    values = registry.validate({"amp.level": 1.5})
    assert values["amp.level"] == 1.5
    assert values["filter.cutoff"] == 440
    assert len(values) == len(registry)


def test_duplicate_or_unknown_registry_keys_are_rejected() -> None:
    first = ParamSpec("amp.level", "Level", "", 0, 1, 0)
    registry = ParamRegistry((first,))

    with pytest.raises(ParamError, match="already registered"):
        registry.register(first)
    with pytest.raises(ParamError, match="unknown parameter"):
        registry.validate_value("amp.unknown", 0)
    with pytest.raises(ParamError, match="unknown parameter"):
        registry.validate({"amp.unknown": 1})


@pytest.mark.parametrize("key, values", (("amp.level", (0, 3, 6)), ("filter.cutoff", (20, 200, 20000)), ("mod.depth", (0, 0.2, 1))))
def test_unit_mapping_round_trips_across_supported_curves(key: str, values: tuple[float, ...]) -> None:
    registry = make_registry()

    for value in values:
        unit_value = registry.to_unit(key, value)
        assert 0 <= unit_value <= 1
        assert registry.from_unit(key, unit_value) == pytest.approx(value)


@pytest.mark.parametrize("unit_value", (True, float("nan"), -0.01, 1.01))
def test_normalized_mapping_rejects_invalid_unit_values(unit_value: object) -> None:
    with pytest.raises(ParamError):
        make_registry().from_unit("amp.level", unit_value)


def test_formatting_uses_audio_units_and_choice_labels() -> None:
    registry = make_registry()

    assert registry.format("filter.cutoff", 440) == "440 Hz"
    assert registry.format("filter.cutoff", 1000) == "1 kHz"
    assert registry.format("env.release", 25.5) == "25.5 ms"
    assert registry.format("env.release", 1500) == "1.5 s"
    assert registry.format("amp.level", -6.25) == "-6.25 dB"
    assert registry.format("mod.depth", 0.256) == "25.6%"
    assert registry.format("pitch.detune", 12) == "12 cents"
    assert registry.format("pitch.interval", -3) == "-3 st"
    assert registry.format("fx.mix", 25) == "25%"


@pytest.mark.parametrize("amount", (0, 0.25, 0.49, 0.5, 0.75, 1))
def test_morph_switches_discrete_and_choice_values_at_half(amount: float) -> None:
    registry = make_registry()
    start = {"osc.count": 1, "voice.mode": 0}
    end = {"osc.count": 8, "voice.mode": 2}

    result = registry.morph(start, end, amount)
    expected = start if amount < 0.5 else end
    assert result["osc.count"] == expected["osc.count"]
    assert result["voice.mode"] == expected["voice.mode"]


def test_morph_interpolates_linear_and_curve_domains() -> None:
    registry = make_registry()
    start = {"amp.level": -60, "filter.cutoff": 20, "mod.depth": 0}
    end = {"amp.level": 6, "filter.cutoff": 20000, "mod.depth": 1}

    result = registry.morph(start, end, 0.5)
    assert result["amp.level"] == pytest.approx(-27)
    assert result["filter.cutoff"] == pytest.approx(20 * 1000**0.5)
    assert result["mod.depth"] == pytest.approx(registry.from_unit("mod.depth", 0.5))


@pytest.mark.parametrize("amount", (0, 0.25, 0.49, 0.5, 0.75, 1))
def test_continuous_morph_respects_each_parameter_curve(amount: float) -> None:
    registry = make_registry()
    result = registry.morph(
        {"amp.level": -60, "filter.cutoff": 20, "mod.depth": 0},
        {"amp.level": 6, "filter.cutoff": 20000, "mod.depth": 1},
        amount,
    )

    assert result["amp.level"] == pytest.approx(-60 + 66 * amount)
    assert result["filter.cutoff"] == pytest.approx(20 * 1000**amount)
    assert result["mod.depth"] == pytest.approx(registry.from_unit("mod.depth", amount))


def test_morph_defaults_missing_values_and_rejects_bad_amounts() -> None:
    registry = make_registry()

    result = registry.morph({}, {"amp.level": 6}, 1)
    assert result["amp.level"] == 6
    assert result["filter.cutoff"] == 440
    for value in (True, -0.1, 1.1, float("nan")):
        with pytest.raises(ParamError):
            registry.morph({}, {}, value)
