"""Device-free and lazy sounddevice output backends."""

from __future__ import annotations

import importlib
import time
from typing import Any, Callable

import numpy as np

from trio_kit.engine.engine import Engine


class NullBackend:
    """A device-free backend for --no-audio, tests, and offline control loops."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.running = False
        self.closed = False
        self.last_error: str | None = None
        self.engine.set_backend_name("null")

    @property
    def is_fallback(self) -> bool:
        return False

    def start(self) -> NullBackend:
        if self.closed:
            raise RuntimeError("backend is closed")
        self.running = True
        return self

    def render(self, frames: int) -> np.ndarray:
        if not self.running or self.closed:
            return np.zeros((frames, 2), dtype=np.float32)
        try:
            return self.engine.render(frames)
        except Exception as error:
            self.last_error = str(error)[:256]
            self.engine.record_callback_error(error)
            return np.zeros((frames, 2), dtype=np.float32)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.running = False
        self.engine.close()


class SoundDeviceBackend:
    """OutputStream adapter; importing sounddevice is deferred until start()."""

    def __init__(
        self,
        engine: Engine,
        *,
        device: int | str | None = None,
        module_loader: Callable[[], Any] | None = None,
    ) -> None:
        self.engine = engine
        self.device = device
        self._module_loader = module_loader
        self._stream: Any | None = None
        self._fallback: NullBackend | None = None
        self.running = False
        self.closed = False
        self.last_error: str | None = None
        self.engine.set_backend_name("sounddevice")

    @property
    def is_fallback(self) -> bool:
        return self._fallback is not None

    @property
    def active_backend(self) -> SoundDeviceBackend | NullBackend:
        return self._fallback if self._fallback is not None else self

    def _load_sounddevice(self) -> Any:
        if self._module_loader is not None:
            return self._module_loader()
        return importlib.import_module("sounddevice")

    @staticmethod
    def _close_stream(stream: Any | None, *, stop: bool = False) -> None:
        if stream is None:
            return
        if stop:
            stop_stream = getattr(stream, "stop", None)
            if callable(stop_stream):
                try:
                    stop_stream()
                except Exception:
                    pass
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _activate_fallback(self, error: BaseException, *, close_stream: bool = True) -> None:
        self.last_error = f"Audio output unavailable: {error}"[:256]
        self.engine.record_callback_error(error)
        if close_stream:
            self._close_stream(self._stream, stop=True)
            self._stream = None
        self._fallback = NullBackend(self.engine).start()
        self.running = True

    def start(self) -> SoundDeviceBackend:
        if self.closed:
            raise RuntimeError("backend is closed")
        if self.running:
            return self
        try:
            sounddevice = self._load_sounddevice()
            self._stream = sounddevice.OutputStream(
                samplerate=self.engine.sample_rate,
                channels=2,
                dtype="float32",
                blocksize=0,
                callback=self.callback,
                device=self.device,
            )
            # Some host APIs invoke the callback synchronously from start().
            self.running = True
            self._stream.start()
        except Exception as error:
            self.running = False
            self._activate_fallback(error, close_stream=True)
        return self

    def callback(self, outdata: Any, frames: int, time_info: Any = None, status: Any = None) -> None:
        started = time.perf_counter()
        try:
            if self.closed:
                outdata.fill(0.0)
                return
            if self._fallback is not None:
                outdata.fill(0.0)
                return
            if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0:
                raise ValueError("callback frame count must be a positive integer")
            rendered = self.engine.render(frames)
            if rendered.shape != (frames, 2):
                raise ValueError("engine returned an invalid callback buffer shape")
            outdata[:] = rendered
        except Exception as error:
            try:
                outdata.fill(0.0)
            except Exception:
                pass
            # Stopping/closing a PortAudio stream from its own callback can
            # deadlock. Leave cleanup to close(), and emit silence meanwhile.
            self._activate_fallback(error, close_stream=False)
        finally:
            self.engine.record_callback_time(time.perf_counter() - started)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.running = False
        stream = self._stream
        self._stream = None
        if stream is not None:
            self._close_stream(stream, stop=True)
        if self._fallback is not None:
            self._fallback.closed = True
            self._fallback.running = False
        self.engine.close()


def open_backend(engine: Engine, *, no_audio: bool = False, device: int | str | None = None) -> NullBackend | SoundDeviceBackend:
    """Start audio when requested, otherwise return the usable null backend."""
    if no_audio:
        return NullBackend(engine).start()
    return SoundDeviceBackend(engine, device=device).start()


__all__ = ["NullBackend", "SoundDeviceBackend", "open_backend"]
