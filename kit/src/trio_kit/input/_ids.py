"""Default process-wide note allocator for the shared input producers."""

from trio_kit.events import NoteIds


DEFAULT_INPUT_NOTE_IDS = NoteIds()
