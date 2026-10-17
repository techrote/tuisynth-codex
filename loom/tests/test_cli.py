from __future__ import annotations

import sys

import pytest

from trio_loom.cli import main


def test_version_flag_prints_installed_version(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["loom", "--version"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == "loom 0.1.0"
