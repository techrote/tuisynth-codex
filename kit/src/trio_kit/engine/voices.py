"""Stable note-id voice ownership, sustain, stealing, and release tails."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

import numpy as np

from trio_kit.constants import MAX_EVENT_QUEUE
from trio_kit.events import NoteOff, NoteOn
from trio_kit.params import ParamSnapshot
from trio_kit.engine.protocols import Voice


@dataclass(slots=True)
class _VoiceSlot:
    voice: Voice | None = None
    note_id: int | None = None
    order: int = 0
    key_down: bool = False
    released: bool = False
    sustained: bool = False
    last_level: float = 0.0


@dataclass(slots=True)
class _FadeTail:
    voice: Voice
    fade_frames: int
    position: int = 0
    last_level: float = 0.0

    @property
    def remaining(self) -> int:
        return max(0, self.fade_frames - self.position)


class VoiceManager:
    """Allocate voices by note identity and preserve short anti-click tails."""

    def __init__(
        self,
        instrument: Any,
        max_voices: int,
        sample_rate: int,
        seed: int = 0,
        *,
        max_tails: int | None = None,
    ) -> None:
        if isinstance(max_voices, bool) or not isinstance(max_voices, int) or max_voices <= 0:
            raise ValueError("max_voices must be a positive integer")
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if max_tails is None:
            max_tails = max_voices + MAX_EVENT_QUEUE * 2
        if isinstance(max_tails, bool) or not isinstance(max_tails, int) or max_tails <= 0:
            raise ValueError("max_tails must be a positive integer")
        if not callable(getattr(instrument, "create_voice", None)):
            raise TypeError("instrument must implement create_voice(rng)")
        self.instrument = instrument
        self.max_voices = max_voices
        self.sample_rate = sample_rate
        self.seed = seed
        self._slots = [_VoiceSlot() for _ in range(max_voices)]
        self._by_note: dict[int, _VoiceSlot] = {}
        self._tails: list[_FadeTail] = []
        self._next_order = 0
        self._voice_counter = 0
        self._sustain = False
        self._max_tails = max_tails

    @property
    def active_count(self) -> int:
        self._remove_finished()
        return len(self._by_note)

    @property
    def tail_count(self) -> int:
        return len(self._tails)

    @property
    def note_ids(self) -> tuple[int, ...]:
        self._remove_finished()
        return tuple(self._by_note)

    @property
    def sustain(self) -> bool:
        return self._sustain

    def _new_voice(self) -> Voice:
        counter = self._voice_counter
        self._voice_counter += 1
        rng = np.random.default_rng(np.random.SeedSequence([self.seed, counter]))
        return self.instrument.create_voice(rng)

    @staticmethod
    def _finished(voice: Voice | None) -> bool:
        if voice is None:
            return True
        finished = getattr(voice, "finished", False)
        return bool(finished() if callable(finished) else finished)

    def _remove_finished(self) -> None:
        for slot in self._slots:
            if slot.note_id is not None and self._finished(slot.voice):
                self._by_note.pop(slot.note_id, None)
                self._clear_slot(slot)

    @staticmethod
    def _clear_slot(slot: _VoiceSlot) -> None:
        slot.voice = None
        slot.note_id = None
        slot.order = 0
        slot.key_down = False
        slot.released = False
        slot.sustained = False
        slot.last_level = 0.0

    @staticmethod
    def _rms(buffer: np.ndarray) -> float:
        if buffer.size == 0:
            return 0.0
        if not np.isfinite(buffer).all():
            return math.inf
        return float(np.sqrt(np.mean(np.square(buffer, dtype=np.float64))))

    def _make_tail(self, slot: _VoiceSlot, milliseconds: float) -> None:
        voice = slot.voice
        if voice is None:
            return
        if slot.note_id is not None:
            self._by_note.pop(slot.note_id, None)
        if not slot.released:
            voice.release()
        fade_frames = max(1, int(round(self.sample_rate * milliseconds / 1000.0)))
        if not self._finished(voice):
            self._tails.append(_FadeTail(voice, fade_frames, last_level=slot.last_level))
            self._trim_tails()
        self._clear_slot(slot)

    def _trim_tails(self) -> None:
        while len(self._tails) > self._max_tails:
            # Prefer to discard a tail that is already almost silent.
            index = min(range(len(self._tails)), key=lambda i: (self._tails[i].remaining, self._tails[i].last_level, i))
            self._tails.pop(index)

    def _select_slot(self) -> tuple[_VoiceSlot, bool]:
        self._remove_finished()
        for slot in self._slots:
            if slot.note_id is None:
                return slot, False
        released = [slot for slot in self._slots if slot.released and not slot.sustained]
        if released:
            return min(released, key=lambda slot: (slot.last_level, slot.order)), True
        return min(self._slots, key=lambda slot: slot.order), True

    def note_on(self, event: NoteOn, params: ParamSnapshot) -> Voice:
        if not isinstance(event, NoteOn):
            raise TypeError("note_on requires a NoteOn event")
        if event.note_id in self._by_note:
            raise ValueError(f"note_id {event.note_id} is already active")
        slot, occupied = self._select_slot()
        voice = self._new_voice()
        if occupied:
            self._make_tail(slot, 5.0)
        slot.voice = voice
        slot.note_id = event.note_id
        slot.order = self._next_order
        self._next_order += 1
        slot.key_down = True
        slot.released = False
        slot.sustained = False
        slot.last_level = 0.0
        self._by_note[event.note_id] = slot
        voice.start(float(event.pitch), float(event.velocity), params)
        return voice

    def note_off(self, event: NoteOff) -> bool:
        if not isinstance(event, NoteOff):
            raise TypeError("note_off requires a NoteOff event")
        slot = self._by_note.get(event.note_id)
        if slot is None or not slot.key_down:
            return False
        slot.key_down = False
        if self._sustain:
            slot.sustained = True
        else:
            self._release(slot)
        return True

    @staticmethod
    def _release(slot: _VoiceSlot) -> None:
        if slot.voice is not None and not slot.released:
            slot.voice.release()
        slot.released = True
        slot.sustained = False

    def set_sustain(self, on: bool) -> None:
        if not isinstance(on, bool):
            raise ValueError("sustain state must be a boolean")
        if self._sustain == on:
            return
        self._sustain = on
        if not on:
            for slot in self._slots:
                if slot.sustained:
                    self._release(slot)

    def panic(self) -> None:
        self._sustain = False
        for slot in self._slots:
            if slot.note_id is not None:
                self._make_tail(slot, 10.0)

    def retarget(self, note_id: int, pitch: float) -> bool:
        if isinstance(note_id, bool) or not isinstance(note_id, int) or note_id <= 0:
            raise ValueError("note_id must be a positive integer")
        if isinstance(pitch, bool) or not isinstance(pitch, Real):
            raise ValueError("pitch must be a finite MIDI note number in the range 0..127")
        try:
            normalized_pitch = float(pitch)
        except (OverflowError, ValueError) as error:
            raise ValueError("pitch must be a finite MIDI note number in the range 0..127") from error
        if not math.isfinite(normalized_pitch) or not 0.0 <= normalized_pitch <= 127.0:
            raise ValueError("pitch must be a finite MIDI note number in the range 0..127")
        slot = self._by_note.get(note_id)
        if slot is None or slot.voice is None:
            return False
        retarget = getattr(slot.voice, "retarget", None)
        if not callable(retarget):
            return False
        retarget(normalized_pitch)
        return True

    def render(self, frames: int, params: ParamSnapshot) -> np.ndarray:
        if isinstance(frames, bool) or not isinstance(frames, int) or frames < 0:
            raise ValueError("frames must be a non-negative integer")
        output = np.zeros((frames, 2), dtype=np.float32)
        if frames == 0:
            return output
        self._remove_finished()
        for slot in self._slots:
            if slot.note_id is None or slot.voice is None:
                continue
            buffer = _voice_buffer(slot.voice, frames, params)
            output += buffer
            slot.last_level = self._rms(buffer)
            if self._finished(slot.voice):
                self._by_note.pop(slot.note_id, None)
                self._clear_slot(slot)

        live_tails: list[_FadeTail] = []
        for tail in self._tails:
            if tail.remaining <= 0 or self._finished(tail.voice):
                continue
            count = min(frames, tail.remaining)
            buffer = _voice_buffer(tail.voice, count, params)
            gains = np.maximum(
                0.0,
                1.0 - (tail.position + np.arange(count, dtype=np.float64)) / tail.fade_frames,
            ).astype(np.float32)
            faded = buffer * gains[:, None]
            output[:count] += faded
            tail.position += count
            tail.last_level = self._rms(faded)
            if tail.remaining > 0 and not self._finished(tail.voice):
                live_tails.append(tail)
        self._tails = live_tails
        return output

    def reset(self) -> None:
        self._by_note.clear()
        self._tails.clear()
        self._sustain = False
        for slot in self._slots:
            self._clear_slot(slot)


def _voice_buffer(voice: Voice, frames: int, params: ParamSnapshot) -> np.ndarray:
    result = voice.render(frames, params)
    buffer = np.asarray(result, dtype=np.float32)
    if buffer.shape != (frames, 2):
        raise ValueError(f"voice must return a stereo buffer with shape ({frames}, 2)")
    return buffer


__all__ = ["VoiceManager"]
