"""Command-line entry point for DRIFT."""

from __future__ import annotations

from collections.abc import Sequence

from trio_drift import __version__
from trio_drift.ui import drift_spec
from trio_kit.cli import run_cli


def main(argv: Sequence[str] | None = None) -> int:
    """Run DRIFT through the shared hardware-safe instrument CLI."""
    return run_cli(drift_spec(), argv=argv, command="drift", version=__version__)
