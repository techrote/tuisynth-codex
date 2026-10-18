from __future__ import annotations

import os
from pathlib import Path

import pytest

from trio_kit.demo import demo_spec
from trio_kit.shell import Shell


SNAPSHOTS = Path(__file__).parent / "snapshots"


@pytest.mark.parametrize(
    ("filename", "width", "height"),
    (("demo-100x30.txt", 100, 30), ("demo-80x24-mono.txt", 80, 24)),
)
def test_demo_shell_golden_snapshots(filename: str, width: int, height: int, tmp_path: Path) -> None:
    shell = Shell(demo_spec(), no_audio=True, data_dir=tmp_path, mono=True, skin_id="mono", start_midi=False)
    try:
        actual = shell.snapshot(width, height)
    finally:
        shell.shutdown()
    path = SNAPSHOTS / filename
    if os.environ.get("TRIO_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8", newline="\n")
    assert path.exists(), f"missing snapshot {filename}; run tools/check.py --package kit --update-snapshots"
    assert path.read_text(encoding="utf-8").rstrip("\n") == actual
    lines = actual.splitlines()
    assert len(lines) == height
    assert {len(line) for line in lines} == {width}
