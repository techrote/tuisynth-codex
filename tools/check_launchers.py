"""Exercise the real platform wrapper in isolated source and wheel installations.

Dependencies must have been acquired in a separate step. This check uses no
network, real audio/MIDI devices, source imports, or the caller's installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import wave
import zipfile


ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ("trio-demo", "aurora", "loom", "drift")
PACKAGES = ("kit", "aurora", "loom", "drift")


def source_identity() -> dict:
    try:
        def git(*arguments: str) -> str:
            return subprocess.run(
                ["git", *arguments], cwd=ROOT, capture_output=True, text=True,
                check=True, timeout=30,
            ).stdout.strip()
        return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"), "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "tree": None, "dirty": None, "note": "No Git metadata available; use the recorded per-file hashes."}


def run_launcher(root: Path, wheelhouse: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in ("TRIO_VENV", "TRIO_WHEELHOUSE", "TRIO_PYTHON", "PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    # Exercise ordinary selection while respecting setup-python's matrix lane.
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    environment.update({"PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    wrapper = [str(root / "launch.cmd")] if os.name == "nt" else ["sh", str(root / "launch.sh")]
    result = subprocess.run(
        [*wrapper, "--wheelhouse", str(wheelhouse), *arguments],
        cwd=root.parent, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Launcher {arguments!r} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result


def copy_inputs(root: Path, destination: Path, *, wheels: Path | None) -> None:
    (destination / "tools").mkdir(parents=True)
    for path in ("launch.sh", "launch.cmd", "tools/launch.py", "requirements-release.txt", "README.md"):
        shutil.copy2(root / path, destination / path)
    if wheels is not None:
        (destination / "wheels").mkdir()
        for path in wheels.glob("trio_*.whl"):
            shutil.copy2(path, destination / "wheels" / path.name)
    else:
        for package in PACKAGES:
            shutil.copytree(
                root / package, destination / package,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", "build", "dist", ".pytest_cache"),
            )


def fallback_selector_report(root: Path) -> dict:
    """Probe the actual fallback without silently selecting it for a CI lane."""
    with tempfile.TemporaryDirectory(prefix="TRIO interpreter fallback ") as temporary:
        directory = Path(temporary)
        environment = os.environ.copy()
        for name in ("TRIO_PYTHON", "PYTHONHOME", "PYTHONPATH"):
            environment.pop(name, None)
        environment["PATH"] = str(directory)
        if os.name == "nt":
            launcher = shutil.which("py")
            if launcher is None or Path(launcher).suffix.lower() != ".exe":
                return {"selector": "py -3", "status": "unavailable", "scope": "No native py.exe found; no successful fallback claim."}
            shutil.copy2(launcher, directory / "py.exe")
            shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "where.exe", directory / "where.exe")
            interpreter = [str(directory / "py.exe"), "-3"]
            wrapper = [str(root / "launch.cmd")]
        else:
            (directory / "python").symlink_to(sys.executable)
            (directory / "dirname").symlink_to(str(shutil.which("dirname")))
            interpreter = [str(directory / "python")]
            wrapper = [str(shutil.which("sh")), str(root / "launch.sh")]
        probe = subprocess.run(
            [*interpreter, "-c", "import json,sys; print(json.dumps(list(sys.version_info[:3]))); sys.exit(0 if sys.version_info >= (3,11) else 1)"],
            env=environment, cwd=root.parent, capture_output=True, text=True, timeout=30, check=False,
        )
        if probe.returncode:
            return {"selector": "py -3" if os.name == "nt" else "python", "status": "unavailable or unsupported", "scope": "No successful fallback claim."}
        result = subprocess.run(
            [*wrapper, "--help"], env=environment, cwd=root.parent,
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode or "Create/reuse an owned local TRIO environment" not in result.stdout:
            raise RuntimeError(f"Real fallback interpreter failed through the platform wrapper: {result.stdout}\n{result.stderr}")
        return {"selector": "py -3" if os.name == "nt" else "python", "status": "pass", "python": json.loads(probe.stdout), "scope": "Actual fallback interpreter runs wrapper help; installed selftests use the matrix PATH interpreter."}


def safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name or "\\" in name or ":" in name or path.is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise RuntimeError(f"Unsafe candidate archive path: {name!r}")
    return path


def extract_candidate(candidate: Path, destination: Path, wheels: Path, expected_commit: str | None) -> dict:
    """Unpack exact published bytes, rejecting traversal, links and duplicates."""
    destination.mkdir(parents=True)
    seen = set()
    with zipfile.ZipFile(candidate) as archive:
        if sum(info.file_size for info in archive.infolist()) > 256 * 1024 * 1024:
            raise RuntimeError("Candidate archive exceeds the bounded qualification size")
        for info in archive.infolist():
            relative = safe_relative(info.filename)
            if info.filename.casefold() in seen:
                raise RuntimeError(f"Duplicate candidate archive path: {info.filename}")
            seen.add(info.filename.casefold())
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise RuntimeError(f"Candidate archive must contain regular files: {info.filename}")
            path = destination.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(info))
            if os.name != "nt" and mode & 0o111:
                path.chmod(0o755)
    record = json.loads((destination / "SOURCE.json").read_text(encoding="utf-8"))
    if expected_commit is not None and record.get("commit") != expected_commit:
        raise RuntimeError("Candidate SOURCE.json commit does not match the checked-out qualification revision")
    hashes = record.get("source_files_sha256", {})
    for name in ("launch.sh", "launch.cmd", "tools/launch.py", "requirements-release.txt"):
        if name not in hashes:
            raise RuntimeError(f"Candidate source record does not identify {name}")
    for name, expected in hashes.items():
        path = destination.joinpath(*safe_relative(name).parts)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Candidate source hash mismatch: {name}")
    wheel_inventory = record.get("wheels", {})
    if set(wheel_inventory) != {f"trio-{package}" for package in PACKAGES}:
        raise RuntimeError("Candidate source record does not identify all four distributions")
    for item in wheel_inventory.values():
        name = item["wheel"]
        if len(safe_relative(name).parts) != 1:
            raise RuntimeError("Candidate wheel name must be a filename")
        for path in (destination / "wheels" / name, wheels / name):
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Candidate wheel hash mismatch: {path.name}")
    expected_names = set(hashes) | {f"wheels/{item['wheel']}" for item in wheel_inventory.values()} | {"SOURCE.json", "QUALIFICATION.json", "wheels/SHA256SUMS"}
    if seen != {name.casefold() for name in expected_names}:
        raise RuntimeError("Candidate archive contains missing or unrecorded files")
    for name in ("SOURCE.json", "QUALIFICATION.json"):
        adjacent = candidate.parent / name
        if adjacent.is_file() and adjacent.read_bytes() != (destination / name).read_bytes():
            raise RuntimeError(f"Candidate {name} differs from its standalone release record")
    manifest = candidate.parent / "SHA256SUMS"
    archive_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if manifest.is_file():
        entries = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in manifest.read_text(encoding="utf-8").splitlines()}
        if entries.get(candidate.name) != archive_hash:
            raise RuntimeError("Candidate archive SHA256SUMS mismatch")
    return {"archive": candidate.name, "sha256": archive_hash, "commit": record.get("commit"), "source_and_wheel_hashes": "pass"}


def check_mode(root: Path, wheelhouse: Path, *, mode: str, extras: str) -> dict:
    input_hashes = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }
    if os.name != "nt":
        subprocess.run(["sh", "-n", str(root / "launch.sh")], check=True, timeout=10)
    setup = run_launcher(root, wheelhouse, ["--setup-only", "aurora"])
    if "setting up" not in setup.stderr:
        raise RuntimeError(f"{mode}: first launch did not set up a new environment")
    marker_path = root / ".trio-venv" / ".trio-ready.json"
    marker_bytes, marker_time = marker_path.read_bytes(), marker_path.stat().st_mtime_ns
    marker = json.loads(marker_bytes)
    if marker["mode"] != mode or marker["extras"]:
        raise RuntimeError(f"{mode}: base setup selected unexpected mode or optional dependencies")
    if marker["installed"]["python"] != list(sys.version_info[:3]):
        raise RuntimeError(f"{mode}: default wrapper did not select the requested CI Python interpreter")
    if any(name in marker["installed"]["versions"] for name in ("sounddevice", "mido", "python-rtmidi")):
        raise RuntimeError(f"{mode}: base setup unexpectedly installed device backends")
    results = {}
    for command in COMMANDS:
        version = run_launcher(root, wheelhouse, [command, "--version"])
        if version.stdout.strip() != f"{command} 0.1.0" or "reusing" not in version.stderr:
            raise RuntimeError(f"{mode}: installed {command} version/reuse check failed")
        selftest = run_launcher(root, wheelhouse, [command, "--selftest", "--data-dir", str(root.parent / f"{mode} user data" / command)])
        if "selftest passed:" not in selftest.stdout:
            raise RuntimeError(f"{mode}: installed {command} selftest did not report success")
        results[command] = selftest.stdout.strip()
    output = root.parent / f"{mode} render with spaces.wav"
    run_launcher(root, wheelhouse, ["aurora", "--render", str(output), "--seconds", "0.05", "--seed", "7", "--data-dir", str(root.parent / f"{mode} user data" / "aurora")])
    with wave.open(str(output), "rb") as stream:
        if stream.getnchannels() != 2 or stream.getnframes() != 2400:
            raise RuntimeError(f"{mode}: forwarded render path/arguments produced unexpected WAV")
    if marker_path.read_bytes() != marker_bytes or marker_path.stat().st_mtime_ns != marker_time:
        raise RuntimeError(f"{mode}: unchanged launches unnecessarily changed the installation")
    if extras:
        run_launcher(root, wheelhouse, ["--extras", extras, "--setup-only", "aurora"])
        optional = json.loads(marker_path.read_text(encoding="utf-8"))
        selected = set(extras.split(","))
        expected_packages = ({"sounddevice"} if "audio" in selected else set()) | ({"mido", "python-rtmidi"} if "midi" in selected else set())
        if not expected_packages <= optional["installed"]["versions"].keys():
            raise RuntimeError(f"{mode}: selected optional packages were not installed")
        repeated = run_launcher(root, wheelhouse, ["drift", "--version"])
        if "reusing" not in repeated.stderr:
            raise RuntimeError(f"{mode}: repeated optional installation was not reused")
    installed = json.loads(marker_path.read_text(encoding="utf-8"))["installed"]["versions"]
    return {
        "mode": mode, "first_setup": "pass", "repeat_reuse": "pass", "outside_checkout": True,
        "interpreter_selection": "default PATH; TRIO_PYTHON unset; CI interpreter directory first",
        "fallback_selector": fallback_selector_report(root),
        "installed_selftests": results, "argument_forwarding": "pass",
        "render_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "input_sha256": input_hashes,
        "wheel_sha256": {name.removeprefix("wheels/"): value for name, value in input_hashes.items() if name.startswith("wheels/")},
        "optional_extras": extras or "not requested", "physical_audio_midi": "not exercised",
        "installed_versions": installed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True, help="directory containing the four built real TRIO wheels")
    parser.add_argument("--candidate", type=Path, help="exact candidate ZIP to extract and exercise (auto-detected in --wheels when present)")
    parser.add_argument("--extras", default="", choices=("", "audio", "midi", "audio,midi"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        wheelhouse, wheels = args.wheelhouse.resolve(), args.wheels.resolve()
        if not wheelhouse.is_dir() or not wheels.is_dir():
            raise RuntimeError("wheelhouse and wheels must both be existing directories")
        report = {"source": source_identity(), "python": sys.version, "platform": sys.platform, "hardware_acceptance": "not performed", "modes": []}
        candidates = [args.candidate.resolve()] if args.candidate else sorted(wheels.glob("*-candidate-*.zip"))
        if len(candidates) > 1:
            raise RuntimeError("Multiple candidate archives found; select one with --candidate")
        report["candidate"] = {"archive_tested": False, "note": "No candidate ZIP provided; local development wheels only."}
        with tempfile.TemporaryDirectory(prefix="TRIO launcher qualification ") as temporary:
            workspace = Path(temporary)
            for mode in ("source", "wheels"):
                bundle = workspace / f"{mode} bundle with spaces"
                if mode == "wheels" and candidates:
                    report["candidate"] = {"archive_tested": True, **extract_candidate(candidates[0], bundle, wheels, report["source"]["commit"])}
                else:
                    copy_inputs(ROOT, bundle, wheels=wheels if mode == "wheels" else None)
                report["modes"].append(check_mode(bundle, wheelhouse, mode=mode, extras=args.extras))
                print(f"TRIO launcher qualification: {mode} PASS", flush=True)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("TRIO launcher qualification: source and wheels PASS; physical acceptance remains unperformed.")
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, zipfile.BadZipFile, KeyError) as error:
        print(f"TRIO launcher qualification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
