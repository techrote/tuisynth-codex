"""Command-line entry point for LOOM."""

from __future__ import annotations

from collections.abc import Sequence

from trio_kit.cli import run_cli
from trio_loom import __version__
from trio_loom.ui import loom_spec


def main(argv: Sequence[str] | None = None) -> int:
    """Run LOOM through the shared hardware-safe instrument CLI."""
    return run_cli(loom_spec(), argv=argv, command="loom", version=__version__)
