from __future__ import annotations

from dataclasses import replace

from trio_kit.demo import SineInstrument, demo_spec
from trio_kit.engine import Engine, EngineTelemetry, SoundDeviceBackend
from trio_kit.events import ControlChange, NoteOff, NoteOn, Panic
from trio_kit.params import ParamSnapshot
from trio_kit.shell import InstrumentSpec, Shell
from trio_kit.input import CcLearnMap
from trio_kit.input import FakeMidiBackend, MidiInput
from trio_kit.tui.testing import HeadlessApp


def test_shell_commands_parameter_undo_redo_preset_boundary_and_note_routing(tmp_path) -> None:
    shell = Shell(demo_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    try:
        shell._ensure_widgets(100, 30)
        assert shell.set_param("amp.level", 0.4)
        assert shell.undo()
        assert shell.redo()
        assert shell._known_params["amp.level"] == 0.4
        assert shell.engine.render(256).shape == (256, 2)
        assert shell.engine.param_snapshot["amp.level"] == 0.4

        assert shell.handle_key("c-z")
        assert shell._known_params["amp.level"] == 0.65
        assert shell.handle_key("c-y")
        assert shell._known_params["amp.level"] == 0.4
        shell.handle_key("any", "z")
        assert shell.engine.event_queue.drain()

        shell.handle_key("f1")
        assert shell.overlay == "help"
        shell.handle_key("escape")
        assert shell.overlay is None
        shell.handle_key("c-p")
        assert shell.overlay == "palette"
        for character in "preset":
            shell.handle_key("any", character)
        shell.handle_key("enter")
        assert shell.overlay == "presets"
        shell.handle_key("escape")

        loaded = shell.load_preset("soft-glass")
        assert loaded.name == "Soft Glass"
        assert shell.engine.render(256).shape == (256, 2)
        assert shell.engine.param_snapshot["amp.level"] == 0.42
    finally:
        shell.shutdown()


def test_shell_shutdown_releases_notes_before_audio_and_closes_midi_after_audio(tmp_path) -> None:
    log: list[object] = []
    spec = demo_spec()
    registry = spec.registry

    class FakeEngine:
        def __init__(self) -> None:
            self.registry = registry
            self.param_snapshot = ParamSnapshot(registry.defaults())
            self._closed = False

        def push(self, event):
            log.append(event)
            return True

        def get_extras(self):
            return {}

        def telemetry(self):
            return EngineTelemetry(48_000, 256, 0, 16, 0, 0, 0, 0, 0, 0, 1.0, 0.0, 0.0, 0, "test", None)

        def close(self):
            log.append("engine.close")
            self._closed = True

    class FakeBackend:
        def close(self):
            log.append("backend.close")

    class FakeMidi:
        status = "MIDI: fake"
        ports = ("Fake",)

        def release_notes(self):
            log.append("midi.release")
            return ()

        def close(self):
            log.append("midi.close")

    class FakeWorker:
        def join(self):
            log.append("worker.join")

    shell = Shell(
        spec, engine=FakeEngine(), backend=FakeBackend(), midi=FakeMidi(),
        cc_learn=CcLearnMap(tmp_path / "map.json"), data_dir=tmp_path, start_midi=False,
    )
    shell.piano.handle_key("enter")
    shell._worker = FakeWorker()
    shell.shutdown()

    assert any(getattr(event, "__class__", None).__name__ == "NoteOff" for event in log if not isinstance(event, str))
    release_index = log.index(next(event for event in log if isinstance(event, NoteOff)))
    assert log.index("worker.join") < release_index
    panic_index = log.index(next(event for event in log if isinstance(event, Panic)))
    backend_index = log.index("backend.close")
    engine_index = log.index("engine.close")
    midi_index = log.index("midi.close")
    assert panic_index < backend_index < engine_index < midi_index
    assert log.index("midi.release") < backend_index


def test_audio_device_failure_is_visible_and_keeps_the_null_backend_usable(tmp_path) -> None:
    instrument = SineInstrument()
    spec = demo_spec()
    engine = Engine(instrument, registry=spec.registry)

    def missing_device():
        raise RuntimeError("fixture audio device unavailable")

    backend = SoundDeviceBackend(engine, module_loader=missing_device).start()
    shell = Shell(spec, engine=engine, backend=backend, data_dir=tmp_path, start_midi=False)
    try:
        frame = shell.snapshot(100, 30)
        assert "Audio fallback" in frame
        assert "fixture audio device unavailable" in frame
        assert backend.is_fallback
        assert backend.active_backend.render(256).shape == (256, 2)
    finally:
        shell.shutdown()


def test_real_terminal_keys_reach_shell_overlays_and_fake_midi_picker(tmp_path) -> None:
    shell = Shell(demo_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    midi_backend = FakeMidiBackend(("Test MIDI keyboard",))
    shell.midi = MidiInput(shell._on_midi_event, backend=midi_backend, cc_learn=shell.cc_learn)
    ui = shell.build_app()
    with HeadlessApp(size=(100, 30), app=ui) as app:
        app.press("f1")
        assert shell.overlay == "help"
        app.press("escape")
        assert shell.overlay is None

        app.press("c-p")
        app.send_keys("preset")
        app.press("enter")
        assert shell.overlay == "presets"
        app.press("escape")

        app.press("f7")
        assert shell.overlay == "midi"
        assert shell.midi_ports == ("Test MIDI keyboard",)
        app.press("enter")
        assert shell.midi.connected_port == "Test MIDI keyboard"

        app.press("f9")
        assert any(isinstance(event, Panic) for event in shell.engine.event_queue.drain())
        app.press("c-q")
    assert shell._closed


def test_shell_tracks_midi_sounding_highlights_and_learned_cc_values(tmp_path) -> None:
    shell = Shell(demo_spec(), no_audio=True, data_dir=tmp_path, start_midi=False)
    try:
        shell._ensure_widgets(100, 30)
        shell._on_midi_event(NoteOn(700, 60, 0.8, "midi"))
        assert 60 in shell.piano._external_sounding
        shell._on_midi_event(NoteOff(700))
        assert 60 not in shell.piano._external_sounding

        shell.cc_learn.arm("amp.level")
        assert shell.cc_learn.feed(7, 127)
        shell._on_midi_event(ControlChange(7, 127))
        assert shell._known_params["amp.level"] == 1.0
    finally:
        shell.shutdown()


def test_instrument_screen_keys_are_delegated_to_the_spec(tmp_path) -> None:
    visited: list[str] = []
    spec = replace(demo_spec(), on_screen=lambda key, _shell: visited.append(key))
    shell = Shell(spec, no_audio=True, data_dir=tmp_path, start_midi=False)
    try:
        assert shell.handle_key("f3")
        assert visited == ["f3"]
        assert any(command_id == "screen-3" for command_id, _label, _action in shell._commands())
    finally:
        shell.shutdown()


def test_instrument_spec_polyphony_seed_and_extras_validation_reach_shared_shell(tmp_path) -> None:
    validate = lambda extras: {"profile": extras.get("profile", "default")}
    base = demo_spec()
    spec = InstrumentSpec(
        identifier=base.identifier,
        name=base.name,
        instrument_factory=base.instrument_factory,
        registry=base.registry,
        factory_package=base.factory_package,
        factory_presets_dir=base.factory_presets_dir,
        factory_skins_dir=base.factory_skins_dir,
        max_voices=3,
        extras_validator=validate,
    )
    shell = Shell(spec, no_audio=True, seed=314, data_dir=tmp_path, start_midi=False)
    try:
        assert shell.engine.max_voices == 3
        assert shell.engine.seed == 314
        assert shell.presets.extras_validator is validate
    finally:
        shell.shutdown()
