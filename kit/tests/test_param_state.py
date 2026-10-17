from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from trio_kit.params import ParamError, ParamRegistry, ParamSnapshot, ParamSpec, ParamState, ParamWarning


def make_registry() -> ParamRegistry:
    return ParamRegistry(
        (
            ParamSpec("amp.level", "Level", "", 0, 2, 1),
            ParamSpec("osc.count", "Count", "", 1, 8, 3, kind="discrete"),
        )
    )


def test_snapshot_is_immutable_copies_input_and_preserves_stepped_types() -> None:
    values = {"amp.level": 1.5, "osc.count": 4}
    snapshot = ParamSnapshot(values, version=3)
    values["amp.level"] = 0.5

    assert snapshot["amp.level"] == 1.5
    assert snapshot["osc.count"] == 4
    assert isinstance(snapshot["osc.count"], int)
    assert snapshot.version == 3
    with pytest.raises(TypeError):
        snapshot["amp.level"] = 0  # type: ignore[index]


def test_parameter_changes_publish_complete_snapshots_atomically() -> None:
    state = ParamState(make_registry())
    first = state.apply({"amp.level": 1.25, "osc.count": 5})
    assert first.version == 1
    assert first["amp.level"] == 1.25
    assert first["osc.count"] == 5

    with pytest.raises(ParamError, match="unknown parameter"):
        state.apply({"amp.level": 0.25, "bad.key": 1})
    assert state.snapshot is first
    assert state.snapshot["amp.level"] == 1.25


def test_clamping_and_stepped_rounding_warn_without_mutating_old_snapshots() -> None:
    state = ParamState(make_registry())
    original = state.snapshot

    with pytest.warns(ParamWarning, match="clamped"):
        clamped = state.set("amp.level", 10)
    with pytest.warns(ParamWarning, match="rounded"):
        stepped = state.set("osc.count", 5.6)

    assert clamped["amp.level"] == 2
    assert stepped["osc.count"] == 6
    assert original["amp.level"] == 1
    assert original.version == 0
    assert stepped.version == 2


def test_unchanged_updates_do_not_publish_a_new_version_and_reset_restores_defaults() -> None:
    state = ParamState(make_registry())
    assert state.set("amp.level", 1) is state.snapshot
    state.set("amp.level", 0.25)

    reset = state.reset()
    assert reset.version == 2
    assert reset["amp.level"] == 1
    assert reset["osc.count"] == 3


def test_concurrent_updates_publish_coherent_snapshots() -> None:
    registry = make_registry()
    state = ParamState(registry)

    def set_level(value: int) -> int:
        return state.set("amp.level", value / 10).version

    with ThreadPoolExecutor(max_workers=8) as executor:
        versions = list(executor.map(set_level, range(1, 9)))

    assert sorted(versions) == list(range(1, 9))
    snapshot = state.snapshot
    assert snapshot.version == 8
    assert isinstance(snapshot["osc.count"], int)
