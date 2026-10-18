from __future__ import annotations

import contextlib
import io
import sys
import wave

import pytest

from trio_aurora.cli import main
from trio_aurora.instrument import aurora_spec
from trio_kit.cli import run_cli


def test_version_flag_prints_installed_version(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["aurora", "--version"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == "aurora 0.1.0"


def test_shared_cli_lists_factory_presets_and_renders_without_devices(tmp_path) -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert run_cli(aurora_spec(), argv=["--list-presets"], command="aurora") == 0
    assert "glacier-choir\tGlacier Choir" in output.getvalue()
    assert "stretch-bells\tStretch Bells" in output.getvalue()

    target = tmp_path / "aurora.wav"
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert run_cli(
            aurora_spec(),
            argv=["--render", str(target), "--seconds", "0.1", "--preset", "cathedral-air"],
            command="aurora",
        ) == 0
    with wave.open(str(target), "rb") as rendered:
        assert rendered.getnchannels() == 2
        assert rendered.getsampwidth() == 2
        assert rendered.getframerate() == 48_000
        assert rendered.getnframes() == 4_800
        assert any(rendered.readframes(rendered.getnframes()))
