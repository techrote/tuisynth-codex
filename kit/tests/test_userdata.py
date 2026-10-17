from __future__ import annotations

import os
from pathlib import Path

import pytest

from trio_kit.userdata import get_user_data_dir


def test_explicit_data_root_is_partitioned_per_instrument(tmp_path: Path) -> None:
    assert get_user_data_dir("aurora", tmp_path) == tmp_path / "aurora"
    assert get_user_data_dir("loom", tmp_path) == tmp_path / "loom"


def test_default_user_data_root_uses_platform_convention(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert get_user_data_dir("drift") == tmp_path / "trio" / "drift"
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert get_user_data_dir("drift") == tmp_path / "trio" / "drift"


@pytest.mark.parametrize("instrument", ("", "../aurora", "AURORA", "a b", "trio_aurora"))
def test_invalid_instrument_directory_names_are_rejected(instrument: str) -> None:
    with pytest.raises(ValueError):
        get_user_data_dir(instrument)
