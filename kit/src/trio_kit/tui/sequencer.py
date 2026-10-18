"""A shared step editor with three instrument-specific ASCII/Unicode motifs."""

from __future__ import annotations

import math
from dataclasses import replace

from trio_kit.seq import ARP_RATES, ArpeggiatorConfig, Pattern, SequenceConfig, Step
from trio_kit.tui.canvas import Canvas, Rect
from trio_kit.tui.mouse import MouseInput
from trio_kit.tui.widgets import Widget


class SequencerWidget(Widget):
    """Mouse/keyboard step editor; drawing motif is selected by the instrument UI."""

    def __init__(self, shell, bounds: Rect, style: str) -> None:
        if style not in {"spectral", "thread", "pressure"}:
            raise ValueError("sequencer style must be spectral, thread or pressure")
        super().__init__(f"sequencer-{style}", bounds, label="Step sequencer")
        self.shell = shell
        self.style = style
        self.visible = False
        self.selected_lane = 0
        self.selected_step = 0
        self._drag: tuple[int, int] | None = None
        self._cell_centres: tuple[tuple[int, int, int, int], ...] = ()

    @property
    def config(self) -> SequenceConfig:
        return SequenceConfig.from_dict(self.shell._known_extras.get("sequencer", {}))

    def _publish(self, config: SequenceConfig) -> bool:
        extras = dict(self.shell._known_extras)
        extras["sequencer"] = config.to_dict()
        return self.shell.set_extras(extras)

    def _set_step(self, lane: int, index: int, **changes: object) -> bool:
        config = self.config
        step = config.pattern.step(lane, index)
        replacement = Step(
            on=changes.get("on", step.on),
            note=changes.get("note", step.note),
            velocity=changes.get("velocity", step.velocity),
            gate=changes.get("gate", step.gate),
            probability=changes.get("probability", step.probability),
        )
        pattern = config.pattern.with_step(lane, index, replacement)
        if pattern == config.pattern:
            return False
        return self._publish(SequenceConfig(pattern, config.tempo, config.swing, config.playing, config.arpeggiator))

    def _set_config(self, **changes: object) -> bool:
        config = self.config
        return self._publish(SequenceConfig(
            changes.get("pattern", config.pattern),
            changes.get("tempo", config.tempo),
            changes.get("swing", config.swing),
            changes.get("playing", config.playing),
            changes.get("arpeggiator", config.arpeggiator),
        ))

    def _positions(self, config: SequenceConfig) -> tuple[tuple[int, int, int, int], ...]:
        """Return lane, step, x, y for each interactive point."""
        bounds = self.bounds
        cells: list[tuple[int, int, int, int]] = []
        if self.style == "pressure":
            cx = bounds.x + bounds.width // 2
            cy = bounds.y + max(2, bounds.height // 2)
            rx = max(2, (bounds.width - 8) // 2)
            ry = max(1, (bounds.height - 3) // 2)
            for lane in range(len(config.pattern.lanes)):
                lane_y = cy + round((lane - (len(config.pattern.lanes) - 1) / 2) * 0.5)
                for index in range(config.pattern.length):
                    angle = -math.pi / 2 + 2 * math.pi * index / config.pattern.length
                    x = cx + round(rx * math.cos(angle))
                    y = lane_y + round(ry * math.sin(angle))
                    cells.append((lane, index, x, y))
            return tuple(cells)
        label_width = 4
        usable = max(1, bounds.width - label_width - 1)
        row_height = max(1, (bounds.height - 2) // len(config.pattern.lanes))
        for lane in range(len(config.pattern.lanes)):
            y = bounds.y + 2 + lane * row_height + max(0, (row_height - 1) // 2)
            for index in range(config.pattern.length):
                x = bounds.x + label_width + round(index * max(0, usable - 1) / max(1, config.pattern.length - 1))
                cells.append((lane, index, x, y))
        return tuple(cells)

    def _locate(self, x: int, y: int) -> tuple[int, int] | None:
        if not self._cell_centres:
            self._cell_centres = self._positions(self.config)
        candidates = [cell for cell in self._cell_centres if abs(cell[2] - x) <= 1 and abs(cell[3] - y) <= 1]
        if not candidates:
            return None
        lane, index, _cx, _cy = min(candidates, key=lambda cell: abs(cell[2] - x) + abs(cell[3] - y))
        return lane, index

    def _toggle(self, lane: int, index: int) -> bool:
        step = self.config.pattern.step(lane, index)
        self.selected_lane, self.selected_step = lane, index
        return self._set_step(lane, index, on=not step.on)

    def handle_key(self, key: str, data: str = "") -> bool:
        command = data.casefold() if key == "any" and len(data) == 1 else key.casefold()
        config = self.config
        if command == "left":
            self.selected_step = (self.selected_step - 1) % config.pattern.length
        elif command == "right":
            self.selected_step = (self.selected_step + 1) % config.pattern.length
        elif command == "up":
            self.selected_lane = (self.selected_lane - 1) % len(config.pattern.lanes)
        elif command == "down":
            self.selected_lane = (self.selected_lane + 1) % len(config.pattern.lanes)
        elif command == "enter":
            return self._toggle(self.selected_lane, self.selected_step)
        elif command == "pageup":
            step = config.pattern.step(self.selected_lane, self.selected_step)
            return self._set_step(self.selected_lane, self.selected_step, velocity=min(1.0, step.velocity + 0.05))
        elif command == "pagedown":
            step = config.pattern.step(self.selected_lane, self.selected_step)
            return self._set_step(self.selected_lane, self.selected_step, velocity=max(0.0, step.velocity - 0.05))
        elif command == "space":
            return self._set_config(playing=not config.playing)
        elif command in {"[", "-"}:
            return self._set_config(tempo=max(40.0, config.tempo - 1.0))
        elif command in {"]", "="}:
            return self._set_config(tempo=min(240.0, config.tempo + 1.0))
        elif command == ",":
            return self._set_config(swing=max(0.0, config.swing - 0.02))
        elif command == ".":
            return self._set_config(swing=min(0.6, config.swing + 0.02))
        elif command == "a":
            return self._set_config(arpeggiator=replace(config.arpeggiator, enabled=not config.arpeggiator.enabled))
        elif command == "m":
            modes = ("up", "down", "updown", "random", "as-played")
            index = modes.index(config.arpeggiator.mode)
            return self._set_config(arpeggiator=replace(config.arpeggiator, mode=modes[(index + 1) % len(modes)]))
        elif command == "o":
            octaves = config.arpeggiator.octaves % 4 + 1
            return self._set_config(arpeggiator=replace(config.arpeggiator, octaves=octaves))
        elif command == "r":
            index = ARP_RATES.index(config.arpeggiator.rate)
            return self._set_config(arpeggiator=replace(config.arpeggiator, rate=ARP_RATES[(index + 1) % len(ARP_RATES)]))
        elif command == "l":
            return self._set_config(arpeggiator=replace(config.arpeggiator, latch=not config.arpeggiator.latch))
        else:
            return False
        self.shell.invalidate()
        return True

    def handle_mouse(self, event: MouseInput) -> bool:
        if event.kind == "wheel_up":
            return self._set_config(tempo=min(240.0, self.config.tempo + 1.0))
        if event.kind == "wheel_down":
            return self._set_config(tempo=max(40.0, self.config.tempo - 1.0))
        target = self._locate(event.x, event.y)
        if event.kind == "up":
            self._drag = None
            return True
        if event.kind == "right" and target is not None:
            lane, index = target
            step = self.config.pattern.step(lane, index)
            choices = (0.25, 0.5, 0.75, 1.0)
            next_probability = next((value for value in choices if value > step.probability + 1e-9), choices[0])
            return self._set_step(lane, index, probability=next_probability)
        if event.kind == "down" and event.button == "left" and target is not None:
            lane, index = target
            self._drag = lane, index
            return self._toggle(lane, index)
        if event.kind == "move" and self._drag is not None and event.button == "left":
            lane, index = self._drag
            fraction = 1.0 - (event.y - self.bounds.y) / max(1, self.bounds.height - 1)
            return self._set_step(lane, index, velocity=min(1.0, max(0.0, fraction)))
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        config = self.config
        self._cell_centres = self._positions(config)
        bounds = self.bounds
        heading_role = "focused" if focused else "heading" if hovered else "accent"
        state = "PLAY" if config.playing else "STOP"
        arp = config.arpeggiator
        arp_label = f"ARP {'ON' if arp.enabled else 'OFF'} {arp.mode}/{arp.rate} x{arp.octaves} L{'1' if arp.latch else '0'}"
        canvas.text(bounds.x, bounds.y, f"SEQ {config.tempo:.0f} BPM · SW {config.swing:.2f} · {state} · {config.pattern.length} steps · {arp_label}", heading_role, max_width=bounds.width)
        selected_role = "selected" if focused else "focused"
        lane_cell = {(lane, index): (x, y) for lane, index, x, y in self._cell_centres}
        if self.style == "spectral":
            for lane, steps in enumerate(config.pattern.lanes):
                y = bounds.y + 2 + lane * max(1, (bounds.height - 2) // len(config.pattern.lanes))
                canvas.text(bounds.x, y, f"{lane + 1:02d}", "muted", max_width=3)
                for index, step in enumerate(steps):
                    x, _ = lane_cell[lane, index]
                    height = max(1, round(step.velocity * max(1, (bounds.height - 3) // max(1, len(config.pattern.lanes)))))
                    glyph = "█" if step.on and not canvas.ascii_only else "#" if step.on else "·" if not canvas.ascii_only else "."
                    role = selected_role if (lane, index) == (self.selected_lane, self.selected_step) else "accent" if step.on else "muted"
                    canvas.put(x, y, glyph, role)
                    if step.on and height > 1:
                        canvas.put(x, max(bounds.y + 1, y - 1), glyph, role)
        elif self.style == "thread":
            for lane, steps in enumerate(config.pattern.lanes):
                y = bounds.y + 2 + lane * max(1, (bounds.height - 2) // len(config.pattern.lanes))
                canvas.text(bounds.x, y, f"{lane + 1:02d}", "muted", max_width=3)
                glyph_line = "-" if canvas.ascii_only else "─"
                for index, step in enumerate(steps):
                    x, _ = lane_cell[lane, index]
                    glyph = ("o" if canvas.ascii_only else "●") if step.on else glyph_line
                    role = selected_role if (lane, index) == (self.selected_lane, self.selected_step) else "accent" if step.on else "muted"
                    canvas.put(x, y, glyph, role)
                    if step.probability < 1.0 and step.on and y + 1 < bounds.bottom:
                        canvas.put(x, y + 1, str(round(step.probability * 4)), "warning")
        else:
            pressure = " .:-=+*#@"
            for lane, index, x, y in self._cell_centres:
                step = config.pattern.step(lane, index)
                selected = (lane, index) == (self.selected_lane, self.selected_step)
                if step.on:
                    glyph = "#" if canvas.ascii_only else pressure[min(len(pressure) - 1, 1 + round(step.velocity * (len(pressure) - 2)))]
                else:
                    glyph = "." if canvas.ascii_only else "·"
                role = selected_role if selected else "accent" if step.on else "muted"
                canvas.put(x, y, glyph, role)
                if step.probability < 1.0 and step.on and y + 1 < bounds.bottom:
                    canvas.put(x, y + 1, str(round(step.probability * 4)), "warning")
        hint = "Arrows step/lane · Enter toggle · PgUp/Dn velocity · Space transport · A/M/O/R/L arp"
        if bounds.height > 1:
            canvas.text(bounds.x, bounds.bottom - 1, hint, "muted", max_width=bounds.width)


__all__ = ["SequencerWidget"]
