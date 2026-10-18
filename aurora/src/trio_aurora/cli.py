"""Command-line entry point for AURORA."""

from __future__ import annotations

from typing import Sequence

from trio_aurora import __version__
from trio_aurora.instrument import aurora_spec
from trio_kit.cli import run_cli


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(aurora_spec(), argv=argv, command="aurora", version=__version__)
