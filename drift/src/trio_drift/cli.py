"""Command-line entry point for DRIFT."""

from __future__ import annotations

import argparse

from trio_drift import __version__


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="drift",
        description="DRIFT terminal synthesizer. Run without options to see available commands.",
    )
    parser.add_argument("--version", action="version", version=f"drift {__version__}")
    parser.parse_args()
    parser.print_help()
    return 0
