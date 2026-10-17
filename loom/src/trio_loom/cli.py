"""Command-line entry point for LOOM."""

from __future__ import annotations

import argparse

from trio_loom import __version__


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="loom",
        description="LOOM terminal synthesizer. Run without options to see available commands.",
    )
    parser.add_argument("--version", action="version", version=f"loom {__version__}")
    parser.parse_args()
    parser.print_help()
    return 0
