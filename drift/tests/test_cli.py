from __future__ import annotations

import sys

import pytest

from trio_drift.cli import main


def test_version_flag_prints_installed_version(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["drift", "--version"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == "drift 0.1.0"


def test_list_presets_prints_all_factory_ids(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["drift", "--list-presets"])

    assert main() == 0
    listed = {line.split("\t", maxsplit=1)[0] for line in capsys.readouterr().out.splitlines()}
    assert listed == {
        "squall-choir", "desert-flute", "monsoon-breath", "howling-pass",
        "whisper-field", "vowel-sweep", "glass-wind", "deep-exhale",
    }
