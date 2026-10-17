from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("trio_check", ROOT / "tools" / "check.py")
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def test_package_selection_returns_one_package_or_all_in_order() -> None:
    assert CHECK.selected_packages("aurora") == ("aurora",)
    assert CHECK.selected_packages("all") == ("kit", "aurora", "loom", "drift")
    assert CHECK.wheel_packages(("aurora",)) == ("kit", "aurora")
    assert CHECK.wheel_packages(("kit",)) == ("kit",)


def test_subprocess_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CHECK.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=7))

    with pytest.raises(CHECK.CheckFailed, match="exit code 7"):
        CHECK.run_process(["python", "-m", "pytest"], label="tests")


def test_main_runs_only_the_selected_package(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []
    monkeypatch.setattr(CHECK, "run_tests", lambda packages, *, update_snapshots: calls.append((tuple(packages), update_snapshots)))

    assert CHECK.main(["--package", "loom"]) == 0
    assert calls == [(('loom',), False)]


def test_main_returns_nonzero_when_a_qualification_step_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise CHECK.CheckFailed("simulated failure")

    monkeypatch.setattr(CHECK, "run_tests", fail)

    assert CHECK.main(["--package", "kit"]) == 1


def test_update_snapshots_sets_the_test_environment_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, str] | None] = []
    monkeypatch.setattr(
        CHECK,
        "run_process",
        lambda command, **kwargs: calls.append(kwargs.get("env")),
    )

    CHECK.run_tests(("kit",), update_snapshots=True)
    assert calls[0] is not None
    assert calls[0]["TRIO_UPDATE_SNAPSHOTS"] == "1"
