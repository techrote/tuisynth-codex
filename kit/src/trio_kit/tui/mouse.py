"""Cell-coordinate mouse events and capture-aware hit routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from trio_kit.tui.canvas import HitMap, HitRegion


@dataclass(frozen=True, slots=True)
class MouseInput:
    """A normalized event; x and y are always zero-based canvas cells."""

    x: int
    y: int
    kind: str
    button: str = "none"
    control: bool = False
    shift: bool = False
    alt: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.x, bool) or not isinstance(self.x, int):
            raise ValueError("x must be an integer cell coordinate")
        if isinstance(self.y, bool) or not isinstance(self.y, int):
            raise ValueError("y must be an integer cell coordinate")
        if self.kind not in {"down", "up", "move", "wheel_up", "wheel_down", "right"}:
            raise ValueError(f"unsupported mouse event kind: {self.kind}")
        if self.button not in {"none", "left", "middle", "right"}:
            raise ValueError(f"unsupported mouse button: {self.button}")

    @property
    def steps(self) -> int:
        """Wheel distance, with Ctrl providing the documented coarse step."""
        return 10 if self.control else 1


class MouseRouter:
    """Route events through the last frame's hit map, retaining drag capture."""

    def __init__(self) -> None:
        self.hit_map: HitMap | None = None
        self.capture: HitRegion | None = None
        self.hover: HitRegion | None = None

    @property
    def captured_tag(self) -> str | None:
        return self.capture.tag if self.capture is not None else None

    @property
    def hovered_tag(self) -> str | None:
        return self.hover.tag if self.hover is not None else None

    def update(self, hit_map: HitMap) -> None:
        """Replace the frame-local map; preserve capture until release."""
        self.hit_map = hit_map

    def target_at(self, x: int, y: int) -> HitRegion | None:
        return self.hit_map.at(x, y) if self.hit_map is not None else None

    def route(self, event: MouseInput, handler: Callable[[HitRegion, MouseInput], object]) -> object | None:
        """Dispatch one event to its captured or topmost hit target."""
        hit = self.target_at(event.x, event.y)
        if event.kind == "move":
            self.hover = hit

        if event.kind == "down" and event.button == "left" and hit is not None:
            self.capture = hit

        target = self.capture if self.capture is not None else hit
        if event.kind == "right":
            target = hit
        result = handler(target, event) if target is not None else None

        if event.kind == "up":
            self.capture = None
        return result
