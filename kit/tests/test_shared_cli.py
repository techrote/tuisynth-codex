from __future__ import annotations

import contextlib
import io
import wave
from dataclasses import replace

import pytest

from trio_kit.cli import parse_note_name, run_cli
from trio_kit.demo import demo_spec


def test_note_name_parser_handles_accidentals_and_rejects_out_of_range() -> None:
    assert parse_note_name("C4") == 60
    assert parse_note_name("F#3") == 54
    assert parse_note_name("Bb2") == 46

    try:
        parse_note_name("C10")
    except ValueError as error:
        assert "MIDI range" in str(error)
    else:
        raise AssertionError("out-of-range note was accepted")


def test_shared_cli_lists_presets_writes_pcm16_stereo_wav_and_snapshots_without_devices(tmp_path) -> None:
    spec = demo_spec()
    with pytest.raises(SystemExit) as version:
        run_cli(spec, argv=["--version"], command="demo", version="0.1.0")
    assert version.value.code == 0

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert run_cli(spec, argv=["--list-presets", "--data-dir", str(tmp_path)], command="demo") == 0
    assert "init\tInit" in stdout.getvalue()
    assert "soft-glass\tSoft Glass" in stdout.getvalue()

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert run_cli(spec, argv=["--list-skins", "--data-dir", str(tmp_path)], command="demo") == 0
    assert "mono" in stdout.getvalue()

    wav_path = tmp_path / "render" / "triad.wav"
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert run_cli(
            spec,
            argv=["--render", str(wav_path), "--notes", "C4,E4,G4", "--seconds", "0.1", "--preset", "soft-glass", "--data-dir", str(tmp_path)],
            command="demo",
        ) == 0
    with wave.open(str(wav_path), "rb") as rendered:
        assert rendered.getnchannels() == 2
        assert rendered.getsampwidth() == 2
        assert rendered.getframerate() == 48_000
        assert rendered.getnframes() == 4_800
        assert any(rendered.readframes(rendered.getnframes()))

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert run_cli(spec, argv=["--snapshot", "100x30", "--screen", "help", "--data-dir", str(tmp_path)], command="demo") == 0
    frame = stdout.getvalue().rstrip("\n")
    assert len(frame.splitlines()) == 30
    assert "TRIO DEMO" in frame and "Command" not in frame and "F1 help" in frame


def test_shared_cli_selftest_success_and_fixture_failure(tmp_path) -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert run_cli(demo_spec(), argv=["--selftest", "--data-dir", str(tmp_path)], command="demo") == 0
    assert "2 presets" in output.getvalue()
    assert "1 skins" in output.getvalue()

    broken_dir = tmp_path / "broken-factory-presets"
    broken_dir.mkdir()
    (broken_dir / "bad.json").write_text("{ not valid json", encoding="utf-8")
    broken = replace(demo_spec(), factory_presets_dir=broken_dir)
    error = io.StringIO()
    with contextlib.redirect_stderr(error):
        assert run_cli(broken, argv=["--selftest", "--data-dir", str(tmp_path)], command="demo") == 1
    assert "invalid preset JSON" in error.getvalue()
