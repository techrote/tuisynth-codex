"""Build and qualify a reproducible, unpublished TRIO release candidate.

Dependency acquisition is explicit: --prepare-wheelhouse downloads pinned wheels.
Every subsequent build and clean-install qualification uses --no-index. A candidate
is exported from one committed Git revision, never the mutable checkout contents.
"""
from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import venv
import wave
import zipfile
from email.parser import BytesParser
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
PACKAGES = ("kit", "aurora", "loom", "drift")
IMPORTS = {
    "kit": ("trio-kit", "trio_kit", "trio-demo"),
    "aurora": ("trio-aurora", "trio_aurora", "aurora"),
    "loom": ("trio-loom", "trio_loom", "loom"),
    "drift": ("trio-drift", "trio_drift", "drift"),
}
ZIP_EPOCH = 315532800  # 1980-01-01, the minimum ZIP timestamp.


class ReleaseError(RuntimeError):
    """A release gate failed; no candidate may be advertised as qualified."""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def clean_environment(wheelhouse: Path | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    # The acquisition phase owns network/index configuration. Qualification must
    # not inherit arbitrary requirement files, constraints, editables or redirects.
    for key in tuple(environment):
        if key.startswith("PIP_"):
            environment.pop(key)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONINSPECT", "PYTHONSTARTUP"):
        environment.pop(key, None)
    environment.update({"PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": os.devnull})
    if wheelhouse is not None:
        environment.update({"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(wheelhouse.resolve())})
    return environment


def run(command: Sequence[str | Path], *, cwd: Path, environment: dict[str, str] | None = None, timeout: int = 300) -> str:
    command = [str(argument) for argument in command]
    print("==> " + " ".join(command), flush=True)
    try:
        completed = subprocess.run(command, cwd=cwd, env=environment, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleaseError(f"could not complete {command[0]}: {error}") from error
    if completed.returncode:
        raise ReleaseError(f"command failed with exit code {completed.returncode}: {' '.join(command)}\n{completed.stdout}")
    return completed.stdout


def python_in(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def command_in(environment: Path, name: str) -> Path:
    return environment / (f"Scripts/{name}.exe" if os.name == "nt" else f"bin/{name}")


def require_wheelhouse(path: Path | None) -> Path:
    if path is None:
        value = os.environ.get("TRIO_WHEELHOUSE")
        path = Path(value) if value else None
    if path is None or not path.is_dir():
        raise ReleaseError("offline qualification needs --wheelhouse DIR (or TRIO_WHEELHOUSE); first run tools/release.py --prepare-wheelhouse DIR")
    return path.resolve()


def prepare_wheelhouse(destination: Path, source: Path = ROOT, *, extras: Sequence[str] = ()) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    # Acquisition is the sole network-enabled phase. Tests/build/install never download.
    environment = os.environ.copy()
    environment.pop("PIP_NO_INDEX", None)
    optional = tomllib.loads((source / "kit" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    if any(extra not in optional for extra in extras):
        raise ReleaseError("extras must contain only audio and/or midi")
    extra_requirements = [requirement for extra in extras for requirement in optional[extra]]
    run([sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--dest", destination.resolve(), "-r", source / "requirements-release.txt", *extra_requirements], cwd=source, environment=environment)
    manifest = {path.name: digest(path) for path in sorted(destination.glob("*.whl"))}
    (destination / "WHEELHOUSE.json").write_bytes(json_bytes(manifest))
    print(f"Prepared {len(manifest)} dependency wheels in {destination}")


def source_files(source: Path, package: str) -> dict[str, Path]:
    _, import_name, _ = IMPORTS[package]
    folder = source / package / "src" / import_name
    files: dict[str, Path] = {}
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if path.is_file() and "__pycache__" not in relative.parts and not path.name.endswith((".pyc", ".pyo")):
            if path.is_symlink():
                raise ReleaseError(f"package source contains a symlink: {path}")
            files[f"{import_name}/{relative.as_posix()}"] = path
    if f"{import_name}/__init__.py" not in files:
        raise ReleaseError(f"missing package source for {package}")
    return files


def build_wheels(source: Path, output: Path, *, wheelhouse: Path | None, epoch: int = ZIP_EPOCH, packages: Sequence[str] = PACKAGES) -> list[Path]:
    """Build clean wheels with a fresh, fully pinned, offline build environment."""
    source, output = source.resolve(), output.resolve()
    wheelhouse = require_wheelhouse(wheelhouse)
    if output.exists() and any(output.iterdir()):
        raise ReleaseError(f"wheel output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    environment = clean_environment(wheelhouse)
    environment["SOURCE_DATE_EPOCH"] = str(max(ZIP_EPOCH, int(epoch)))
    environment["PYTHONHASHSEED"] = "0"
    with tempfile.TemporaryDirectory(prefix="trio-build-") as temporary:
        workspace = Path(temporary)
        build_environment = workspace / "venv"
        venv.EnvBuilder(with_pip=True).create(build_environment)
        python = python_in(build_environment)
        run([python, "-m", "pip", "install", "--no-index", "--find-links", wheelhouse, "-r", source / "requirements-release.txt"], cwd=workspace, environment=environment)
        for package in packages:
            if package not in PACKAGES:
                raise ReleaseError(f"unknown package {package!r}")
            # Copy only tracked/exported source and packaging metadata, never stale build
            # directories or egg-info left by editable installation in the caller's tree.
            project = workspace / package
            project.mkdir()
            shutil.copy2(source / package / "pyproject.toml", project / "pyproject.toml")
            for optional in ("README.md", "MANIFEST.in"):
                if (source / package / optional).is_file():
                    shutil.copy2(source / package / optional, project / optional)
            for name, path in source_files(source, package).items():
                target = project / "src" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
            run([python, "-m", "build", "--wheel", "--no-isolation", "--outdir", output, project], cwd=workspace, environment=environment)
    paths = sorted(output.glob("*.whl"))
    if len(paths) != len(packages):
        raise ReleaseError(f"expected {len(packages)} wheels, found {len(paths)}")
    return paths


def _normalized_requirement(value: str) -> str:
    from packaging.requirements import Requirement
    return str(Requirement(value))


def verify_wheels(source: Path, wheels: Path | Sequence[Path], *, packages: Sequence[str] = PACKAGES) -> dict[str, object]:
    """Verify all package bytes, metadata, entry points and wheel RECORD hashes."""
    paths = sorted(wheels.glob("*.whl")) if isinstance(wheels, Path) else sorted(wheels)
    if len(paths) != len(packages):
        raise ReleaseError(f"expected {len(packages)} wheels, found {len(paths)}")
    inventory: dict[str, object] = {}
    for package in packages:
        distribution, import_name, command = IMPORTS[package]
        expected_name = f"{distribution.replace('-', '_')}-{VERSION}-py3-none-any.whl"
        matches = [path for path in paths if path.name == expected_name]
        if len(matches) != 1:
            raise ReleaseError(f"missing or ambiguous wheel {expected_name}")
        path = matches[0]
        config = tomllib.loads((source / package / "pyproject.toml").read_text(encoding="utf-8"))
        project = config["project"]
        if project["name"] != distribution or project["version"] != VERSION or project["requires-python"] != ">=3.11":
            raise ReleaseError(f"incorrect source metadata for {package}")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name for name in names):
                raise ReleaseError(f"unsafe or duplicate wheel entries: {path.name}")
            expected = source_files(source, package)
            actual = {name for name in names if name.startswith(import_name + "/") and not name.endswith("/")}
            if actual != set(expected):
                raise ReleaseError(f"{package} wheel payload mismatch; missing={sorted(set(expected)-actual)}, extra={sorted(actual-set(expected))}")
            for name, original in expected.items():
                if archive.read(name) != original.read_bytes():
                    raise ReleaseError(f"{package} wheel bytes differ from source: {name}")
            metadata_prefix = f"{distribution.replace('-', '_')}-{VERSION}.dist-info/"
            if any(not name.startswith((import_name + "/", metadata_prefix)) for name in names):
                raise ReleaseError(f"unexpected top-level wheel payload in {package}")
            wheel_metadata = BytesParser().parsebytes(archive.read(metadata_prefix + "WHEEL"))
            if wheel_metadata["Wheel-Version"] != "1.0" or wheel_metadata["Root-Is-Purelib"] != "true" or wheel_metadata.get_all("Tag") != ["py3-none-any"]:
                raise ReleaseError(f"incorrect wheel compatibility metadata for {package}")
            metadata = BytesParser().parsebytes(archive.read(metadata_prefix + "METADATA"))
            if metadata["Name"] != distribution or metadata["Version"] != VERSION or metadata["Requires-Python"] != ">=3.11":
                raise ReleaseError(f"incorrect wheel metadata for {package}")
            expected_requirements = {_normalized_requirement(value) for value in project.get("dependencies", [])}
            for extra, dependencies in project.get("optional-dependencies", {}).items():
                expected_requirements.update(_normalized_requirement(f'{value}; extra == "{extra}"') for value in dependencies)
            actual_requirements = {_normalized_requirement(value) for value in metadata.get_all("Requires-Dist", [])}
            if actual_requirements != expected_requirements:
                raise ReleaseError(f"incorrect dependency metadata for {package}")
            entry_points = configparser.ConfigParser()
            entry_points.read_string(archive.read(metadata_prefix + "entry_points.txt").decode("utf-8"))
            if dict(entry_points["console_scripts"]) != project["scripts"] or command not in entry_points["console_scripts"]:
                raise ReleaseError(f"incorrect console entry points for {package}")
            records = list(csv.reader(io.StringIO(archive.read(metadata_prefix + "RECORD").decode("utf-8"))))
            if len(records) != len(names) or {row[0] for row in records} != set(names):
                raise ReleaseError(f"wheel RECORD inventory differs for {package}")
            for name, encoded, size in records:
                if name == metadata_prefix + "RECORD":
                    if encoded or size:
                        raise ReleaseError(f"RECORD must not hash itself: {package}")
                    continue
                data = archive.read(name)
                calculated = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
                if encoded != calculated or size != str(len(data)):
                    raise ReleaseError(f"incorrect wheel RECORD digest: {name}")
            inventory[distribution] = {"wheel": path.name, "sha256": digest(path), "payload_files": len(expected), "presets": sum("/data/presets/" in name for name in expected), "skins": sum("/data/skins/" in name for name in expected)}
    return inventory


def qualify_install(source: Path, wheels: Path | Sequence[Path], *, wheelhouse: Path | None, packages: Sequence[str] = PACKAGES) -> dict[str, object]:
    """Co-install wheels in a new venv and exercise real commands outside source."""
    wheelhouse = require_wheelhouse(wheelhouse)
    paths = sorted(wheels.glob("*.whl")) if isinstance(wheels, Path) else sorted(wheels)
    paths = [path.resolve() for path in paths]
    source = source.resolve()
    environment = clean_environment(wheelhouse)
    environment.pop("NO_COLOR", None)
    report: dict[str, object] = {"python": platform.python_version(), "platform": platform.system(), "packages": {}}
    with tempfile.TemporaryDirectory(prefix="trio-installed-") as temporary:
        workspace = Path(temporary)
        installation = workspace / "venv"
        venv.EnvBuilder(with_pip=True).create(installation)
        python = python_in(installation)
        run([python, "-m", "pip", "install", "--no-index", "--find-links", wheelhouse, "pip==25.3"], cwd=workspace, environment=environment)
        run([python, "-m", "pip", "install", "--no-index", "--find-links", wheelhouse, "--constraint", source / "requirements-release.txt", *paths], cwd=workspace, environment=environment)
        report["pip_check"] = run([python, "-m", "pip", "check"], cwd=workspace, environment=environment).strip()
        report["installed_distributions"] = json.loads(run([python, "-m", "pip", "list", "--format=json"], cwd=workspace, environment=environment))
        for package in packages:
            distribution, import_name, command = IMPORTS[package]
            expected = {name.split("/", 1)[1]: digest(path) for name, path in source_files(source, package).items()}
            evidence = workspace / f"{package}-expected.json"
            evidence.write_bytes(json_bytes(expected))
            # -I plus a clean venv prohibits editable/PYTHONPATH/source-checkout leaks.
            script = (
                "import hashlib,importlib,importlib.metadata,json,pathlib,sys; "
                f"module=importlib.import_module({import_name!r}); "
                "location=pathlib.Path(module.__file__).resolve(); "
                "assert location.is_relative_to(pathlib.Path(sys.prefix).resolve()),location; "
                f"assert not location.is_relative_to(pathlib.Path({str(source)!r})),location; "
                f"assert importlib.metadata.version({distribution!r}) == {VERSION!r}; "
                f"assert module.__version__ == {VERSION!r}; "
                f"expected=json.loads(pathlib.Path({str(evidence)!r}).read_text()); "
                "base=location.parent; "
                "assert all(hashlib.sha256((base/name).read_bytes()).hexdigest()==sha for name,sha in expected.items()); "
                "print('installed source/resource hashes verified: '+str(len(expected)))"
            )
            import_result = run([python, "-I", "-c", script], cwd=workspace, environment=environment).strip()
            executable = command_in(installation, command)
            data = workspace / (package + " user data")
            data.mkdir()
            def invoke(*arguments: str | Path) -> str:
                return run([executable, *arguments, "--data-dir", data], cwd=workspace, environment=environment)
            version = invoke("--version").strip()
            if version != f"{command} {VERSION}":
                raise ReleaseError(f"unexpected installed version: {version!r}")
            selftest = invoke("--selftest")
            listed_presets = {line.split("\t", 1)[0] for line in invoke("--list-presets").splitlines() if line}
            presets_root = source / package / "src" / import_name / "data" / "presets"
            expected_presets = {json.loads(path.read_text(encoding="utf-8"))["id"] for path in presets_root.rglob("*.json")}
            if listed_presets != expected_presets:
                raise ReleaseError(f"{command} installed factory preset mismatch: {sorted(listed_presets ^ expected_presets)}")
            listed_skins = set(invoke("--list-skins").splitlines())
            expected_skins = {"mono"} | {path.stem for path in (source / package / "src" / import_name / "data" / "skins").glob("*.toml")}
            if listed_skins != expected_skins:
                raise ReleaseError(f"{command} installed factory skin mismatch: {sorted(listed_skins ^ expected_skins)}")
            expected_selftest = f"selftest passed: {len(expected_presets)} presets, {len(expected_skins)} skins, {2 * len(expected_presets)} offline render-seconds"
            if selftest.strip() != expected_selftest:
                raise ReleaseError(f"{command} did not report complete installed selftest success: {selftest!r}")
            snapshot_arguments = ["--snapshot", "80x24"]
            if package == "drift":
                snapshot_arguments += ["--screen", "grain", "--skin", "squall"]
            snapshot = invoke(*snapshot_arguments)
            if package == "drift" and any(marker not in snapshot for marker in ("GRAIN", "DRIFT", "squall")):
                raise ReleaseError("installed drift snapshot omitted GRAIN, DRIFT or squall")
            if not snapshot.strip():
                raise ReleaseError(f"empty installed snapshot for {command}")
            render = workspace / f"{package} smoke.wav"
            invoke("--render", render, "--notes", "C4", "--seconds", "0.05")
            with wave.open(str(render), "rb") as recording:
                frames = recording.getnframes()
                samples = recording.readframes(frames)
                if frames <= 0 or not any(samples):
                    raise ReleaseError(f"{command} produced an empty or silent offline WAV")
                render_details = {"frames": frames, "sample_rate": recording.getframerate(), "channels": recording.getnchannels(), "sample_width": recording.getsampwidth()}
            report["packages"][distribution] = {"version": version, "imports": import_result, "selftest": selftest.strip(), "presets": sorted(listed_presets), "skins": sorted(listed_skins), "snapshot_sha256": hashlib.sha256(snapshot.encode("utf-8")).hexdigest(), "offline_render": render_details}
    return report


def revision_info(repository: Path, revision: str) -> dict[str, object]:
    if revision.startswith("-"):
        raise ReleaseError("revision must not begin with '-'")
    commit = run(["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=repository).strip()
    tree = run(["git", "rev-parse", commit + "^{tree}"], cwd=repository).strip()
    epoch = int(run(["git", "show", "-s", "--format=%ct", commit], cwd=repository).strip())
    return {"commit": commit, "tree": tree, "source_date_epoch": max(ZIP_EPOCH, epoch)}


def export_source(repository: Path, commit: str, destination: Path, *, modes: dict[str, int] | None = None) -> dict[str, str]:
    """Export exact Git blobs without checkout line-ending/smudge transformations."""
    destination.mkdir(parents=True, exist_ok=True)
    listing = subprocess.run(["git", "ls-tree", "-r", "-z", commit], cwd=repository, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    entries: dict[str, str] = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        attributes, raw_name = record.split(b"\t", 1)
        mode, kind, oid = attributes.decode("ascii").split()
        name = raw_name.decode("utf-8")
        path = PurePosixPath(name)
        if kind != "blob" or mode not in {"100644", "100755"} or path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ReleaseError(f"unsupported or unsafe source entry: {name}")
        data = subprocess.run(["git", "cat-file", "blob", oid], cwd=repository, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        target = destination.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if mode == "100755" else 0o644)
        entries[name] = hashlib.sha256(data).hexdigest()
        if modes is not None:
            modes[name] = 0o755 if mode == "100755" else 0o644
    return entries


def deterministic_zip(destination: Path, files: dict[str, Path | bytes], *, epoch: int, file_modes: dict[str, int] | None = None) -> None:
    timestamp = time.gmtime(max(ZIP_EPOCH, min(epoch, 4354819198)))[:6]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, value in sorted(files.items()):
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ReleaseError(f"unsafe archive name: {name}")
            info = zipfile.ZipInfo(name, timestamp)
            info.create_system = 3
            executable = bool(file_modes.get(name, 0o644) & 0o111) if file_modes is not None else isinstance(value, Path) and bool(value.stat().st_mode & 0o111)
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value.read_bytes() if isinstance(value, Path) else value, compresslevel=9)


def write_checksums(directory: Path, *, names: Sequence[str] | None = None) -> dict[str, str]:
    files = sorted(path for path in directory.iterdir() if path.is_file() and path.name != "SHA256SUMS") if names is None else [directory / name for name in sorted(names)]
    checksums = {path.name: digest(path) for path in files}
    (directory / "SHA256SUMS").write_text("".join(f"{checksum}  {name}\n" for name, checksum in checksums.items()), encoding="utf-8", newline="\n")
    return checksums


def verify_checksums(directory: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in (directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9_.-]*)", line)
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
        if match is None or match[2] == "SHA256SUMS" or match[2].endswith(".") or match[2].split(".", 1)[0].upper() in reserved or match[2] in checksums:
            raise ReleaseError("malformed or unsafe checksum manifest")
        sha, name = match.groups()
        path = directory / name
        if not path.is_file() or path.is_symlink() or digest(path) != sha:
            raise ReleaseError(f"checksum mismatch: {name}")
        checksums[name] = sha
    if not checksums:
        raise ReleaseError("empty checksum manifest")
    actual = {path.name for path in directory.iterdir() if path.name != "SHA256SUMS"}
    if actual != set(checksums):
        raise ReleaseError("checksum manifest does not cover the complete artifact directory")
    return checksums


def validate_output_location(repository: Path, output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise ReleaseError(f"candidate output must be empty: {output}")
    if output.is_relative_to(repository):
        relative = output.relative_to(repository).as_posix()
        ignored = subprocess.run(["git", "check-ignore", "--no-index", "--quiet", "--", relative], cwd=repository, check=False)
        if ignored.returncode != 0:
            raise ReleaseError("candidate output inside the checkout must be Git-ignored (for example dist/release)")


def create_candidate(repository: Path, revision: str, output: Path, *, wheelhouse: Path | None) -> dict[str, object]:
    repository, output = repository.resolve(), output.resolve()
    wheelhouse = require_wheelhouse(wheelhouse)
    validate_output_location(repository, output)
    dirty = run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=repository).strip()
    if dirty:
        raise ReleaseError("release requires a clean checkout; commit changes before qualification")
    info = revision_info(repository, revision)
    tool_source = run(["git", "show", f"{info['commit']}:tools/release.py"], cwd=repository)
    if tool_source.replace("\r\n", "\n") != Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n"):
        raise ReleaseError("run the release tool from the requested source revision")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trio-release-") as temporary:
        workspace = Path(temporary)
        source_a, source_b = workspace / "source-a", workspace / "source-b"
        modes: dict[str, int] = {}
        hashes = export_source(repository, str(info["commit"]), source_a, modes=modes)
        if hashes != export_source(repository, str(info["commit"]), source_b):
            raise ReleaseError("Git export reproducibility mismatch")
        stage = workspace / "candidate"
        stage.mkdir()
        wheels_a, wheels_b = stage / "wheels", workspace / "rebuild"
        first = build_wheels(source_a, wheels_a, wheelhouse=wheelhouse, epoch=int(info["source_date_epoch"]))
        second = build_wheels(source_b, wheels_b, wheelhouse=wheelhouse, epoch=int(info["source_date_epoch"]))
        first_hashes = {path.name: digest(path) for path in first}
        if first_hashes != {path.name: digest(path) for path in second}:
            raise ReleaseError("independent clean wheel builds are not byte-for-byte reproducible")
        inventory = verify_wheels(source_a, first)
        qualification = qualify_install(source_a, first, wheelhouse=wheelhouse)
        qualification.update({"source_commit": info["commit"], "source_tree": info["tree"], "reproducible_wheels": first_hashes, "physical_acceptance": "not performed; see docs/ACCEPTANCE.md"})
        source_record = {"schema_version": 1, "project": "TRIO", "version": VERSION, "status": "unpublished release candidate; Draft/HOLD", **info, "source_files_sha256": hashes, "source_file_modes": {name: format(mode, "04o") for name, mode in modes.items()}, "wheels": inventory, "build_requirements": (source_a / "requirements-release.txt").read_text(encoding="utf-8"), "toolchain": {"python": platform.python_version(), "platform": platform.system()}, "dependency_wheels_sha256": {path.name: digest(path) for path in sorted(wheelhouse.glob("*.whl"))}, "physical_acceptance": "not performed; see docs/ACCEPTANCE.md"}
        (stage / "SOURCE.json").write_bytes(json_bytes(source_record))
        (stage / "QUALIFICATION.json").write_bytes(json_bytes(qualification))
        short = str(info["commit"])[:12]
        source_archive = stage / f"trio-{VERSION}-source-{short}.zip"
        archive_files = {name: source_a / name for name in hashes}
        deterministic_zip(source_archive, archive_files, epoch=int(info["source_date_epoch"]), file_modes=modes)
        source_rebuild = workspace / "source-rebuild.zip"
        deterministic_zip(source_rebuild, {name: source_b / name for name in hashes}, epoch=int(info["source_date_epoch"]), file_modes=modes)
        if digest(source_archive) != digest(source_rebuild):
            raise ReleaseError("source ZIP reproducibility mismatch")
        # Candidate extraction gives source, launchers, and the four already-built wheels.
        candidate_files = dict(archive_files)
        candidate_files.update({f"wheels/{path.name}": path for path in first})
        for name in ("SOURCE.json", "QUALIFICATION.json"):
            candidate_files[name] = stage / name
        inner_manifest = "".join(f"{sha}  {name}\n" for name, sha in sorted(first_hashes.items()))
        candidate_files["wheels/SHA256SUMS"] = inner_manifest.encode("utf-8")
        candidate = stage / f"trio-{VERSION}-candidate-{short}.zip"
        deterministic_zip(candidate, candidate_files, epoch=int(info["source_date_epoch"]), file_modes=modes)
        candidate_rebuild = workspace / "candidate-rebuild.zip"
        rebuild_files = dict(candidate_files)
        rebuild_files.update({name: source_b / name for name in hashes})
        rebuild_files.update({f"wheels/{path.name}": path for path in second})
        deterministic_zip(candidate_rebuild, rebuild_files, epoch=int(info["source_date_epoch"]), file_modes=modes)
        if digest(candidate) != digest(candidate_rebuild):
            raise ReleaseError("candidate ZIP reproducibility mismatch")
        (stage / "REPRODUCIBILITY.json").write_bytes(json_bytes({
            "source_commit": info["commit"],
            "scope": "Two clean Git exports and independent pinned-toolchain wheel builds; source and candidate ZIPs reconstructed with canonical Git modes. Candidate reconstructions share the same qualification record. Comparisons are within one OS/Python/toolchain lane, not across different lanes.",
            "matching_sha256": {**first_hashes, source_archive.name: digest(source_archive), candidate.name: digest(candidate)},
        }))
        # Four standalone wheels are convenient for pip and independent inspection.
        for wheel in first:
            shutil.copy2(wheel, stage / wheel.name)
        shutil.rmtree(wheels_a)
        checksums = write_checksums(stage)
        verify_checksums(stage)
        if output.exists():
            output.rmdir()
        shutil.copytree(stage, output)
        verify_checksums(output)
    print(f"Qualified unpublished candidate for {info['commit']}: {output}")
    return {**info, "output": str(output), "checksums": checksums}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD", help="committed release source revision")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "release")
    parser.add_argument("--wheelhouse", type=Path, help="prefetched dependency wheels; no network during build/install")
    parser.add_argument("--prepare-wheelhouse", type=Path, metavar="DIR", help="download pinned dependency wheels, then exit")
    parser.add_argument("--extras", default="", help="comma-separated audio,midi wheels to acquire with --prepare-wheelhouse")
    parser.add_argument("--verify", type=Path, metavar="DIR", help="verify an artifact directory's SHA256SUMS, then exit")
    parser.add_argument("--reproducible", action="store_true", help="compatibility spelling; two-build reproducibility is always required")
    arguments = parser.parse_args(argv)
    try:
        if arguments.prepare_wheelhouse is not None:
            prepare_wheelhouse(arguments.prepare_wheelhouse, extras=tuple(extra.strip() for extra in arguments.extras.split(",") if extra.strip()))
        elif arguments.extras:
            raise ReleaseError("--extras is only valid with --prepare-wheelhouse")
        elif arguments.verify is not None:
            verify_checksums(arguments.verify)
            print("Artifact SHA-256 checksums verified")
        else:
            create_candidate(ROOT, arguments.revision, arguments.output, wheelhouse=arguments.wheelhouse)
    except (ReleaseError, OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
