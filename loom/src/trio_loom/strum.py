"""Headless string tuning and strum-crossing rules."""

from __future__ import annotations

import math


DEFAULT_TUNING = (40, 45, 50, 55, 59, 64, 69, 74)  # E2 A2 D3 G3 B3 E4 A4 D5


class StrumModel:
    """Map visible string rows to deterministic chord/default tuning pitches."""

    def __init__(self, string_count: int = 8) -> None:
        self.set_string_count(string_count)

    def set_string_count(self, string_count: int) -> None:
        if isinstance(string_count, bool) or not isinstance(string_count, int) or not 4 <= string_count <= 12:
            raise ValueError("string_count must be an integer from 4 through 12")
        self.string_count = string_count

    def pitches(self, mode: str = "direct", held: tuple[float, ...] = ()) -> tuple[int, ...]:
        if mode not in {"direct", "chord"}:
            raise ValueError("mode must be direct or chord")
        if mode == "chord" and held:
            valid_values: set[int] = set()
            for pitch in held:
                try:
                    value = float(pitch)
                except (TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(value) and 0 <= value <= 127:
                    valid_values.add(int(round(value)))
            valid = sorted(valid_values)
            if valid:
                classes = sorted({pitch % 12 for pitch in valid})
                base = valid[0]
                result = [base]
                for _ in range(1, self.string_count):
                    candidates: list[int] = []
                    for pitch_class in classes:
                        candidate = base + ((pitch_class - base) % 12)
                        while candidate <= result[-1]:
                            candidate += 12
                        candidates.append(candidate)
                    candidate = min(candidates)
                    result.append(candidate)
                return tuple(result)
        if self.string_count <= len(DEFAULT_TUNING):
            return DEFAULT_TUNING[: self.string_count]
        return DEFAULT_TUNING + tuple(DEFAULT_TUNING[-1] + 5 * index for index in range(1, self.string_count - len(DEFAULT_TUNING) + 1))

    @staticmethod
    def crossing_velocity(rows_per_second: float) -> float:
        speed = float(rows_per_second)
        if not math.isfinite(speed):
            raise ValueError("rows_per_second must be finite")
        return min(1.0, max(0.25, 0.25 + max(0.0, speed) / 40.0))

    @staticmethod
    def ordered_crossings(string_count: int, direction: int = 1) -> tuple[int, ...]:
        if isinstance(string_count, bool) or not isinstance(string_count, int) or string_count < 1:
            raise ValueError("string_count must be positive")
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or 1")
        values = tuple(range(string_count))
        return values if direction == 1 else tuple(reversed(values))


__all__ = ["DEFAULT_TUNING", "StrumModel"]
