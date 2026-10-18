"""Command-line entry point for DRIFT."""

from __future__ import annotations

import argparse

from trio_drift import __version__
from trio_drift.presets import load_factory_presets


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="drift",
        description="DRIFT terminal synthesizer. Run without options to see available commands.",
    )
    parser.add_argument("--version", action="version", version=f"drift {__version__}")
    parser.add_argument("--list-presets", action="store_true", help="list packaged factory presets")
    arguments = parser.parse_args()
    if arguments.list_presets:
        for preset in load_factory_presets():
            print(f"{preset.id}\t{preset.name}")
        return 0
    parser.print_help()
    return 0
