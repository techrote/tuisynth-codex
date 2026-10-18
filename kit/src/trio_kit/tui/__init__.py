"""Shared cell-based terminal UI primitives and reusable controls."""

from trio_kit.tui.app import CanvasApp, UIEvent
from trio_kit.tui.canvas import Canvas, Cell, HitMap, HitRegion, Rect
from trio_kit.tui.mouse import MouseInput, MouseRouter
from trio_kit.tui.widgets import (
    Button,
    Choice,
    Fader,
    FocusRing,
    Knob,
    ListBox,
    Meter,
    ParamWidget,
    Tabs,
    TextField,
    Toggle,
    Widget,
    XYPad,
)

__all__ = [
    "Button",
    "Canvas",
    "CanvasApp",
    "Cell",
    "Choice",
    "Fader",
    "FocusRing",
    "HitMap",
    "HitRegion",
    "Knob",
    "ListBox",
    "Meter",
    "MouseInput",
    "MouseRouter",
    "ParamWidget",
    "Rect",
    "Tabs",
    "TextField",
    "Toggle",
    "UIEvent",
    "Widget",
    "XYPad",
]
