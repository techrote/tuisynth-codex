"""Command-line entry point for AURORA."""

from __future__ import annotations

import argparse

from trio_aurora import __version__


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="aurora",
        description="AURORA terminal synthesizer. Run without options to see available commands.",
    )
    parser.add_argument("--version", action="version", version=f"aurora {__version__}")
    parser.parse_args()
    parser.print_help()
    return 0
