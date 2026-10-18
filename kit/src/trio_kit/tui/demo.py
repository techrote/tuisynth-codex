"""Small deterministic widget layout used for documentation and snapshots."""

from __future__ import annotations

from trio_kit.params import ParamSpec
from trio_kit.tui.canvas import Canvas, Rect
from trio_kit.tui.widgets import (
    Button,
    Choice,
    Fader,
    FocusRing,
    Knob,
    ListBox,
    Meter,
    Tabs,
    TextField,
    Toggle,
    XYPad,
)


def widget_demo(width: int = 100, height: int = 30, *, monochrome: bool = False) -> tuple[Canvas, FocusRing]:
    """Build a frozen frame and all ten controls at the requested dimensions."""
    if width < 80 or height < 24:
        canvas = Canvas(width, height, role="background", ascii_only=monochrome)
        canvas.box(0, 0, width, height, style="ascii", role="border")
        canvas.text_center(height // 2, "Enlarge terminal to 80x24", x=1, width=max(0, width - 2), role="warning")
        return canvas, FocusRing()

    canvas = Canvas(width, height, role="background", ascii_only=monochrome)
    canvas.box(0, 0, width, height, style="ascii" if monochrome else "square", role="border")
    canvas.text(2, 0, "TRIO / TUI WIDGET DEMO", "title", max_width=width - 4)
    canvas.text(width - 19, 0, "100x30" if width >= 100 else "80x24", "muted", max_width=17)
    canvas.text(2, height - 1, "Tab focus  Arrows adjust  Delete resets  Ctrl+Q quits", "muted", max_width=width - 4)

    amp = ParamSpec("amp.level", "Level", "", 0.0, 1.0, 0.65)
    cutoff = ParamSpec("filter.cutoff", "Cutoff", "Hz", 20.0, 20000.0, 1200.0, curve="log")
    wave = ParamSpec("osc.wave", "Wave", "", 0.0, 3.0, 1.0, kind="choice", choices=("Sine", "Triangle", "Saw", "Square"))
    enabled = ParamSpec("fx.enabled", "Enabled", "", 0.0, 1.0, 0.0, kind="discrete")
    pan = ParamSpec("mix.pan", "Pan", "", -1.0, 1.0, 0.0)
    depth = ParamSpec("mod.depth", "Depth", "", 0.0, 1.0, 0.5)

    compact = width < 100 or height < 30
    if compact:
        ring = FocusRing(
            [
                Tabs("tabs", Rect(2, 2, width - 4, 1), ("Voice", "Mod", "FX"), selected=0),
                Fader("level", Rect(2, 5, 22, 3), amp, 0.65),
                Knob("cutoff", Rect(27, 5, 13, 4), cutoff, 1200.0),
                Toggle("enabled", Rect(43, 5, 15, 1), enabled),
                Choice("wave", Rect(60, 5, width - 62, 1), wave),
                XYPad("xy", Rect(2, 10, 19, 11), pan, depth, 0.0, 0.5, label="XY"),
                Meter("meter", Rect(25, 10, 16, 3), 0.72, label="Output", peak=0.9, right_value=0.54, right_peak=0.85),
                Button("apply", Rect(45, 10, 16, 1), "Apply", lambda: None),
                TextField("name", Rect(25, 15, width - 28, 1), "Glass Tide", label="Preset", default="Init"),
                ListBox("presets", Rect(45, 18, width - 48, 4), ("Init", "Glass Tide", "Long Echo"), selected=1, label="Library"),
            ]
        )
    else:
        ring = FocusRing(
            [
                Tabs("tabs", Rect(3, 2, width - 6, 1), ("Voice", "Modulation", "Effects"), selected=0),
                Fader("level", Rect(4, 5, 26, 3), amp, 0.65),
                Knob("cutoff", Rect(34, 5, 19, 4), cutoff, 1200.0),
                Toggle("enabled", Rect(58, 5, 17, 1), enabled),
                Choice("wave", Rect(77, 5, 20, 1), wave),
                XYPad("xy", Rect(4, 10, 24, 10), pan, depth, 0.0, 0.5, label="XY / MOD"),
                Meter("meter", Rect(33, 10, 24, 3), 0.72, label="Output", peak=0.9, right_value=0.54, right_peak=0.85),
                Button("apply", Rect(65, 10, 20, 1), "Apply", lambda: None),
                TextField("name", Rect(33, 16, 45, 1), "Glass Tide", label="Preset", default="Init"),
                ListBox("presets", Rect(65, 18, 30, 7), ("Init", "Glass Tide", "Long Echo", "Night Air"), selected=1, label="Library"),
            ]
        )
    return canvas, ring
