"""Cell-based drawing surface and last-frame hit map."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from wcwidth import wcwidth


def _dimension(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class Rect:
    """A half-open rectangle in zero-based terminal cell coordinates."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("x", "y"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        for name in ("width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def intersect(self, other: Rect) -> Rect:
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        return Rect(left, top, max(0, right - left), max(0, bottom - top))


@dataclass(frozen=True, slots=True)
class Cell:
    """One printable cell and its semantic style role."""

    char: str = " "
    role: str = "text"


@dataclass(frozen=True, slots=True)
class HitRegion:
    """A rectangular target. Later regions take precedence over earlier ones."""

    rect: Rect
    tag: str
    payload: object | None = None


class HitMap:
    """Topmost-wins hit testing in zero-based cell coordinates."""

    def __init__(self, width: int, height: int) -> None:
        self.width = _dimension(width, "width")
        self.height = _dimension(height, "height")
        self._regions: list[HitRegion] = []
        self._bounds = Rect(0, 0, width, height)

    @property
    def regions(self) -> tuple[HitRegion, ...]:
        return tuple(self._regions)

    def add(self, rect: Rect, tag: str, payload: object | None = None) -> HitRegion | None:
        if not isinstance(rect, Rect):
            raise TypeError("rect must be a Rect")
        if not isinstance(tag, str) or not tag:
            raise ValueError("tag must be a non-empty string")
        clipped = rect.intersect(self._bounds)
        if clipped.width == 0 or clipped.height == 0:
            return None
        region = HitRegion(clipped, tag, payload)
        self._regions.append(region)
        return region

    def at(self, x: int, y: int) -> HitRegion | None:
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
            return None
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        for region in reversed(self._regions):
            if region.rect.contains(x, y):
                return region
        return None


_FRAMES: dict[str, tuple[str, str, str, str, str, str]] = {
    "round": ("╭", "╮", "╰", "╯", "─", "│"),
    "square": ("┌", "┐", "└", "┘", "─", "│"),
    "heavy": ("┏", "┓", "┗", "┛", "━", "┃"),
    "double": ("╔", "╗", "╚", "╝", "═", "║"),
    "ascii": ("+", "+", "+", "+", "-", "|"),
}


class Canvas:
    """A clipped character grid with semantic roles and a frame-local hit map.

    Canvas positions are zero-based. Its rectangles are half-open. `put`
    rejects non-single-cell glyphs; `text` substitutes `?` to keep following
    text aligned to one source character per cell.
    """

    def __init__(self, width: int, height: int, *, role: str = "text", ascii_only: bool = False) -> None:
        self.width = _dimension(width, "width")
        self.height = _dimension(height, "height")
        if not isinstance(ascii_only, bool):
            raise ValueError("ascii_only must be a boolean")
        self.ascii_only = ascii_only
        self.cells = [[Cell(role=role) for _ in range(width)] for _ in range(height)]
        self.hit_map = HitMap(width, height)
        self._bounds = Rect(0, 0, width, height)
        self._clips: list[Rect] = [self._bounds]

    @property
    def clip_rect(self) -> Rect:
        return self._clips[-1]

    @contextmanager
    def clipped(self, x: int | Rect, y: int | None = None, width: int | None = None, height: int | None = None) -> Iterator[Canvas]:
        """Temporarily intersect drawing and hit registration with a clip rect."""
        if isinstance(x, Rect):
            rect = x
        else:
            if y is None or width is None or height is None:
                raise TypeError("clipped requires x, y, width and height")
            rect = Rect(x, y, width, height)
        self._clips.append(self.clip_rect.intersect(rect))
        try:
            yield self
        finally:
            self._clips.pop()

    def clear(self, role: str = "text", char: str = " ") -> None:
        safe = self._safe_char(char)
        if safe is None:
            raise ValueError("clear character must occupy exactly one terminal cell")
        for y in range(self.height):
            for x in range(self.width):
                self.cells[y][x] = Cell(safe, role)
        self.hit_map = HitMap(self.width, self.height)
        self._clips = [self._bounds]

    def _safe_char(self, char: object) -> str | None:
        if not isinstance(char, str) or len(char) != 1:
            return None
        if not char.isprintable() or wcwidth(char) != 1 or (self.ascii_only and ord(char) > 0x7F):
            return None
        return char

    def put(self, x: int, y: int, char: str, role: str = "text") -> bool:
        """Draw one printable width-one character; return False when clipped or unsafe."""
        safe = self._safe_char(char)
        if safe is None or not self.clip_rect.contains(x, y):
            return False
        self.cells[y][x] = Cell(safe, role)
        return True

    def text(self, x: int, y: int, value: object, role: str = "text", *, max_width: int | None = None) -> int:
        """Draw text, replacing non-cell-safe characters with `?`; return cells visited."""
        if not isinstance(value, str):
            value = str(value)
        if max_width is not None:
            if isinstance(max_width, bool) or not isinstance(max_width, int) or max_width < 0:
                raise ValueError("max_width must be a non-negative integer")
        start_x = x
        line_x = x
        line_y = y
        visited = 0
        for char in value:
            if char == "\n":
                line_x = start_x
                line_y += 1
                visited = 0
                continue
            if max_width is not None and visited >= max_width:
                break
            safe = self._safe_char(char)
            self.put(line_x, line_y, safe if safe is not None else "?", role)
            line_x += 1
            visited += 1
        return visited

    def fill(self, x: int, y: int, width: int, height: int, char: str = " ", role: str = "text") -> None:
        safe = self._safe_char(char)
        if safe is None:
            raise ValueError("fill character must occupy exactly one terminal cell")
        rect = Rect(x, y, width, height).intersect(self.clip_rect)
        for row in range(rect.y, rect.bottom):
            for column in range(rect.x, rect.right):
                self.cells[row][column] = Cell(safe, role)

    def hline(self, x: int, y: int, width: int, char: str = "─", role: str = "border") -> None:
        if width < 0:
            raise ValueError("width must be non-negative")
        for column in range(width):
            self.put(x + column, y, char, role)

    def vline(self, x: int, y: int, height: int, char: str = "│", role: str = "border") -> None:
        if height < 0:
            raise ValueError("height must be non-negative")
        for row in range(height):
            self.put(x, y + row, char, role)

    def box(self, x: int, y: int, width: int, height: int, *, style: str = "round", role: str = "border") -> None:
        if width < 0 or height < 0:
            raise ValueError("box dimensions must be non-negative")
        if width == 0 or height == 0:
            return
        try:
            tl, tr, bl, br, horizontal, vertical = _FRAMES[style]
        except KeyError as error:
            raise ValueError(f"unknown box style: {style}") from error
        if self.ascii_only:
            tl, tr, bl, br, horizontal, vertical = _FRAMES["ascii"]
        if width == 1:
            self.vline(x, y, height, vertical, role)
            return
        if height == 1:
            self.hline(x, y, width, horizontal, role)
            return
        self.put(x, y, tl, role)
        self.put(x + width - 1, y, tr, role)
        self.put(x, y + height - 1, bl, role)
        self.put(x + width - 1, y + height - 1, br, role)
        self.hline(x + 1, y, width - 2, horizontal, role)
        self.hline(x + 1, y + height - 1, width - 2, horizontal, role)
        self.vline(x, y + 1, height - 2, vertical, role)
        self.vline(x + width - 1, y + 1, height - 2, vertical, role)

    def text_center(self, y: int, value: object, *, x: int = 0, width: int | None = None, role: str = "text") -> None:
        if not isinstance(value, str):
            value = str(value)
        width = self.width - x if width is None else width
        if width < 0:
            raise ValueError("width must be non-negative")
        safe = "".join(char if self._safe_char(char) is not None else "?" for char in value)
        if len(safe) > width:
            safe = safe[:width]
        self.text(x + (width - len(safe)) // 2, y, safe, role)

    def blit_art(self, x: int, y: int, art: str | tuple[str, ...] | list[str], *, role: str = "text") -> None:
        """Draw clipped multiline art while replacing unsafe glyphs with `?`."""
        lines = art.splitlines() if isinstance(art, str) else art
        for row, line in enumerate(lines):
            self.text(x, y + row, line, role)

    def hit(self, x: int, y: int, width: int, height: int, tag: str, payload: object | None = None) -> HitRegion | None:
        """Register a clipped half-open hit rectangle in draw order."""
        rect = Rect(x, y, width, height).intersect(self.clip_rect)
        return self.hit_map.add(rect, tag, payload)

    def snapshot(self) -> str:
        """Return the complete plain-text frame, preserving terminal width."""
        return "\n".join("".join(cell.char for cell in row) for row in self.cells)

    plain_text = snapshot
