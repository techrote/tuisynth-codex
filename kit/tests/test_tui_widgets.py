from pathlib import Path

import pytest

from trio_kit.params import ParamSpec
from trio_kit.tui.canvas import Canvas, Rect
from trio_kit.tui.mouse import MouseInput
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


def _spec(key: str, label: str, minimum: float = 0, maximum: float = 100, default: float = 50, **kwargs) -> ParamSpec:
    return ParamSpec(key, label, "", minimum, maximum, default, **kwargs)


def test_focus_ring_visits_all_controls_in_order_and_wraps() -> None:
    controls = [
        Fader("fader", Rect(0, 0, 8, 2), _spec("a.level", "Level")),
        Knob("knob", Rect(0, 0, 8, 3), _spec("a.cutoff", "Cutoff")),
        Toggle("toggle", Rect(0, 0, 8, 1), _spec("a.enabled", "Enabled", 0, 1, 0, kind="discrete")),
        Choice("choice", Rect(0, 0, 8, 1), _spec("a.wave", "Wave", 0, 2, 0, kind="choice", choices=("A", "B", "C"))),
        XYPad("xy", Rect(0, 0, 8, 4), _spec("a.x", "X"), _spec("a.y", "Y")),
        Meter("meter", Rect(0, 0, 8, 2)),
        Button("button", Rect(0, 0, 8, 1), "Go"),
        TextField("text", Rect(0, 0, 8, 1)),
        ListBox("list", Rect(0, 0, 8, 3), ("A", "B")),
        Tabs("tabs", Rect(0, 0, 8, 1), ("A", "B")),
    ]
    ring = FocusRing(controls)
    assert ring.focusables == tuple(controls)
    assert ring.focused is None
    assert ring.handle_key("s-tab") is True
    assert ring.focused_tag == "tabs"
    assert ring.handle_key("tab") is True
    assert ring.focused_tag == "fader"


def test_parameter_widgets_have_keyboard_twins_and_callbacks() -> None:
    events: list[tuple[str, int | float]] = []
    callback = lambda key, value: events.append((key, value))
    fader = Fader("fader", Rect(0, 0, 12, 3), _spec("amp.level", "Level"), on_change=callback)
    fader.handle_key("right")
    assert fader.value == 51
    fader.handle_key("home")
    assert fader.value == 0
    fader.handle_key("end")
    assert fader.value == 100
    fader.handle_key("delete")
    assert fader.value == 50

    knob = Knob("knob", Rect(0, 0, 9, 4), _spec("filter.cutoff", "Cutoff"), value=50)
    before = knob.unit
    knob.handle_key("up")
    assert knob.unit > before

    toggle = Toggle("toggle", Rect(0, 0, 12, 1), _spec("fx.enabled", "Enabled", 0, 1, 0, kind="discrete"), on_change=callback)
    toggle.handle_key("space")
    assert toggle.value == 1
    toggle.handle_key("delete")
    assert toggle.value == 0

    choices = _spec("osc.wave", "Wave", 0, 2, 2, kind="choice", choices=("Sine", "Saw", "Square"))
    choice = Choice("choice", Rect(0, 0, 12, 1), choices, on_change=callback)
    choice.handle_key("right")
    assert choice.value == 0
    choice.handle_key("left")
    assert choice.value == 2
    assert events == [("amp.level", 51), ("amp.level", 0), ("amp.level", 100), ("amp.level", 50), ("fx.enabled", 1), ("fx.enabled", 0), ("osc.wave", 0), ("osc.wave", 2)]


def test_xy_pad_axes_keyboard_and_mouse_mapping_are_monotonic() -> None:
    events: list[tuple[str, int | float]] = []
    xy = XYPad(
        "xy",
        Rect(2, 2, 9, 7),
        _spec("mix.pan", "Pan", -1, 1, 0),
        _spec("mod.depth", "Depth", 0, 1, 0.5),
        on_change=lambda key, value: events.append((key, value)),
    )
    start_y = xy.y_spec.to_unit(xy.y_value)
    xy.handle_key("up")
    assert xy.y_spec.to_unit(xy.y_value) > start_y
    xy.handle_key("right")
    assert xy.x_value > 0
    samples = []
    for x in (2, 4, 7, 10):
        xy.handle_mouse(MouseInput(x, 5, "down", "left"))
        samples.append(xy.x_spec.to_unit(xy.x_value))
    assert samples == sorted(samples)
    xy.handle_mouse(MouseInput(10, 5, "right", "right"))
    assert xy.x_value == 0 and xy.y_value == 0.5


def test_vertical_fader_and_seven_position_knob_follow_drag_direction() -> None:
    vertical = Fader("vertical", Rect(2, 2, 3, 8), _spec("filter.amount", "Amount"), orientation="vertical")
    vertical.handle_mouse(MouseInput(3, 2, "down", "left"))
    high = vertical.value
    vertical.handle_mouse(MouseInput(3, 9, "move", "left"))
    assert vertical.value < high

    stepped = _spec("filter.step", "Step", 0, 6, 3, kind="discrete")
    knob = Knob("knob", Rect(1, 1, 9, 7), stepped)
    knob.handle_mouse(MouseInput(5, 1, "down", "left"))
    assert knob.value == 6
    knob.handle_mouse(MouseInput(5, 7, "move", "left"))
    assert knob.value == 0

    canvas = Canvas(12, 5)
    knob = Knob("knob", Rect(1, 1, 9, 4), _spec("filter.level", "Level"))
    knob.draw(canvas)
    assert len(canvas.cells[2][2:9]) == 7
    assert all(cell.char.isascii() for cell in canvas.cells[2][2:9])


def test_action_text_list_tabs_and_meter_controls() -> None:
    actions: list[str] = []
    button = Button("button", Rect(0, 0, 10, 1), "Run", lambda: actions.append("run"))
    assert button.handle_key("enter") is True
    assert actions == ["run"]

    changed: list[object] = []
    text = TextField("text", Rect(0, 0, 20, 1), "Init", default="Init", on_change=lambda value: changed.append(value))
    text.handle_key("end")
    text.handle_key("any", " A")
    assert text.value == "Init A"
    text.handle_key("backspace")
    assert text.value == "Init "
    text.handle_key("delete")
    assert text.value == "Init"
    assert changed == ["Init A", "Init ", "Init"]

    listbox = ListBox("list", Rect(0, 0, 12, 4), ("Init", "Glass", "Echo"))
    listbox.handle_key("down")
    assert listbox.selected == 1
    listbox.handle_key("pageup")
    assert listbox.selected == 2
    listbox.handle_key("home")
    assert listbox.selected == 0

    tabs = Tabs("tabs", Rect(0, 0, 15, 1), ("Voice", "Mod", "FX"))
    tabs.handle_key("end")
    assert tabs.selected == 2
    tabs.handle_key("left")
    assert tabs.selected == 1

    meter = Meter("meter", Rect(0, 0, 12, 2), 1.4, peak=0.7)
    assert meter.value == 1.0
    meter.set_level(-1.0)
    assert meter.value == 0.0
    with pytest.raises(ValueError):
        meter.set_level(float("nan"))

    stereo = Meter("stereo", Rect(0, 0, 12, 3), 0.8, label="Output", peak=0.95, right_value=0.4, right_peak=0.7)
    canvas = Canvas(12, 3)
    stereo.draw(canvas)
    assert canvas.cells[1][0].char == "L"
    assert canvas.cells[2][0].char == "R"
    assert canvas.cells[1][2].role == "meter_high"
    assert canvas.cells[2][2].role == "meter_mid"


def test_widgets_draw_hit_regions_and_have_no_engine_or_dsp_imports() -> None:
    fader = Fader("fader", Rect(1, 1, 8, 3), _spec("amp.level", "Level"))
    button = Button("button", Rect(2, 2, 6, 1), "Go")
    canvas = Canvas(10, 5)
    FocusRing((fader, button)).draw(canvas)
    assert canvas.hit_map.at(1, 1).tag == "fader"
    assert canvas.hit_map.at(2, 2).tag == "button"
    assert canvas.hit_map.at(1, 2).tag == "fader"

    source = Path(__file__).parents[1] / "src" / "trio_kit" / "tui" / "widgets.py"
    implementation = source.read_text(encoding="utf-8")
    assert "trio_kit.engine" not in implementation
    assert "trio_kit.dsp" not in implementation
