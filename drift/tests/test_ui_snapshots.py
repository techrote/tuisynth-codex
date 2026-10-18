from __future__ import annotations

import os
from pathlib import Path

import pytest

from trio_drift.ui import drift_spec
from trio_kit.shell import Shell


_SIZES = ((100, 30), (80, 24))
_SKINS = ("mono", "desert-haze", "monsoon", "squall")
_SCREENS = ("map", "grain")


@pytest.mark.parametrize("skin", _SKINS)
@pytest.mark.parametrize("size", _SIZES)
@pytest.mark.parametrize("screen", _SCREENS)
def test_drift_weather_map_and_drawer_golden_snapshots(
    skin: str,
    size: tuple[int, int],
    screen: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    width, height = size
    shell = Shell(
        drift_spec(clock=lambda: 0.0),
        no_audio=True,
        start_midi=False,
        skin_id=skin,
        mono=skin == "mono",
        data_dir=tmp_path / f"{skin}-{width}x{height}-{screen}",
        seed=19,
    )
    try:
        actual = shell.snapshot(width, height, screen=screen)
    finally:
        shell.shutdown()

    snapshot_dir = Path(__file__).parent / "snapshots"
    snapshot_path = snapshot_dir / f"{screen}_{skin}_{width}x{height}.txt"
    if os.environ.get("TRIO_UPDATE_SNAPSHOTS") == "1":
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(actual + "\n", encoding="utf-8")
    assert snapshot_path.is_file(), f"missing golden snapshot {snapshot_path.name}; run tools/check.py --package drift --update-snapshots"
    expected = snapshot_path.read_text(encoding="utf-8").rstrip("\n")
    assert actual == expected
