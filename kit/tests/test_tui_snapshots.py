import os
from pathlib import Path

import pytest

from trio_kit.tui.demo import widget_demo


SNAPSHOTS = Path(__file__).parent / "snapshots"


@pytest.mark.parametrize(
    ("filename", "width", "height", "monochrome"),
    [
        ("widget-demo-100x30.txt", 100, 30, False),
        ("widget-demo-80x24-mono.txt", 80, 24, True),
    ],
)
def test_widget_demo_golden_snapshot(filename: str, width: int, height: int, monochrome: bool) -> None:
    canvas, widgets = widget_demo(width, height, monochrome=monochrome)
    widgets.draw(canvas)
    actual = canvas.snapshot()
    path = SNAPSHOTS / filename

    if os.environ.get("TRIO_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8", newline="\n")
    assert path.exists(), f"missing snapshot {filename}; run tools/check.py --package kit --update-snapshots"
    assert path.read_text(encoding="utf-8").rstrip("\n") == actual
    lines = actual.splitlines()
    assert len(lines) == height
    assert {len(line) for line in lines} == {width}
