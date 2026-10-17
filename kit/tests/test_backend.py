from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from trio_kit.engine import Engine, NullBackend, SoundDeviceBackend
from trio_kit.events import NoteOn

from engine_fakes import FakeInstrument


class FakeStream:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.fail_start = fail_start
        self.started = False
        self.stopped = False
        self.closed = False
        self.kwargs: dict[str, object] = {}

    def start(self) -> None:
        self.started = True
        if self.fail_start:
            raise RuntimeError("device disappeared")

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def test_sounddevice_import_is_lazy_until_start() -> None:
    loaded: list[bool] = []
    engine = Engine(FakeInstrument())
    backend = SoundDeviceBackend(engine, module_loader=lambda: loaded.append(True))

    assert loaded == []
    assert not backend.running


def test_device_free_backend_renders_and_closes_cleanly() -> None:
    engine = Engine(FakeInstrument())
    backend = NullBackend(engine).start()

    output = backend.render(257)

    assert backend.running
    assert output.shape == (257, 2)
    assert np.isfinite(output).all()
    backend.close()
    assert backend.closed
    assert not backend.running


def test_missing_sounddevice_falls_back_to_a_readable_null_backend() -> None:
    engine = Engine(FakeInstrument())

    def missing() -> object:
        raise ImportError("sounddevice is not installed")

    backend = SoundDeviceBackend(engine, module_loader=missing).start()

    assert backend.is_fallback
    assert backend.active_backend is not backend
    assert backend.last_error is not None and "sounddevice is not installed" in backend.last_error
    assert backend.active_backend.render(12).shape == (12, 2)  # type: ignore[union-attr]
    backend.close()


def test_start_failure_closes_partial_stream_and_uses_fallback() -> None:
    stream = FakeStream(fail_start=True)

    def output_stream(**kwargs: object) -> FakeStream:
        stream.kwargs = kwargs
        return stream

    engine = Engine(FakeInstrument())
    backend = SoundDeviceBackend(engine, module_loader=lambda: SimpleNamespace(OutputStream=output_stream)).start()

    assert backend.is_fallback
    assert stream.started
    assert stream.closed
    assert stream.stopped
    assert backend.last_error is not None and "device disappeared" in backend.last_error
    assert stream.kwargs["samplerate"] == 48_000
    assert stream.kwargs["channels"] == 2
    backend.close()


def test_callback_fills_varied_sizes_from_engine() -> None:
    engine = Engine(FakeInstrument())
    engine.push(NoteOn(1, 60, 1, "test"))
    stream = FakeStream()

    def output_stream(**kwargs: object) -> FakeStream:
        stream.kwargs = kwargs
        return stream

    backend = SoundDeviceBackend(engine, module_loader=lambda: SimpleNamespace(OutputStream=output_stream)).start()
    callback = stream.kwargs["callback"]
    for frames in (1, 255, 256, 257, 1_024):
        outdata = np.full((frames, 2), np.nan, dtype=np.float32)
        callback(outdata, frames)  # type: ignore[operator]
        assert np.isfinite(outdata).all()
    assert not backend.is_fallback
    backend.close()


def test_callback_failure_writes_silence_and_defers_stream_cleanup_until_close() -> None:
    engine = Engine(FakeInstrument())
    stream = FakeStream()

    def output_stream(**kwargs: object) -> FakeStream:
        stream.kwargs = kwargs
        return stream

    backend = SoundDeviceBackend(engine, module_loader=lambda: SimpleNamespace(OutputStream=output_stream)).start()

    def fail(frames: int) -> np.ndarray:
        raise RuntimeError("render failed")

    engine.render = fail  # type: ignore[method-assign]
    outdata = np.full((257, 2), np.nan, dtype=np.float32)
    backend.callback(outdata, 257)

    assert np.array_equal(outdata, np.zeros_like(outdata))
    assert backend.is_fallback
    assert backend.last_error is not None and "render failed" in backend.last_error
    assert not stream.closed

    another = np.full((32, 2), np.nan, dtype=np.float32)
    backend.callback(another, 32)
    assert np.array_equal(another, np.zeros_like(another))
    backend.close()
    assert stream.closed
    assert stream.stopped


def test_callback_after_close_writes_silence_without_reactivating_backend() -> None:
    engine = Engine(FakeInstrument())
    backend = SoundDeviceBackend(engine, module_loader=lambda: (_ for _ in ()).throw(AssertionError("loaded")))
    backend.closed = True
    outdata = np.full((16, 2), np.nan, dtype=np.float32)

    backend.callback(outdata, 16)

    assert np.array_equal(outdata, np.zeros_like(outdata))
    assert not backend.is_fallback
