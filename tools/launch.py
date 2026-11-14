"""Create/reuse an owned local TRIO environment, then run an installed command.

All bootstrap options precede the command; everything after it is forwarded.
No device dependencies are installed unless explicitly selected with --extras.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    print("TRIO needs Python 3.11 or newer. Set TRIO_PYTHON to a supported executable.", file=sys.stderr)
    raise SystemExit(2)

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Iterator, Sequence


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("kit", "aurora", "loom", "drift")
COMMANDS = ("aurora", "loom", "drift", "trio-demo")
VERSION = "0.1.0"
SCHEMA = 1
OWNER = ".trio-owned.json"
READY = ".trio-ready.json"
SETUP_TIMEOUT = 600


class LaunchError(RuntimeError):
    """A setup failure that is safe to report without a traceback."""


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    # Preserve only connection settings for explicit online first-run setup.
    # Ambient requirements/options must not change the selected installation.
    network_settings = {"PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_PROXY", "PIP_CERT", "PIP_CLIENT_CERT", "PIP_TRUSTED_HOST"}
    for key in tuple(environment):
        if key.startswith("PIP_") and key not in network_settings:
            environment.pop(key, None)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PIP_NO_INPUT"] = "1"
    # An owner's pip configuration must not redirect installation out of the venv.
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def venv_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def command_path(environment: Path, command: str) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return environment / directory / (command + suffix)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def setup_lock(environment: Path) -> Iterator[None]:
    """OS locks release on process exit, including interrupted/failed setup."""
    lock_path = environment.with_name(environment.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LaunchError("Another TRIO setup is running for this environment; wait for it to finish and retry.") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def parse_extras(value: str) -> tuple[str, ...]:
    extras = tuple(sorted(set(filter(None, (part.strip() for part in value.split(","))))))
    if any(extra not in {"audio", "midi"} for extra in extras):
        raise LaunchError("--extras accepts audio, midi, or audio,midi (an empty value selects neither).")
    return extras


def midi_build_guidance(extras: Sequence[str]) -> str:
    return (
        "Prepare a complete matching wheelhouse with the same Python interpreter: "
        f"python tools/release.py --prepare-wheelhouse wheelhouse --extras {','.join(extras)}; "
        "then rerun this launcher with --wheelhouse wheelhouse. "
        "The controlled preparation refreshes python-rtmidi 1.5.8's generated Cython C++ for newer Python. "
        "Native prerequisites: on Windows install Visual Studio Build Tools with Desktop development with C++ "
        "and use Developer PowerShell; on Ubuntu install build-essential, python3-dev, libasound2-dev and pkg-config. "
        "See docs/INSTALL.md."
    )


def package_inputs(root: Path) -> tuple[str, list[Path], list[Path]]:
    """Release wheels take precedence; never mix incomplete wheels and source."""
    requirement = root / "requirements-release.txt"
    if not requirement.is_file():
        raise LaunchError(f"Missing {requirement.name}; use a complete TRIO checkout or evaluation bundle.")
    optional_constraints = root / "requirements-optional.txt"
    if not optional_constraints.is_file():
        raise LaunchError(f"Missing {optional_constraints.name}; use a complete TRIO checkout or evaluation bundle.")
    if (root / "wheels").exists():
        paths = []
        for package in PACKAGES:
            matches = sorted((root / "wheels").glob(f"trio_{package}-{VERSION}-*.whl"))
            if len(matches) != 1:
                raise LaunchError(f"Expected exactly one trio-{package} {VERSION} wheel in {root / 'wheels'}.")
            paths.append(matches[0])
        return "wheels", paths, [requirement, optional_constraints, *paths]
    paths = [root / package for package in PACKAGES]
    files = [requirement, optional_constraints]
    for path in paths:
        if not (path / "pyproject.toml").is_file() or not (path / "src").is_dir():
            raise LaunchError(f"Missing source package {path.name}; use a complete TRIO checkout or evaluation bundle.")
        files.append(path / "pyproject.toml")
        for name in ("README.md", "MANIFEST.in"):
            if (path / name).is_file():
                files.append(path / name)
        files.extend(
            file for file in sorted((path / "src").rglob("*"))
            if file.is_file()
            and not any(part == "__pycache__" or part.endswith(".egg-info") for part in file.parts)
            and file.suffix not in {".pyc", ".pyo"}
        )
    return "source", paths, files


def fingerprint(root: Path, files: Sequence[Path], extras: Sequence[str]) -> str:
    digest = hashlib.sha256()
    settings = {
        "schema": SCHEMA, "root": str(root), "python": list(sys.version_info[:3]),
        "executable": str(Path(sys.executable).resolve()), "extras": list(extras),
    }
    digest.update(json.dumps(settings, sort_keys=True).encode("utf-8"))
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def run_setup(command: Sequence[str], *, environment: dict[str, str], cwd: Path) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, env=environment, check=False, timeout=SETUP_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LaunchError(f"Setup could not complete: {error}. Fix the cause, then run the same launcher again.") from error
    if result.returncode:
        raise LaunchError(
            f"Setup failed (exit {result.returncode}); no instrument was launched. "
            "Check the pip error above and retry. Offline setup needs all selected dependencies in --wheelhouse."
        )


def installed_state(environment: Path) -> dict:
    script = (
        "import json,sys; from importlib.metadata import distributions; "
        "print(json.dumps({'prefix':sys.prefix,'python':list(sys.version_info[:3]),"
        "'versions':{d.metadata['Name'].lower().replace('_','-'):d.version for d in distributions()}}))"
    )
    try:
        result = subprocess.run(
            [str(venv_python(environment)), "-I", "-c", script],
            env=clean_environment(), cwd=environment.parent,
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode:
            return {}
        data = json.loads(result.stdout)
        if Path(data.get("prefix", "")).resolve() != environment.resolve():
            return {}
        if data.get("python") != list(sys.version_info[:3]):
            return {}
        if any(data.get("versions", {}).get("trio-" + package) != VERSION for package in PACKAGES):
            return {}
        return data
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def prepare(root: Path, environment: Path, *, extras: str | None, wheelhouse: Path | None, reinstall: bool) -> None:
    if environment.is_symlink():
        raise LaunchError("TRIO_VENV must not be a symbolic link; choose a separate local environment directory.")
    if environment == root or environment in root.parents:
        raise LaunchError("TRIO_VENV must be a separate environment directory, not the checkout or its parent.")
    if wheelhouse is not None and not wheelhouse.is_dir():
        raise LaunchError(f"Wheelhouse does not exist: {wheelhouse}")
    mode, packages, inputs = package_inputs(root)
    with setup_lock(environment):
        previous = read_json(environment / READY)
        owner = read_json(environment / OWNER)
        saved = previous.get("extras", owner.get("extras", []))
        saved = saved if isinstance(saved, list) and all(isinstance(value, str) for value in saved) else []
        # Extras are additive. Removing optional backends requires a fresh venv,
        # so an ordinary launch never silently removes a previously selected one.
        chosen = tuple(sorted(set(parse_extras(",".join(saved))) | set(parse_extras(extras or ""))))
        expected = fingerprint(root, inputs, chosen)
        current = installed_state(environment) if (environment / READY).is_file() else {}
        if (
            not reinstall and previous.get("fingerprint") == expected and current
            and previous.get("installed") == current
            and all(command_path(environment, name).is_file() for name in COMMANDS)
        ):
            print(f"TRIO: reusing {environment}", file=sys.stderr, flush=True)
            return
        if environment.exists() and (not environment.is_dir() or any(environment.iterdir())) and owner.get("owner") != "TRIO":
            raise LaunchError(f"Refusing to modify an existing unmanaged environment: {environment}. Choose another TRIO_VENV.")
        environment.mkdir(parents=True, exist_ok=True)
        write_json(environment / OWNER, {"owner": "TRIO", "schema": SCHEMA, "extras": list(chosen)})
        (environment / READY).unlink(missing_ok=True)
        if wheelhouse is None and "midi" in chosen and sys.version_info[:2] >= (3, 13):
            raise LaunchError(
                "Python 3.13+ MIDI setup requires a compatible prebuilt wheelhouse; plain online "
                "python-rtmidi 1.5.8 source installation is not the qualified path. "
                f"{midi_build_guidance(chosen)} No instrument was launched. "
                "The selected interpreter and extras have been retained."
            )
        print(f"TRIO: setting up {mode} installation in {environment}; extras: {','.join(chosen) or 'none'}", file=sys.stderr, flush=True)
        try:
            # A relocatable interpreter reached through a PATH symlink can give
            # EnvBuilder the alias directory as its stdlib home. Invoke the
            # resolved base interpreter so pyvenv.cfg records the real location.
            base_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
            result = subprocess.run(
                [str(base_python), "-I", "-m", "venv", str(environment)],
                cwd=root, env=clean_environment(), check=False, timeout=SETUP_TIMEOUT,
            )
            if result.returncode:
                raise LaunchError("Cannot create the virtual environment. Install Python's venv/ensurepip support and retry.")
        except (OSError, subprocess.SubprocessError) as error:
            raise LaunchError(f"Cannot create the virtual environment: {error}. Install Python's venv/ensurepip support and retry.") from error
        python = str(venv_python(environment))
        subprocess_environment = clean_environment()
        offline = ["--no-index", "--find-links", str(wheelhouse)] if wheelhouse else []
        if wheelhouse:
            subprocess_environment["PIP_NO_INDEX"] = "1"
            subprocess_environment.pop("PIP_INDEX_URL", None)
            subprocess_environment.pop("PIP_EXTRA_INDEX_URL", None)
        constraints = str(root / "requirements-release.txt")
        optional_constraints = str(root / "requirements-optional.txt")
        run_setup(
            [python, "-m", "pip", "install", *offline, "-r", constraints],
            environment=subprocess_environment, cwd=root,
        )
        package_arguments = [str(path) for path in packages]
        run_setup(
            [python, "-m", "pip", "install", *offline, "--no-build-isolation", "--force-reinstall", "-c", constraints, *package_arguments],
            environment=subprocess_environment, cwd=root,
        )
        if chosen:
            # Only our four distributions use the pinned in-venv build tools.
            # Native optional dependencies may need a different PEP 517 backend
            # (for example Meson/Cython for RtMidi on newer Python releases).
            # Keep their build isolation enabled; the already-installed local
            # kit supplies the extras metadata without a PyPI TRIO dependency.
            optional_requirement = f"trio-kit[{','.join(chosen)}]=={VERSION}"
            try:
                run_setup(
                    [python, "-m", "pip", "install", *offline, "-c", constraints, "-c", optional_constraints, optional_requirement],
                    environment=subprocess_environment, cwd=root,
                )
            except LaunchError as error:
                native_hint = " " + midi_build_guidance(chosen) if "midi" in chosen else ""
                raise LaunchError(
                    f"Requested optional dependencies ({','.join(chosen)}) remain incomplete. {error}"
                    f"{native_hint} Alternatively, supply a compatible prebuilt wheelhouse for this OS, "
                    "architecture and Python version with --wheelhouse, then retry. "
                    "The selected interpreter and extras have been retained."
                ) from error
        run_setup([python, "-m", "pip", "check"], environment=subprocess_environment, cwd=root)
        state = installed_state(environment)
        if not state or not all(command_path(environment, name).is_file() for name in COMMANDS):
            raise LaunchError("Installation did not provide all four 0.1.0 distributions and commands; retry setup.")
        write_json(environment / READY, {
            "schema": SCHEMA, "fingerprint": expected, "extras": list(chosen), "installed": state, "mode": mode,
        })


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extras", help="add optional dependencies: audio, midi, audio,midi; previous choices are retained")
    parser.add_argument("--wheelhouse", type=Path, default=os.environ.get("TRIO_WHEELHOUSE"), help="offline dependency directory")
    parser.add_argument("--setup-only", action="store_true", help="prepare the installation without starting an instrument")
    parser.add_argument("--reinstall", action="store_true", help="repair/refresh this launcher-owned installation")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        target = Path(os.environ.get("TRIO_VENV", str(ROOT / ".trio-venv"))).expanduser().absolute()
        prepare(
            ROOT, target, extras=args.extras,
            wheelhouse=args.wheelhouse.expanduser().resolve() if args.wheelhouse else None,
            reinstall=args.reinstall,
        )
        if args.setup_only:
            return 0
        environment = clean_environment()
        environment["VIRTUAL_ENV"] = str(target)
        environment["PATH"] = str(command_path(target, args.command).parent) + os.pathsep + environment.get("PATH", "")
        return subprocess.call([str(command_path(target, args.command)), *args.arguments], env=environment)
    except (LaunchError, OSError) as error:
        print(f"TRIO: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nTRIO: interrupted; run the launcher again when ready.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
