from __future__ import annotations

from dataclasses import replace

from trio_kit.demo import demo_spec
from trio_kit.modulation import SOURCES
from trio_kit.shell import Shell
from trio_kit.tui.canvas import Canvas, Rect
from trio_kit.tui.modulation import ModulationWidget
from trio_kit.tui.mouse import MouseInput


def _mod_shell(tmp_path):
    holder: dict[str, ModulationWidget] = {}

    def widgets(shell, width: int, height: int):
        widget = ModulationWidget(shell, Rect(2, 3, width - 4, height - 3), "pressure")
        holder["widget"] = widget
        return (widget,)

    def on_screen(key: str, shell) -> None:
        widget = holder.get("widget")
        if widget is None:
            return
        if key == "s-f4":
            widget.visible = True
            shell.widgets.focus(widget.tag)
        elif key == "mod-return":
            widget.visible = False
            shell.current_screen = "main"

    spec = replace(demo_spec(), widgets=widgets, on_screen=on_screen)
    shell = Shell(spec, no_audio=True, data_dir=tmp_path, start_midi=False)
    shell._ensure_widgets(80, 24)
    return shell, holder


def test_modulation_screen_keyboard_actions_route_clear_reorder_and_bypass(tmp_path) -> None:
    shell, holder = _mod_shell(tmp_path)
    try:
        assert shell.handle_key("s-f4")
        widget = holder["widget"]
        assert widget.visible
        assert shell.widgets.focused_tag == widget.tag
        assert shell.widgets.handle_key("r")
        assert shell._known_extras["modulation"]["slots"][0]["source"] == "lfo2"
        assert shell.widgets.handle_key("t")
        assert shell.widgets.handle_key("+")
        slot = shell._known_extras["modulation"]["slots"][0]
        assert slot["destination"] == "fx.tremolo.depth"
        assert slot["amount"] > 0
        assert shell.widgets.handle_key(",")
        assert shell._known_extras["modulation"]["rack"]["units"]["tremolo"]["mix"] == 0.95
        assert shell.widgets.handle_key(".")
        assert shell._known_extras["modulation"]["rack"]["units"]["tremolo"]["mix"] == 1.0
        assert shell.widgets.handle_key("delete")
        assert shell._known_extras["modulation"]["slots"][0] == {"source": None, "destination": None, "amount": 0.0}

        assert shell.widgets.handle_key("]")
        assert shell._known_extras["modulation"]["rack"]["order"][0] == "ring-mod"
        assert shell.widgets.handle_key("b")
        assert shell._known_extras["modulation"]["rack"]["units"]["tremolo"]["bypass"] is False
        assert shell.handle_key("escape")
        assert shell.current_screen == "main"
        assert not widget.visible
    finally:
        shell.shutdown()


def test_keyboard_can_focus_and_edit_every_pedalboard_unit(tmp_path) -> None:
    shell, holder = _mod_shell(tmp_path)
    try:
        shell.handle_key("s-f4")
        widget = holder["widget"]
        assert shell.widgets.handle_key("v")
        assert widget.focus_area == "rack"
        for index in range(7):
            order = shell._known_extras["modulation"]["rack"]["order"]
            name = order[index]
            assert widget.selected_unit == index
            original_mix = shell._known_extras["modulation"]["rack"]["units"][name]["mix"]
            original_bypass = shell._known_extras["modulation"]["rack"]["units"][name]["bypass"]
            assert shell.widgets.handle_key(",")
            assert shell._known_extras["modulation"]["rack"]["units"][name]["mix"] == original_mix - 0.05
            assert shell.widgets.handle_key(".")
            assert shell._known_extras["modulation"]["rack"]["units"][name]["mix"] == original_mix
            assert shell.widgets.handle_key("b")
            assert shell._known_extras["modulation"]["rack"]["units"][name]["bypass"] is not original_bypass
            assert shell.widgets.handle_key("b")
            assert shell._known_extras["modulation"]["rack"]["units"][name]["bypass"] is original_bypass
            if index < 6:
                assert shell.widgets.handle_key("right")
        assert shell.widgets.handle_key("v")
        assert widget.focus_area == "matrix"
    finally:
        shell.shutdown()


def test_voice_sources_only_offer_destinations_consumed_per_voice(tmp_path) -> None:
    shell, holder = _mod_shell(tmp_path)
    try:
        shell.handle_key("s-f4")
        widget = holder["widget"]
        for _ in range(4):
            assert shell.widgets.handle_key("down")
        assert shell._known_extras["modulation"]["slots"][0]["source"] == "velocity"
        assert widget.destinations == ()
        assert not shell.widgets.handle_key("t")
        assert shell._known_extras["modulation"]["slots"][0]["destination"] is None
    finally:
        shell.shutdown()


def test_modulation_mouse_routes_destination_amount_clear_and_pedal_controls(tmp_path) -> None:
    shell, holder = _mod_shell(tmp_path)
    try:
        widget = holder["widget"]
        shell.handle_key("s-f4")
        widget.draw(Canvas(80, 24), focused=True)
        grid = widget._grid
        assert grid is not None
        slot_x = grid.x + grid.width // 8 + 1
        assert grid.height == len(SOURCES)
        widget.handle_mouse(MouseInput(slot_x, grid.y, "down", button="left"))
        assert shell._known_extras["modulation"]["slots"][1]["source"] == "lfo1"
        widget.handle_mouse(MouseInput(slot_x, grid.y + len(SOURCES) - 1, "down", button="left"))
        assert shell._known_extras["modulation"]["slots"][1]["source"] == SOURCES[-1]

        details_y = widget._details_y
        widget.handle_mouse(MouseInput(slot_x, details_y + 1, "down", button="left"))
        assert shell._known_extras["modulation"]["slots"][1]["destination"] == "fx.tremolo.depth"
        amount_x = widget.bounds.x + 2 * widget._cell_width - 1
        widget.handle_mouse(MouseInput(amount_x, details_y + 2, "down", button="left"))
        assert shell._known_extras["modulation"]["slots"][1]["amount"] > 0.5

        widget.handle_mouse(MouseInput(slot_x, grid.y, "right", button="right"))
        assert shell._known_extras["modulation"]["slots"][1]["source"] is None
        pedal = widget._pedals[0]
        widget.handle_mouse(MouseInput(pedal.x, pedal.bottom - 1, "down", button="left"))
        assert shell._known_extras["modulation"]["rack"]["units"]["tremolo"]["mix"] == 0.0
        widget.handle_mouse(MouseInput(pedal.right - 1, pedal.bottom - 1, "move", button="left"))
        assert shell._known_extras["modulation"]["rack"]["units"]["tremolo"]["mix"] == 1.0
        widget.handle_mouse(MouseInput(pedal.right - 1, pedal.bottom - 1, "up", button="left"))
        widget.handle_mouse(MouseInput(pedal.x, pedal.y, "wheel_down"))
        assert shell._known_extras["modulation"]["rack"]["units"]["tremolo"]["mix"] == 0.95
        widget.handle_mouse(MouseInput(pedal.x, pedal.y, "right", button="right"))
        assert shell._known_extras["modulation"]["rack"]["units"]["tremolo"]["bypass"] is False
        widget.handle_mouse(MouseInput(pedal.x, pedal.y, "down", button="left"))
        target = widget._pedals[1]
        widget.handle_mouse(MouseInput(target.x, target.y, "move", button="left"))
        widget.handle_mouse(MouseInput(target.x, target.y, "up", button="left"))
        assert shell._known_extras["modulation"]["rack"]["order"][1] == "tremolo"
    finally:
        shell.shutdown()


def test_three_modulation_styles_have_distinct_screens(tmp_path) -> None:
    shell, _holder = _mod_shell(tmp_path)
    try:
        extras = dict(shell._known_extras)
        modulation = dict(extras["modulation"])
        slots = [dict(slot) for slot in modulation["slots"]]
        slots[0] = {"source": "lfo1", "destination": "fx.tremolo.depth", "amount": 0.5}
        modulation["slots"] = slots
        extras["modulation"] = modulation
        shell.set_extras(extras)
        snapshots = []
        for style in ("spectral", "thread", "pressure"):
            canvas = Canvas(80, 24, ascii_only=True)
            widget = ModulationWidget(shell, Rect(2, 2, 76, 21), style)
            widget.draw(canvas, focused=True)
            snapshots.append(canvas.snapshot())
        assert all("MOD MATRIX" in snapshot for snapshot in snapshots)
        assert len(set(snapshots)) == 3
    finally:
        shell.shutdown()
