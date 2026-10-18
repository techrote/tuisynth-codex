from trio_kit.tui.canvas import HitMap, Rect
from trio_kit.tui.mouse import MouseInput, MouseRouter


def test_mouse_router_captures_until_release_even_outside_target() -> None:
    hit_map = HitMap(12, 5)
    hit_map.add(Rect(2, 1, 4, 2), "fader")
    router = MouseRouter()
    router.update(hit_map)
    seen: list[tuple[str, str, int, int]] = []

    def dispatch(target, event):
        seen.append((target.tag, event.kind, event.x, event.y))
        return True

    assert router.route(MouseInput(3, 1, "down", "left"), dispatch) is True
    assert router.captured_tag == "fader"
    assert router.route(MouseInput(10, 4, "move", "left"), dispatch) is True
    assert router.route(MouseInput(11, 4, "up", "left"), dispatch) is True
    assert router.captured_tag is None
    assert router.route(MouseInput(10, 4, "move"), dispatch) is None
    assert seen == [
        ("fader", "down", 3, 1),
        ("fader", "move", 10, 4),
        ("fader", "up", 11, 4),
    ]


def test_mouse_router_routes_hover_right_click_and_coarse_wheel() -> None:
    hit_map = HitMap(5, 3)
    hit_map.add(Rect(1, 1, 2, 1), "control")
    router = MouseRouter()
    router.update(hit_map)
    seen = []
    handler = lambda target, event: seen.append((target.tag, event.kind, event.steps))

    router.route(MouseInput(1, 1, "move"), handler)
    assert router.hovered_tag == "control"
    router.route(MouseInput(2, 1, "wheel_up", control=True), handler)
    router.route(MouseInput(2, 1, "right", "right"), handler)
    router.route(MouseInput(4, 0, "move"), handler)
    assert router.hovered_tag is None
    assert seen == [
        ("control", "move", 1),
        ("control", "wheel_up", 10),
        ("control", "right", 1),
    ]
