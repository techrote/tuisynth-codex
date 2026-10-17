"""Platform-aware per-instrument user data locations."""

from __future__ import annotations

import os
import re
from pathlib import Path


_INSTRUMENT_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def get_user_data_dir(instrument: str, data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Return the writable data directory for one instrument.

    An explicit ``data_dir`` is a shared data root; the instrument id is appended
    so multiple TRIO apps can safely use the same ``--data-dir`` option.
    """
    if not isinstance(instrument, str) or not _INSTRUMENT_RE.fullmatch(instrument):
        raise ValueError("instrument must be a lowercase identifier such as 'aurora'")
    if data_dir is not None:
        return Path(data_dir).expanduser() / instrument

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        configured = os.environ.get("XDG_DATA_HOME")
        base = Path(configured).expanduser() if configured and Path(configured).is_absolute() else Path.home() / ".local" / "share"
    return base / "trio" / instrument
