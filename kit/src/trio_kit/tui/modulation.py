"""Shared eight-slot modulation editor and ASCII effect pedalboard."""

from __future__ import annotations

from collections.abc import Mapping

from trio_kit.modulation import FX_RANGES, ModulationConfig, RACK_UNITS, SOURCES
from trio_kit.tui.canvas import Canvas, Rect
from trio_kit.tui.mouse import MouseInput
from trio_kit.tui.widgets import Widget


_SOURCE_LABELS = {
    "lfo1": "LFO1", "lfo2": "LFO2", "lfo3": "LFO3", "modenv": "ENV",
    "velocity": "VEL", "modwheel": "WHEEL", "keytrack": "KEY", "note-random": "RAND",
    "pitchbend": "BEND", "tremolo.lfo": "TREM", "phaser.lfo": "PHASE",
    "tape.wow": "WOW", "tape.flutter": "FLUT",
}
_UNIT_LABELS = {"tremolo": "TREM", "ring-mod": "RING", "phaser": "PHASE", "tape": "TAPE", "chorus": "CHORUS", "delay": "DELAY", "reverb": "REVERB"}


class ModulationWidget(Widget):
    """Mouse and keyboard editor bound to the shell's preset extras model."""

    def __init__(self, shell, bounds: Rect, style: str) -> None:
        if style not in {"spectral", "thread", "pressure"}:
            raise ValueError("modulation style must be spectral, thread or pressure")
        super().__init__(f"modulation-{style}", bounds, label="Modulation matrix and FX rack")
        self.shell = shell
        self.style = style
        self.visible = False
        self.selected_slot = 0
        self.selected_source = 0
        self.selected_unit = 0
        self.focus_area = "matrix"
        self._pedal_drag: int | None = None
        self._mix_drag: int | None = None
        self._grid: Rect | None = None
        self._pedals: tuple[Rect, ...] = ()
        self._details_y = 0
        self._cell_width = 1

    @property
    def config(self) -> ModulationConfig:
        raw = self.shell._known_extras.get("modulation", {})
        return ModulationConfig.from_dict(raw)

    @property
    def destinations(self) -> tuple[str, ...]:
        slot = self.config.slots[self.selected_slot]
        source = slot.source or SOURCES[self.selected_source]
        return self._destinations_for(source)

    def _source_is_voice(self, source: str) -> bool:
        if source in {"modenv", "velocity", "keytrack", "note-random"}:
            return True
        if source in {"lfo1", "lfo2", "lfo3"}:
            return self.config.lfos[int(source[-1]) - 1].mode == "voice"
        return False

    def _destinations_for(self, source: str) -> tuple[str, ...]:
        voice_source = self._source_is_voice(source)
        parameters = tuple(
            spec.key for spec in self.shell.registry
            if spec.modulatable and spec.kind == "continuous"
            and (not voice_source or spec.modulation_scope in {"voice", "both"})
        )
        return parameters if voice_source else parameters + tuple(FX_RANGES)

    def _publish(self, config: ModulationConfig) -> bool:
        extras = dict(self.shell._known_extras)
        extras["modulation"] = config.to_dict()
        changed = self.shell.set_extras(extras)
        if changed:
            self.shell.invalidate()
        return changed

    def _edit_slot(self, *, source: str | None = None, destination: str | None = None, amount: float | None = None, clear: bool = False) -> bool:
        config = self.config
        slots = [slot.to_dict() for slot in config.slots]
        if clear:
            slots[self.selected_slot] = {"source": None, "destination": None, "amount": 0.0}
        else:
            current = slots[self.selected_slot]
            if source is not None:
                current["source"] = source
                if current.get("destination") not in self._destinations_for(source):
                    current["destination"] = None
            if destination is not None:
                current["destination"] = destination
                if current.get("source") is None:
                    current["source"] = SOURCES[self.selected_source]
            if amount is not None:
                current["amount"] = min(1.0, max(-1.0, amount))
        data = config.to_dict()
        data["slots"] = slots
        return self._publish(ModulationConfig.from_dict(data))

    def _cycle_source(self, direction: int) -> bool:
        self.selected_source = (self.selected_source + direction) % len(SOURCES)
        return self._edit_slot(source=SOURCES[self.selected_source])

    def _cycle_destination(self, direction: int) -> bool:
        destinations = self.destinations
        if not destinations:
            return False
        current = self.config.slots[self.selected_slot].destination
        index = destinations.index(current) if current in destinations else -1
        return self._edit_slot(destination=destinations[(index + direction) % len(destinations)])

    def _adjust_amount(self, delta: float) -> bool:
        slot = self.config.slots[self.selected_slot]
        return self._edit_slot(amount=slot.amount + delta)

    def _toggle_bypass(self, index: int | None = None) -> bool:
        config = self.config
        chosen = self.selected_unit if index is None else index
        name = config.rack_order[chosen]
        data = config.to_dict()
        data["rack"]["units"][name]["bypass"] = not bool(config.rack_units[name]["bypass"])
        self.selected_unit = chosen
        self.focus_area = "rack"
        return self._publish(ModulationConfig.from_dict(data))

    def _set_unit_mix(self, index: int, mix: float) -> bool:
        config = self.config
        chosen = min(len(config.rack_order) - 1, max(0, index))
        name = config.rack_order[chosen]
        data = config.to_dict()
        data["rack"]["units"][name]["mix"] = min(1.0, max(0.0, mix))
        self.selected_unit = chosen
        self.focus_area = "rack"
        return self._publish(ModulationConfig.from_dict(data))

    def _adjust_unit_mix(self, delta: float) -> bool:
        config = self.config
        name = config.rack_order[self.selected_unit]
        return self._set_unit_mix(self.selected_unit, float(config.rack_units[name]["mix"]) + delta)

    def _move_unit(self, target: int) -> bool:
        config = self.config
        target = min(len(config.rack_order) - 1, max(0, target))
        if target == self.selected_unit:
            return False
        order = list(config.rack_order)
        unit = order.pop(self.selected_unit)
        order.insert(target, unit)
        data = config.to_dict()
        data["rack"]["order"] = order
        self.selected_unit = target
        self.focus_area = "rack"
        return self._publish(ModulationConfig.from_dict(data))

    def handle_key(self, key: str, data: str = "") -> bool:
        command = data.casefold() if key == "any" and len(data) == 1 else key.casefold()
        if command == "v":
            self.focus_area = "rack" if self.focus_area == "matrix" else "matrix"
            self.shell.invalidate()
            return True
        if self.focus_area == "rack" and command in {"left", "right"}:
            self.selected_unit = (self.selected_unit + (1 if command == "right" else -1)) % len(self.config.rack_order)
            self.shell.invalidate()
            return True
        if command == "left":
            self.selected_slot = (self.selected_slot - 1) % 8
        elif command == "right":
            self.selected_slot = (self.selected_slot + 1) % 8
        elif command == "up":
            return self._cycle_source(-1)
        elif command == "down":
            return self._cycle_source(1)
        elif command in {"r", "enter"}:
            return self._cycle_source(1)
        elif command == "t":
            return self._cycle_destination(1)
        elif command in {"+", "="}:
            return self._adjust_amount(0.05)
        elif command in {"-", "_"}:
            return self._adjust_amount(-0.05)
        elif command in {",", "<"}:
            return self._adjust_unit_mix(-0.05)
        elif command in {".", ">"}:
            return self._adjust_unit_mix(0.05)
        elif command == "pageup":
            return self._adjust_amount(0.1)
        elif command == "pagedown":
            return self._adjust_amount(-0.1)
        elif command in {"delete", "backspace"}:
            return self._edit_slot(clear=True)
        elif command == "b":
            return self._toggle_bypass()
        elif command == "[":
            return self._move_unit(self.selected_unit - 1)
        elif command == "]":
            return self._move_unit(self.selected_unit + 1)
        elif command in {"space", "enter-unit"}:
            return self._toggle_bypass()
        else:
            return False
        self.shell.invalidate()
        return True

    def handle_mouse(self, event: MouseInput) -> bool:
        grid = self._grid
        if event.kind == "wheel_up":
            for index, rect in enumerate(self._pedals):
                if rect.x <= event.x < rect.right and rect.y <= event.y < rect.bottom:
                    self.selected_unit = index
                    self.focus_area = "rack"
                    return self._adjust_unit_mix(0.05 * event.steps)
            return self._adjust_amount(0.05 * event.steps)
        if event.kind == "wheel_down":
            for index, rect in enumerate(self._pedals):
                if rect.x <= event.x < rect.right and rect.y <= event.y < rect.bottom:
                    self.selected_unit = index
                    self.focus_area = "rack"
                    return self._adjust_unit_mix(-0.05 * event.steps)
            return self._adjust_amount(-0.05 * event.steps)
        if event.kind == "up":
            self._pedal_drag = None
            self._mix_drag = None
            return True
        if grid is not None and grid.y <= event.y < grid.bottom and grid.x <= event.x < grid.right:
            self.focus_area = "matrix"
            slot = min(7, max(0, (event.x - grid.x) * 8 // max(1, grid.width)))
            row = event.y - grid.y
            if event.kind == "right":
                self.selected_slot = slot
                return self._edit_slot(clear=True)
            if event.kind == "down" and event.button == "left":
                self.selected_slot = slot
                source_row = min(len(SOURCES) - 1, max(0, row))
                self.selected_source = source_row
                return self._edit_slot(source=SOURCES[source_row])
            if event.kind == "move" and event.button == "left":
                self.selected_slot = slot
                fraction = min(1.0, max(0.0, (event.x - grid.x) / max(1, grid.width - 1)))
                return self._edit_slot(amount=2.0 * fraction - 1.0)
        details = self._details_y
        if self.bounds.x <= event.x < self.bounds.right and details <= event.y < details + 3:
            self.selected_slot = min(7, max(0, (event.x - self.bounds.x) // max(1, self._cell_width)))
            if event.kind == "right":
                return self._edit_slot(clear=True)
            if event.kind == "down" and event.button == "left" and event.y == details + 1:
                return self._cycle_destination(1)
            if ((event.kind == "down" and event.button == "left") or (event.kind == "move" and event.button == "left")) and event.y == details + 2:
                local = (event.x - self.bounds.x - self.selected_slot * self._cell_width) / max(1, self._cell_width - 1)
                return self._edit_slot(amount=2.0 * min(1.0, max(0.0, local)) - 1.0)
        if event.kind == "right":
            for index, rect in enumerate(self._pedals):
                if rect.x <= event.x < rect.right and rect.y <= event.y < rect.bottom:
                    self.focus_area = "rack"
                    return self._toggle_bypass(index)
        if event.kind == "down" and event.button == "left":
            for index, rect in enumerate(self._pedals):
                if rect.x <= event.x < rect.right and rect.y <= event.y < rect.bottom:
                    self.selected_unit = index
                    self.focus_area = "rack"
                    if rect.height >= 3 and event.y == rect.bottom - 1:
                        self._mix_drag = index
                        self._set_unit_mix(index, (event.x - rect.x) / max(1, rect.width - 1))
                    else:
                        self._pedal_drag = index
                    return True
        if event.kind == "move" and event.button == "left" and self._mix_drag is not None:
            rect = self._pedals[self._mix_drag]
            mix = min(1.0, max(0.0, (event.x - rect.x) / max(1, rect.width - 1)))
            return self._set_unit_mix(self._mix_drag, mix)
        if event.kind == "move" and event.button == "left" and self._pedal_drag is not None:
            for index, rect in enumerate(self._pedals):
                if rect.x <= event.x < rect.right and rect.y <= event.y < rect.bottom:
                    return self._move_unit(index)
        return False

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        super().draw(canvas, focused=focused, hovered=hovered)
        b = self.bounds
        config = self.config
        title_role = "focused" if focused else "accent" if hovered else "heading"
        canvas.text(b.x, b.y, f"MOD MATRIX · 8 ROUTES · {self.style.upper()}", title_role, max_width=b.width)
        grid_y = b.y + 1
        grid_h = max(1, min(len(SOURCES), b.height - 8))
        grid = Rect(b.x, grid_y, b.width, grid_h)
        self._grid = grid
        cell_w = max(1, grid.width // 8)
        row_names = SOURCES[:grid.height]
        # Source names form rows; the eight columns remain the independently selectable slots.
        for row, source in enumerate(row_names):
            short = _SOURCE_LABELS[source]
            y = grid.y + row
            canvas.text(grid.x, y, short, "muted", max_width=min(5, grid.width))
            for slot_index, slot in enumerate(config.slots):
                x = grid.x + grid.width // 8 * slot_index + min(5, cell_w - 1)
                if x >= grid.right:
                    continue
                active = slot.source == source and slot.destination is not None
                if self.style == "spectral":
                    glyph = "*" if active else "."
                elif self.style == "thread":
                    glyph = "o" if active else "-"
                else:
                    glyph = "#" if active else "."
                role = "selected" if slot_index == self.selected_slot else "accent" if active else "muted"
                canvas.put(x, y, glyph, role)
        details_y = grid.bottom
        self._details_y = details_y
        self._cell_width = cell_w
        for index, slot in enumerate(config.slots):
            x = b.x + cell_w * index
            selected = index == self.selected_slot
            source = "--" if slot.source is None else _SOURCE_LABELS.get(slot.source, slot.source[:4].upper())
            destination = "unpatched" if slot.destination is None else slot.destination
            destination = destination[-max(3, cell_w - 1):]
            amount = f"{slot.amount:+.2f}"
            role = "selected" if selected else "text"
            canvas.text(x, details_y, f"{index + 1:02d} {source}", role, max_width=cell_w)
            if details_y + 1 < b.bottom:
                canvas.text(x, details_y + 1, destination, "muted", max_width=cell_w)
            if details_y + 2 < b.bottom:
                canvas.text(x, details_y + 2, amount, "accent" if selected else "muted", max_width=cell_w)
        pedal_y = max(details_y + 3, b.bottom - 4)
        pedal_h = max(1, b.bottom - pedal_y - 1)
        gap = 1
        pedal_w = max(1, (b.width - gap * (len(config.rack_order) - 1)) // len(config.rack_order))
        pedals: list[Rect] = []
        for index, name in enumerate(config.rack_order):
            x = b.x + index * (pedal_w + gap)
            rect = Rect(x, pedal_y, min(pedal_w, max(1, b.right - x)), pedal_h)
            pedals.append(rect)
            settings = config.rack_units[name]
            bypass = bool(settings["bypass"])
            selected = index == self.selected_unit
            role = "selected" if selected else "muted" if bypass else "accent"
            canvas.text(rect.x, rect.y, "+" + "-" * max(0, rect.width - 2) + "+" if rect.width > 2 else "[]", role, max_width=rect.width)
            if rect.height > 1:
                label = _UNIT_LABELS[name] + (" BYP" if bypass else " ON")
                canvas.text(rect.x, rect.y + 1, label, role, max_width=rect.width)
            if rect.height > 2:
                mix = float(settings["mix"])
                canvas.text(rect.x, rect.bottom - 1, f"MIX {mix:.2f}", "muted", max_width=rect.width)
        self._pedals = tuple(pedals)
        if b.height > 1:
            canvas.text(b.x, b.bottom - 1, "V rack focus · rack arrows select unit · R source T target B/Space bypass Del clear [ ] order ,/. mix", "muted", max_width=b.width)


__all__ = ["ModulationWidget"]
