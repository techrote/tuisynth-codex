"""Shared instrument shell: lifecycle, commands, overlays and persistent state."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trio_kit.engine import Engine, open_backend
from trio_kit.events import ControlChange, Event, NoteOff, NoteOn, Panic, ParamSet, PresetApply
from trio_kit.input import CcLearnMap, KeyboardPiano, MidiInput
from trio_kit.params import ParamRegistry
from trio_kit.preset import Preset, PresetError, PresetLibrary, validate_preset_id
from trio_kit.skins import SkinLibrary
from trio_kit.tui import Canvas, CanvasApp, FocusRing, PianoWidget, Rect
from trio_kit.tui.widgets import ParamWidget, TextField, Widget


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Instrument-specific identity and drawing hooks consumed by the shared shell."""

    identifier: str
    name: str
    instrument_factory: Callable[[], object]
    registry: ParamRegistry | None = None
    draw: Callable[[Canvas, Shell], object] | None = None
    widgets: Callable[[Shell, int, int], Iterable[Widget]] | None = None
    on_screen: Callable[[str, Shell], object] | None = None
    factory_package: str | None = None
    factory_presets_dir: str | Path | None = None
    factory_skins_dir: str | Path | None = None
    legato_glide: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", self.identifier):
            raise ValueError("instrument identifier must be a lowercase id")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("instrument name must be a non-empty string")
        if not callable(self.instrument_factory):
            raise ValueError("instrument_factory must be callable")
        if self.registry is not None and not isinstance(self.registry, ParamRegistry):
            raise ValueError("registry must be a ParamRegistry or None")
        if self.draw is not None and not callable(self.draw):
            raise ValueError("draw must be callable or None")
        if self.widgets is not None and not callable(self.widgets):
            raise ValueError("widgets must be callable or None")
        if self.on_screen is not None and not callable(self.on_screen):
            raise ValueError("on_screen must be callable or None")
        if not isinstance(self.legato_glide, bool):
            raise ValueError("legato_glide must be a boolean")


class _OverlayLayer(Widget):
    """Draw modal content after regular widgets and route its keys before them."""

    def __init__(self, shell: Shell, bounds: Rect) -> None:
        super().__init__("__overlay__", bounds, label="Overlay", focusable=False)
        self.shell = shell

    def draw(self, canvas: Canvas, *, focused: bool = False, hovered: bool = False) -> None:
        del focused, hovered
        if self.shell.overlay is None:
            return
        canvas.hit(self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height, self.tag, self)
        self.shell._draw_overlay(canvas)

    def handle_key(self, key: str, data: str = "") -> bool:
        return self.shell.handle_key(key, data) if self.shell.overlay is not None else False

    def handle_mouse(self, event: Any) -> bool:
        return self.shell.overlay is not None


class Shell:
    """Compose an instrument engine with terminal input, presets, skins and overlays."""

    def __init__(
        self,
        spec: InstrumentSpec,
        *,
        engine: Engine | None = None,
        backend: Any | None = None,
        midi: Any | None = None,
        cc_learn: CcLearnMap | None = None,
        no_audio: bool = False,
        device: int | str | None = None,
        sample_rate: int = 48_000,
        skin_id: str | None = None,
        mono: bool = False,
        data_dir: str | Path | None = None,
        midi_selection: int | str | None = None,
        midi_channel: int | None = None,
        start_midi: bool = True,
    ) -> None:
        if not isinstance(spec, InstrumentSpec):
            raise TypeError("spec must be an InstrumentSpec")
        self.spec = spec
        self.engine = engine or Engine(spec.instrument_factory(), sample_rate=sample_rate, registry=spec.registry)
        if spec.registry is not None and self.engine.registry.specs != spec.registry.specs:
            raise ValueError("engine registry must match InstrumentSpec.registry")
        self.registry = self.engine.registry
        self.backend = backend if backend is not None else open_backend(self.engine, no_audio=no_audio, device=device)
        self.cc_learn = cc_learn or CcLearnMap.for_instrument(spec.identifier, data_dir=data_dir)
        self.midi = midi if midi is not None else MidiInput(
            self._on_midi_event,
            selection=midi_selection,
            channel=None if midi_channel in (None, 0) else midi_channel,
            cc_learn=self.cc_learn,
        )
        self._start_midi = start_midi
        self.skins = SkinLibrary.for_instrument(
            spec.identifier,
            data_dir=data_dir,
            factory_dir=spec.factory_skins_dir,
            skin_id=skin_id,
            mono=mono,
        )
        self.presets = PresetLibrary(
            spec.identifier,
            self.registry,
            data_dir=data_dir,
            factory_package=spec.factory_package,
            factory_dir=spec.factory_presets_dir,
        )
        self.keyboard = KeyboardPiano()
        self._known_params = dict(self.engine.param_snapshot)
        self._midi_sounding: dict[int, int] = {}
        self._history: list[tuple[str, int | float, int | float]] = []
        self._redo: list[tuple[str, int | float, int | float]] = []
        self._loaded_params = dict(self._known_params)
        self.current_preset: Preset | None = None
        self.current_screen = "main"
        self.status_message: str | None = None
        self.overlay: str | None = None
        self.overlay_index = 0
        self.overlay_query = ""
        self.overlay_input = ""
        self.overlay_message: str | None = None
        self._skin_before_overlay: str | None = None
        self._selected_midi = 0
        self._preset_selection = 0
        self._rename_source: str | None = None
        self._focused_control: str | None = None
        self._focus_before_overlay: str | None = None
        self._widget_size: tuple[int, int] | None = None
        self.widgets = FocusRing()
        self.piano = PianoWidget("piano", Rect(2, 16, 42, 7), self._on_piano_event, legato_glide=spec.legato_glide)
        self.widgets.add(self.piano)
        self._overlay_layer = _OverlayLayer(self, Rect(0, 0, 80, 24))
        self.widgets.add(self._overlay_layer)
        self.app: CanvasApp | None = None
        self._closed = False
        self._worker_stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._lock = threading.RLock()

    @property
    def modified(self) -> bool:
        return self._known_params != self._loaded_params

    @property
    def midi_status(self) -> str:
        return str(getattr(self.midi, "status", "MIDI: unavailable"))

    @property
    def midi_ports(self) -> tuple[str, ...]:
        return tuple(getattr(self.midi, "ports", getattr(self.midi, "available_ports", ())))

    def _push(self, event: Event) -> bool:
        try:
            result = bool(self.engine.push(event))
        except Exception as error:
            self.status_message = f"Event rejected: {error}"
            result = False
        if result:
            self.invalidate()
        else:
            self.status_message = "Event queue is full; change was not applied"
            self.invalidate()
        return result

    def _on_piano_event(self, event: Event) -> None:
        self._push(event)

    def _refresh_sounding(self) -> None:
        if hasattr(self, "piano"):
            self.piano.set_sounding((*self._midi_sounding.values(), *self.keyboard.active_pitches))

    def _on_midi_event(self, event: Event) -> None:
        if isinstance(event, NoteOn) and event.source == "midi":
            self._midi_sounding[event.note_id] = int(round(event.pitch))
        elif isinstance(event, NoteOff):
            self._midi_sounding.pop(event.note_id, None)
        elif isinstance(event, Panic):
            self._midi_sounding.clear()
        self._refresh_sounding()
        if isinstance(event, ControlChange):
            for key, cc in self.cc_learn.bindings.items():
                if cc == event.cc and key in self.registry.specs:
                    spec = self.registry[key]
                    self.set_param(key, spec.from_unit(event.value / 127.0))
        self._push(event)

    def set_param(self, key: str, value: object, *, record_history: bool = True) -> bool:
        validated = self.registry.validate_value(key, value)
        previous = self._known_params[key]
        if validated == previous:
            return False
        if not self._push(ParamSet(key, validated)):
            return False
        self._known_params[key] = validated
        if record_history:
            self._history.append((key, previous, validated))
            del self._history[:-50]
            self._redo.clear()
        self._sync_widgets()
        return True

    def undo(self) -> bool:
        if not self._history:
            return False
        key, before, after = self._history.pop()
        self._redo.append((key, before, after))
        return self.set_param(key, before, record_history=False)

    def redo(self) -> bool:
        if not self._redo:
            return False
        key, before, after = self._redo.pop()
        changed = self.set_param(key, after, record_history=False)
        if changed:
            self._history.append((key, before, after))
            del self._history[:-50]
        return changed

    def _sync_widgets(self) -> None:
        for widget in self.widgets.widgets:
            if isinstance(widget, ParamWidget) and widget.spec.key in self._known_params:
                widget.value = self._known_params[widget.spec.key]

    def load_preset(self, preset_id: str) -> Preset:
        preset = self.presets.get(preset_id)
        complete = self.registry.validate(preset.params)
        if not self._push(PresetApply(complete, preset.extras)):
            raise PresetError("preset could not be queued for application")
        self._known_params = complete
        self._loaded_params = dict(complete)
        self.engine_preset_name = preset.name
        self.current_preset = preset
        self._history.clear()
        self._redo.clear()
        self._sync_widgets()
        return preset

    @property
    def engine_preset_name(self) -> str:
        return getattr(self, "_engine_preset_name", "Init")

    @engine_preset_name.setter
    def engine_preset_name(self, value: str) -> None:
        self._engine_preset_name = value

    @staticmethod
    def _slug(value: str) -> str:
        candidate = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
        return validate_preset_id(candidate or "preset")

    def save_preset(self, name: str, *, preset_id: str | None = None, overwrite: bool = False) -> Preset:
        label = name.strip()
        if not label:
            raise PresetError("preset name must not be empty")
        preset = Preset(
            self.spec.identifier,
            self._slug(preset_id or label),
            label,
            self._known_params,
            self.engine.get_extras(),
        )
        self.presets.save(preset, overwrite=overwrite)
        self.current_preset = preset
        self.engine_preset_name = preset.name
        self._loaded_params = dict(self._known_params)
        return preset

    def rename_preset(self, preset_id: str, name: str) -> Preset:
        label = name.strip()
        if not label:
            raise PresetError("preset name must not be empty")
        renamed = self.presets.rename(preset_id, self._slug(label), name=label)
        if self.current_preset is not None and self.current_preset.id == preset_id:
            self.current_preset = renamed
            self.engine_preset_name = renamed.name
        return renamed

    def delete_preset(self, preset_id: str) -> None:
        self.presets.delete(preset_id)
        if self.current_preset is not None and self.current_preset.id == preset_id:
            self.current_preset = None
            self.engine_preset_name = "Init"

    def panic(self) -> None:
        for event in self.keyboard.release_all():
            self._push(event)
        self.piano.release_all()
        self._midi_sounding.clear()
        self._refresh_sounding()
        self._push(Panic())

    def _ensure_widgets(self, width: int, height: int) -> None:
        size = (width, height)
        if self._widget_size == size:
            return
        previous_focus = self.widgets.focused_tag
        previous_octave = self.piano.octave
        previous_cursor = self.piano._cursor
        previous_latches = self.piano.latched_pitches
        if self._widget_size is not None:
            self.piano.release_all()
        entries: list[Widget] = []
        usable_layout = width >= 80 and height >= 24
        if usable_layout and self.spec.widgets is not None:
            entries.extend(self.spec.widgets(self, width, height))
        piano_y = max(4, height - 10)
        piano_height = min(7, height - piano_y - 3)
        if usable_layout and width >= 44 and piano_height >= 3:
            self.piano = PianoWidget(
                "piano",
                Rect(2, piano_y, 42, piano_height),
                self._on_piano_event,
                legato_glide=self.spec.legato_glide,
            )
            self.piano._set_octave(previous_octave)
            self.piano._cursor = min(previous_cursor, self.piano.octaves * 12 - 1)
            self.piano._latches.update(previous_latches)
            entries.append(self.piano)
        self._overlay_layer = _OverlayLayer(self, Rect(0, 0, width, height))
        self._overlay_layer.focusable = self.overlay is not None
        entries.append(self._overlay_layer)
        self.widgets = FocusRing(entries)
        if previous_focus is not None:
            self.widgets.focus(previous_focus)
        self._widget_size = size
        self._sync_widgets()
        self._refresh_sounding()
        if self.app is not None:
            self.app.widgets = self.widgets

    def _draw(self, canvas: Canvas) -> None:
        canvas.box(0, 0, canvas.width, canvas.height, style="ascii" if canvas.ascii_only else "square", role="border")
        self._ensure_widgets(canvas.width, canvas.height)
        if canvas.width < 80 or canvas.height < 24:
            canvas.text_center(canvas.height // 2, "Enlarge terminal to 80x24", x=1, width=max(0, canvas.width - 2), role="warning")
            return
        if self.spec.draw is not None:
            self.spec.draw(canvas, self)
        telemetry = self.engine.telemetry()
        preset = self.engine_preset_name + ("*" if self.modified else "")
        header = f"{self.spec.name} | {preset} | skin {self.skins.current_id} | {self.midi_status}"
        canvas.text(2, 1, header, "title", max_width=canvas.width - 4)
        metrics = (
            f"voices {telemetry.active_voices}/{telemetry.max_voices}  CPU {telemetry.render_load * 100:.1f}%  "
            f"limiter {telemetry.limiter_gain:.2f}  octave {self.keyboard.octave:+d}  "
            f"velocity {self.keyboard.velocity:.2f}  latch {'on' if self.keyboard.latch else 'off'}"
        )
        canvas.text(2, 2, metrics, "muted", max_width=canvas.width - 4)
        footer = self._footer()
        canvas.text(2, canvas.height - 2, footer, "muted", max_width=canvas.width - 4)
        backend_error = getattr(self.backend, "last_error", None)
        if backend_error:
            canvas.text(2, 3, f"Audio fallback: {backend_error}", "warning", max_width=canvas.width - 4)
        elif telemetry.last_error:
            canvas.text(2, 3, f"Engine warning: {telemetry.last_error}", "warning", max_width=canvas.width - 4)
        if self.status_message:
            canvas.text(2, canvas.height - 3, self.status_message, "warning", max_width=canvas.width - 4)

    def _footer(self) -> str:
        if self.overlay == "presets":
            return "Enter load  S save  R rename  D delete  Esc close"
        if self.overlay == "skins":
            return "Up/Down preview  Enter keep  Esc restore"
        if self.overlay == "midi":
            return "Up/Down select port  Enter connect  Ctrl+L learn  Esc close"
        if self.overlay == "palette":
            return "Type to filter  Up/Down select  Enter run  Esc close"
        if self.overlay in {"save", "rename"}:
            return "Type a name  Enter save  Esc cancel"
        return "F1 help  F6 skin  F7 MIDI  F8 presets  F9 panic  Ctrl+P palette  Ctrl+Z/Y undo/redo  Ctrl+Q quit"

    def _overlay_rows(self) -> tuple[str, ...]:
        if self.overlay == "help":
            return (
                "F1 help   F2-F5 instrument screens   F6 / Shift+F6 skin",
                "F7 MIDI picker   F8 preset library   F9 panic",
                "Ctrl+L MIDI CC learn   Ctrl+P command palette",
                "Ctrl+Z undo   Ctrl+Y redo   Ctrl+Q quit",
                "Piano mouse: down plays; drag glides; right-click latches; wheel changes octave",
                "Piano focus: Left/Right cursor, Up/Down octave, Enter timed note",
                "Computer notes: z s x d c v g b h n j m  /  q 2 w 3 e r 5 t 6 y 7 u i 9 o 0 p",
                "- / = octave   [ / ] velocity   ' latch   F9 panic",
                "Preset library: Enter load, S save-as, R rename, D delete user preset",
                f"Current instrument screen: {self.current_screen.upper()} (F2-F5 are instrument-defined)",
            )
        if self.overlay == "palette":
            commands = self._filtered_commands()
            return tuple(("> " if index == self.overlay_index else "  ") + label for index, (_, label, _) in enumerate(commands)) or ("No matching commands",)
        if self.overlay == "skins":
            return tuple(("> " if skin_id == self.skins.current_id else "  ") + skin_id for skin_id in self.skins.ids)
        if self.overlay == "midi":
            ports = self.midi_ports
            if not ports:
                return (self.midi_status, "No MIDI port is required for keyboard or mouse play")
            return tuple(("> " if index == self._selected_midi else "  ") + name for index, name in enumerate(ports))
        if self.overlay == "presets":
            presets = self.presets.list_presets()
            if not presets:
                return ("No factory or user presets found", "Press S to save the current sound")
            return tuple(("> " if index == self._preset_selection else "  ") + f"{item.name} ({item.id})" for index, item in enumerate(presets))
        if self.overlay in {"save", "rename"}:
            prompt = "Save preset as" if self.overlay == "save" else "Rename preset to"
            return (prompt, self.overlay_input + "_", self.overlay_message or "")
        if self.overlay == "learn":
            control = self._focused_control or "no focused parameter"
            binding = self.cc_learn.lookup(control) if control in self.registry.specs else None
            return (f"Learning CC for {control}", "Move a hardware control to bind the next CC", f"Current binding: {binding if binding is not None else 'none'}")
        return ()

    def _draw_overlay(self, canvas: Canvas) -> None:
        if self.overlay is None:
            return
        rows = self._overlay_rows()
        width = min(canvas.width - 4, max(38, min(92, max((len(row) for row in rows), default=20) + 4)))
        height = min(canvas.height - 4, max(5, len(rows) + 4))
        x = max(1, (canvas.width - width) // 2)
        y = max(1, (canvas.height - height) // 2)
        title = {"help": "Help", "palette": "Command palette", "skins": "Select skin", "midi": "MIDI input", "presets": "Preset library", "save": "Save preset", "rename": "Rename preset", "learn": "MIDI CC learn"}.get(self.overlay, self.overlay)
        canvas.fill(x, y, width, height, " ", "background")
        canvas.box(x, y, width, height, style="ascii" if canvas.ascii_only else "round", role="accent")
        canvas.text(x + 2, y + 1, title, "title", max_width=width - 4)
        for index, row in enumerate(rows[: max(0, height - 4)]):
            role = "selected" if row.startswith(">") or self.overlay in {"learn", "save", "rename"} and index == 1 else "text"
            canvas.text(x + 2, y + 2 + index, row, role, max_width=width - 4)

    def _select_skin(self, skin_id: str) -> None:
        skin = self.skins.select(skin_id)
        if self.app is not None:
            self.app.skin = skin
            self.app.ascii_only = skin.id == "mono"
            if self.app.application is not None:
                self.app.application.style = self.app._prompt_style()
        self.invalidate()

    def _commands(self) -> tuple[tuple[str, str, Callable[[], object]], ...]:
        commands = [
            ("help", "Help", lambda: self.open_overlay("help")),
            ("skin", "Skin preview", lambda: self.open_overlay("skins")),
            ("skin-next", "Next skin", lambda: self._cycle_skin(1)),
            ("skin-prev", "Previous skin", lambda: self._cycle_skin(-1)),
            ("midi", "MIDI input picker", lambda: self.open_overlay("midi")),
            ("presets", "Preset library", lambda: self.open_overlay("presets")),
            ("save", "Save current sound as a preset", self._begin_save),
            ("panic", "Panic / release all notes", self.panic),
            ("undo", "Undo parameter change", self.undo),
            ("redo", "Redo parameter change", self.redo),
            ("learn", "MIDI CC learn for focused control", self.arm_cc_learn),
            ("quit", "Quit application", self.quit),
        ]
        if self.spec.on_screen is not None:
            commands.extend(
                (f"screen-{number}", f"Open instrument screen F{number}", lambda key=f"f{number}": self._open_screen(key))
                for number in range(2, 6)
            )
        return tuple(commands)

    def _cycle_skin(self, direction: int) -> None:
        self._select_skin(self.skins.cycle(direction).id)

    def _open_screen(self, key: str) -> None:
        self.current_screen = key
        if self.spec.on_screen is not None:
            self.spec.on_screen(key, self)
        self.status_message = f"{self.spec.name} screen {key.upper()}"
        self.invalidate()

    def _begin_save(self) -> None:
        self.open_overlay("presets")
        self.overlay = "save"
        self.overlay_input = self.engine_preset_name if self.current_preset is not None else ""
        self._overlay_layer.focusable = True
        self.widgets.focus(self._overlay_layer.tag)

    def quit(self) -> None:
        self.shutdown()
        if self.app is not None:
            self.app.quit()

    def _filtered_commands(self) -> tuple[tuple[str, str, Callable[[], object]], ...]:
        query = self.overlay_query.casefold().strip()
        commands = self._commands()
        if not query:
            return commands
        return tuple(command for command in commands if query in command[1].casefold() or all(char in command[1].casefold() for char in query))

    def open_overlay(self, name: str) -> None:
        if name not in {"help", "palette", "skins", "midi", "presets", "learn"}:
            raise ValueError(f"unsupported overlay: {name}")
        if self.overlay == "skins" and name != "skins" and self._skin_before_overlay is not None:
            self._select_skin(self._skin_before_overlay)
        if self.overlay is None:
            self._focus_before_overlay = self.widgets.focused_tag
        self.overlay = name
        self._overlay_layer.focusable = True
        self.widgets.focus(self._overlay_layer.tag)
        self.overlay_index = 0
        self.overlay_query = ""
        self.overlay_message = None
        self._skin_before_overlay = self.skins.current_id if name == "skins" else None
        if name == "midi":
            try:
                self.midi.poll()
            except Exception as error:
                self.status_message = f"MIDI unavailable: {error}"
            self._selected_midi = 0
        if name == "presets":
            self._preset_selection = 0
        self.invalidate()

    def close_overlay(self, *, restore_skin: bool = True) -> None:
        if self.overlay == "skins" and restore_skin and self._skin_before_overlay is not None:
            self._select_skin(self._skin_before_overlay)
        self.overlay = None
        self._skin_before_overlay = None
        self._overlay_layer.focusable = False
        if self._focus_before_overlay is not None:
            self.widgets.focus(self._focus_before_overlay)
        else:
            self.widgets.clear_focus()
        self._focus_before_overlay = None
        self.invalidate()

    def arm_cc_learn(self) -> bool:
        widget = self.widgets.focused
        control = widget.spec.key if isinstance(widget, ParamWidget) else next(iter(self.registry.specs), None)
        if control is None:
            self.status_message = "No parameter is available for MIDI learn"
            self.open_overlay("learn")
            return False
        self._focused_control = control
        self.cc_learn.arm(control)
        self.open_overlay("learn")
        self.status_message = f"Move a controller to bind CC to {control}"
        return True

    def _handle_overlay_key(self, key: str, data: str) -> bool:
        typed = data if len(data) == 1 and data.isprintable() else key if len(key) == 1 and key.isprintable() else ""
        if key == "escape":
            self.close_overlay()
            return True
        if self.overlay == "help":
            return True
        if self.overlay == "palette":
            commands = self._filtered_commands()
            if key == "up":
                self.overlay_index = max(0, self.overlay_index - 1)
            elif key == "down":
                self.overlay_index = min(max(0, len(commands) - 1), self.overlay_index + 1)
            elif key == "backspace":
                self.overlay_query = self.overlay_query[:-1]
                self.overlay_index = 0
            elif key == "enter":
                if commands:
                    action = commands[min(self.overlay_index, len(commands) - 1)][2]
                    self.close_overlay(restore_skin=False)
                    action()
            elif typed:
                self.overlay_query += typed
                self.overlay_index = 0
            self.invalidate()
            return True
        if self.overlay == "skins":
            if key in {"up", "down"} and self.skins.ids:
                index = self.skins.ids.index(self.skins.current_id)
                index = (index + (1 if key == "down" else -1)) % len(self.skins.ids)
                self._select_skin(self.skins.ids[index])
            elif key == "enter":
                self.close_overlay(restore_skin=False)
            self.invalidate()
            return True
        if self.overlay == "midi":
            ports = self.midi_ports
            if key == "up":
                self._selected_midi = max(0, self._selected_midi - 1)
            elif key == "down":
                self._selected_midi = min(max(0, len(ports) - 1), self._selected_midi + 1)
            elif key == "enter" and ports:
                self.midi.select_port(self._selected_midi)
                self.status_message = self.midi_status
                self.close_overlay(restore_skin=False)
            elif typed.casefold() == "l":
                self.arm_cc_learn()
            self.invalidate()
            return True
        if self.overlay == "presets":
            presets = self.presets.list_presets()
            if key == "up":
                self._preset_selection = max(0, self._preset_selection - 1)
            elif key == "down":
                self._preset_selection = min(max(0, len(presets) - 1), self._preset_selection + 1)
            elif key == "enter" and presets:
                try:
                    selected = presets[min(self._preset_selection, len(presets) - 1)]
                    self.load_preset(selected.id)
                    self.close_overlay(restore_skin=False)
                except Exception as error:
                    self.overlay_message = str(error)
            elif typed.casefold() in {"s", "r", "d"}:
                if typed.casefold() == "s":
                    self.overlay = "save"
                    self.overlay_input = ""
                elif not presets:
                    self.overlay_message = "No preset is selected"
                elif typed.casefold() == "r":
                    item = presets[min(self._preset_selection, len(presets) - 1)]
                    if item.id not in {preset.id for preset in self.presets._factory_presets().values()}:
                        self._rename_source = item.id
                        self.overlay = "rename"
                        self.overlay_input = item.name
                    else:
                        self.overlay_message = "Factory presets cannot be renamed"
                else:
                    item = presets[min(self._preset_selection, len(presets) - 1)]
                    try:
                        self.delete_preset(item.id)
                        self.overlay_message = f"Deleted {item.name}"
                    except Exception as error:
                        self.overlay_message = str(error)
            self.invalidate()
            return True
        if self.overlay in {"save", "rename"}:
            if key == "backspace":
                self.overlay_input = self.overlay_input[:-1]
            elif key == "enter":
                try:
                    if self.overlay == "save":
                        self.save_preset(self.overlay_input)
                    elif self._rename_source is not None:
                        self.rename_preset(self._rename_source, self.overlay_input)
                    self.close_overlay(restore_skin=False)
                    self.open_overlay("presets")
                except Exception as error:
                    self.overlay_message = str(error)
            elif typed:
                self.overlay_input += typed
            self.invalidate()
            return True
        if self.overlay == "learn":
            if key == "escape":
                self.cc_learn.disarm()
                self.close_overlay(restore_skin=False)
            return True
        return False

    def handle_key(self, key: str, data: str = "") -> bool:
        """Handle global commands; called after focused widgets receive a key."""
        if self.overlay is not None:
            return self._handle_overlay_key(key, data)
        if key == "f1":
            self.open_overlay("help")
            return True
        if key == "f6":
            self._select_skin(self.skins.cycle(1).id)
            return True
        if key in {"s-f6", "shift-f6"}:
            self._select_skin(self.skins.cycle(-1).id)
            return True
        if key == "f7":
            self.open_overlay("midi")
            return True
        if key == "f8":
            self.open_overlay("presets")
            return True
        if key == "f9":
            self.panic()
            return True
        if key == "c-p":
            self.open_overlay("palette")
            return True
        if key == "c-l":
            self.arm_cc_learn()
            return True
        if key == "c-z":
            self.undo()
            return True
        if key == "c-y":
            self.redo()
            return True
        if key == "escape":
            if self.widgets.focused is not None:
                self.widgets.clear_focus()
                return True
            return False
        if key.startswith("f") and key[1:].isdigit() and key in {"f2", "f3", "f4", "f5"}:
            if self.spec.on_screen is not None:
                self.current_screen = key.lower()
                self.spec.on_screen(self.current_screen, self)
                self.status_message = f"{self.spec.name} screen {key.upper()}"
                self.invalidate()
                return True
        focused = self.widgets.focused
        if isinstance(focused, TextField):
            return False
        note_key = data if key == "any" else key
        if self.keyboard.handles_key(note_key):
            events = self.keyboard.press(note_key)
            for event in events:
                self._push(event)
            self._refresh_sounding()
            return True
        return False

    def invalidate(self) -> None:
        if self.app is not None:
            self.app.invalidate()

    def build_app(self) -> CanvasApp:
        if self.app is None:
            self.app = CanvasApp(
                self._draw,
                widgets=self.widgets,
                skin=self.skins.current,
                quit_callback=self.shutdown,
                on_key=self.handle_key,
                animated=True,
            )
        return self.app

    def _tick(self) -> None:
        while not self._worker_stop.wait(0.02):
            now = time.monotonic()
            for event in self.keyboard.tick(now):
                self._push(event)
            self._refresh_sounding()
            if self.piano.tick(now):
                self.invalidate()

    def run(self) -> None:
        if self._closed:
            raise RuntimeError("shell is closed")
        if self._start_midi:
            try:
                self.midi.start()
            except Exception as error:
                self.status_message = f"MIDI unavailable: {error}"
        self._worker = threading.Thread(target=self._tick, name=f"trio-shell-{self.spec.identifier}", daemon=True)
        self._worker.start()
        try:
            start_backend = getattr(self.backend, "start", None)
            if callable(start_backend) and not getattr(self.backend, "running", False):
                start_backend()
            self.build_app().run()
        finally:
            self.shutdown()

    def snapshot(self, width: int = 100, height: int = 30, *, screen: str = "main") -> str:
        if screen not in {"main", "help", "palette", "skins", "midi", "presets"}:
            raise ValueError("unknown snapshot screen")
        if screen != "main":
            self.open_overlay(screen)
        from trio_kit.tui.testing import HeadlessApp

        with HeadlessApp(size=(width, height), app=self.build_app()) as driver:
            return driver.screen_text()

    def shutdown(self) -> None:
        """Release producers, stop audio, close MIDI, and leave terminal restoration to the app."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._worker_stop.set()
        failures: list[str] = []
        if self._worker is not None and self._worker is not threading.current_thread():
            try:
                self._worker.join()
            except Exception as error:
                failures.append(f"stop shell input: {error}")
        try:
            for event in self.keyboard.release_all():
                self.engine.push(event)
            self.piano.release_all()
            release = getattr(self.midi, "release_notes", None)
            if callable(release):
                release()
            self.engine.push(Panic())
        except Exception as error:
            failures.append(f"release notes: {error}")
        try:
            self.backend.close()
        except Exception as error:
            failures.append(f"stop audio: {error}")
        try:
            if not getattr(self.engine, "_closed", False):
                self.engine.close()
        except Exception as error:
            failures.append(f"close engine: {error}")
        try:
            self.midi.close()
        except Exception as error:
            failures.append(f"close MIDI: {error}")
        if failures:
            self.status_message = "; ".join(failures)[:256]


__all__ = ["InstrumentSpec", "Shell"]
