"""Run package tests and optional clean wheel installation checks."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("kit", "aurora", "loom", "drift")
IMPORTS = {
    "kit": ("trio-kit", "trio_kit", "trio-demo"),
    "aurora": ("trio-aurora", "trio_aurora", "aurora"),
    "loom": ("trio-loom", "trio_loom", "loom"),
    "drift": ("trio-drift", "trio_drift", "drift"),
}


class CheckFailed(RuntimeError):
    """Raised when a qualification subprocess fails."""


def selected_packages(selection: str) -> tuple[str, ...]:
    if selection == "all":
        return PACKAGES
    return (selection,)


def wheel_packages(packages: Sequence[str]) -> tuple[str, ...]:
    """Include the shared kit when packaging an instrument on its own."""
    selected = set(packages)
    if selected & {"aurora", "loom", "drift"}:
        selected.add("kit")
    return tuple(package for package in PACKAGES if package in selected)


def run_process(
    command: Sequence[str],
    *,
    label: str,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    printable = " ".join(command)
    print(f"\n==> {label}: {printable}", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )
    if capture and result.stdout:
        print(result.stdout, end="")
    if capture and result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        raise CheckFailed(f"{label} failed with exit code {result.returncode}")
    return result


def run_tests(packages: Sequence[str], *, update_snapshots: bool) -> None:
    environment = os.environ.copy()
    if update_snapshots:
        environment["TRIO_UPDATE_SNAPSHOTS"] = "1"
    for package in packages:
        run_process(
            [sys.executable, "-m", "pytest", "-q", str(ROOT / package / "tests")],
            label=f"{package} tests",
            env=environment,
        )


def venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def venv_script(environment: Path, command: str) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / f"{command}.exe"
    return environment / "bin" / command


def check_wheels(packages: Sequence[str]) -> None:
    packages = wheel_packages(packages)
    with tempfile.TemporaryDirectory(prefix="trio-wheel-check-") as temporary:
        workspace = Path(temporary)
        wheels = workspace / "wheels"
        wheels.mkdir()

        for package in packages:
            run_process(
                [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheels), str(ROOT / package)],
                label=f"build {package} wheel",
            )

        environment = workspace / "install"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = venv_python(environment)
        wheel_paths = sorted(wheels.glob("*.whl"))
        if len(wheel_paths) != len(packages):
            raise CheckFailed(f"expected {len(packages)} wheels, found {len(wheel_paths)}")

        run_process(
            [str(python), "-m", "pip", "install", *map(str, wheel_paths)],
            label="install wheels in a clean environment",
            cwd=workspace,
        )

        for package in packages:
            distribution, import_name, command = IMPORTS[package]
            check_script = (
                "import importlib, importlib.metadata; "
                f"assert importlib.metadata.version({distribution!r}) == '0.1.0'; "
                f"assert importlib.import_module({import_name!r}).__version__ == '0.1.0'"
            )
            if package == "kit":
                check_script += (
                    "; from trio_kit.tui import Canvas, CanvasApp, FocusRing, PianoWidget; "
                    "from trio_kit.tui.testing import HeadlessApp; "
                    "from trio_kit.shell import InstrumentSpec, Shell; "
                    "from trio_kit.cli import run_cli; "
                    "from trio_kit.demo import demo_spec; "
                    "assert Canvas and CanvasApp and FocusRing and PianoWidget and HeadlessApp; "
                    "assert InstrumentSpec and Shell and run_cli and demo_spec"
                )
            if package == "aurora":
                check_script += (
                    "; from trio_aurora import AuroraInstrument, aurora_spec, generate_table_set; "
                    "from importlib.resources import files; "
                    "assert AuroraInstrument and aurora_spec and generate_table_set; "
                    "assert files('trio_aurora').joinpath('data/presets/glacier-choir.json').is_file()"
                )
            if package == "loom":
                check_script += (
                    "; from trio_loom import LoomInstrument, WaveguideString, loom_registry, load_factory_presets; "
                    "from importlib.resources import files; "
                    "assert LoomInstrument and WaveguideString and loom_registry; "
                    "assert len(load_factory_presets()) >= 8; "
                    "assert files('trio_loom').joinpath('data/presets/rosewood-harp.json').is_file()"
                )
            if package == "drift":
                check_script += (
                    "; from trio_drift import DriftInstrument, GrainPool, drift_registry, load_factory_presets; "
                    "from importlib.resources import files; "
                    "assert DriftInstrument and GrainPool and drift_registry; "
                    "assert {preset.id for preset in load_factory_presets()} == "
                    "{'squall-choir', 'desert-flute', 'monsoon-breath', 'howling-pass', "
                    "'whisper-field', 'vowel-sweep', 'glass-wind', 'deep-exhale'}; "
                    "assert files('trio_drift').joinpath('data/presets/squall-choir.json').is_file()"
                )
            run_process(
                [str(python), "-c", check_script],
                label=f"installed {distribution} metadata and import smoke check",
                cwd=workspace,
            )
            if command is not None:
                result = run_process(
                    [str(venv_script(environment, command)), "--version"],
                    label=f"installed {command} --version",
                    cwd=workspace,
                    capture=True,
                )
                expected = f"{command} 0.1.0"
                if result.stdout.strip() != expected:
                    raise CheckFailed(f"{command} --version returned {result.stdout.strip()!r}; expected {expected!r}")
                if package == "aurora":
                    preset_result = run_process(
                        [str(venv_script(environment, command)), "--list-presets"],
                        label="installed aurora factory preset listing",
                        cwd=workspace,
                        capture=True,
                    )
                    required_presets = {
                        "glacier-choir", "northern-veil", "cathedral-air", "solar-bloom",
                        "ice-strings", "deep-ocean", "hollow-partials", "stretch-bells",
                    }
                    listed = {line.split("\t", maxsplit=1)[0] for line in preset_result.stdout.splitlines() if line}
                    if not required_presets <= listed:
                        raise CheckFailed(f"aurora preset listing omitted {sorted(required_presets - listed)}")
                if package == "drift":
                    drift_data_dir = workspace / "drift-user-data"
                    drift_data_dir.mkdir()
                    preset_result = run_process(
                        [str(venv_script(environment, command)), "--list-presets", "--data-dir", str(drift_data_dir)],
                        label="installed drift factory preset listing",
                        cwd=workspace,
                        capture=True,
                    )
                    required_presets = {
                        "squall-choir", "desert-flute", "monsoon-breath", "howling-pass",
                        "whisper-field", "vowel-sweep", "glass-wind", "deep-exhale",
                    }
                    listed = {line.split("\t", maxsplit=1)[0] for line in preset_result.stdout.splitlines() if line}
                    if listed != required_presets:
                        raise CheckFailed(f"drift preset listing differs from required set: {sorted(listed ^ required_presets)}")
                    skin_result = run_process(
                        [str(venv_script(environment, command)), "--list-skins", "--data-dir", str(drift_data_dir)],
                        label="installed drift factory skin listing",
                        cwd=workspace,
                        capture=True,
                    )
                    listed_skins = set(skin_result.stdout.splitlines())
                    required_skins = {"mono", "squall", "desert-haze", "monsoon"}
                    if listed_skins != required_skins:
                        raise CheckFailed(f"drift skin listing differs from required set: {sorted(listed_skins ^ required_skins)}")
                    qualified_environment = os.environ.copy()
                    qualified_environment.pop("NO_COLOR", None)
                    snapshot = run_process(
                        [str(venv_script(environment, command)), "--snapshot", "80x24", "--screen", "grain", "--skin", "squall", "--data-dir", str(drift_data_dir)],
                        label="installed drift compact headless snapshot",
                        cwd=workspace,
                        env=qualified_environment,
                        capture=True,
                    )
                    if any(marker not in snapshot.stdout for marker in ("GRAIN", "DRIFT", "squall")):
                        raise CheckFailed("drift compact snapshot did not contain its instrument, grain HUD and selected skin")
                    run_process(
                        [str(venv_script(environment, command)), "--selftest", "--data-dir", str(drift_data_dir)],
                        label="installed drift offline selftest",
                        cwd=workspace,
                        env=qualified_environment,
                        capture=True,
                    )
                    render_path = workspace / "drift-smoke.wav"
                    run_process(
                        [str(venv_script(environment, command)), "--render", str(render_path), "--notes", "C4", "--seconds", "0.05", "--data-dir", str(drift_data_dir)],
                        label="installed drift offline render",
                        cwd=workspace,
                        env=qualified_environment,
                        capture=True,
                    )
                    if not render_path.is_file() or render_path.stat().st_size <= 44:
                        raise CheckFailed("drift offline render did not create a non-empty WAV file")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", choices=(*PACKAGES, "all"), default="all")
    parser.add_argument("--packaging", action="store_true", help="build selected wheels and install them in a clean environment")
    parser.add_argument("--update-snapshots", action="store_true", help="set TRIO_UPDATE_SNAPSHOTS=1 for selected tests")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = make_parser().parse_args(argv)
    packages = selected_packages(arguments.package)
    try:
        run_tests(packages, update_snapshots=arguments.update_snapshots)
        if arguments.packaging:
            check_wheels(packages)
    except CheckFailed as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
