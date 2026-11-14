"""Release regressions use real ZIP/Git/filesystem data and never use a network."""
from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("trio_release", ROOT / "tools" / "release.py")
assert SPEC and SPEC.loader
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


@pytest.fixture
def packaged_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    for package in RELEASE.PACKAGES:
        target = source / package
        target.mkdir(parents=True)
        shutil.copyfile(ROOT / package / "pyproject.toml", target / "pyproject.toml")
        _, import_name, _ = RELEASE.IMPORTS[package]
        shutil.copytree(ROOT / package / "src" / import_name, target / "src" / import_name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return source


def make_wheel(source: Path, directory: Path, package: str = "kit", *, mutate=None, bad_record: bool = False) -> Path:
    """Create a standards-shaped fixture independently of the release verifier."""
    project = tomllib.loads((source / package / "pyproject.toml").read_text())["project"]
    name = project["name"].replace("-", "_")
    prefix = f"{name}-0.1.0.dist-info/"
    payload = {path.relative_to(source / package / "src").as_posix(): path.read_bytes() for path in (source / package / "src").rglob("*") if path.is_file()}
    metadata = f"Metadata-Version: 2.4\nName: {project['name']}\nVersion: 0.1.0\nRequires-Python: >=3.11\n"
    for requirement in project["dependencies"]:
        metadata += f"Requires-Dist: {requirement}\n"
    for extra, requirements in project.get("optional-dependencies", {}).items():
        metadata += f"Provides-Extra: {extra}\n"
        for requirement in requirements:
            metadata += f'Requires-Dist: {requirement}; extra == "{extra}"\n'
    payload[prefix + "METADATA"] = metadata.encode()
    payload[prefix + "WHEEL"] = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    payload[prefix + "entry_points.txt"] = ("[console_scripts]\n" + "".join(f"{command} = {entry}\n" for command, entry in project["scripts"].items())).encode()
    if mutate:
        mutate(payload)
    rows = []
    for filename, value in sorted(payload.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip("=")
        rows.append((filename, "sha256=" + ("incorrect" if bad_record else digest), str(len(value))))
    rows.append((prefix + "RECORD", "", ""))
    record = io.StringIO(newline="")
    csv.writer(record).writerows(rows)
    payload[prefix + "RECORD"] = record.getvalue().encode()
    directory.mkdir(exist_ok=True)
    path = directory / f"{name}-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for filename, value in payload.items():
            archive.writestr(filename, value)
    return path


def test_all_four_wheels_verify_complete_code_assets_metadata_and_records(packaged_source: Path, tmp_path: Path) -> None:
    wheels = [make_wheel(packaged_source, tmp_path / "wheels", package) for package in RELEASE.PACKAGES]
    result = RELEASE.verify_wheels(packaged_source, wheels)
    assert set(result) == {"trio-kit", "trio-aurora", "trio-loom", "trio-drift"}
    assert [result[f"trio-{name}"]["presets"] for name in ("aurora", "loom", "drift")] == [8, 8, 8]
    assert result["trio-kit"]["presets"] == 2


@pytest.mark.parametrize("damage", ["missing-preset", "changed-code", "extra-code", "dependency", "entrypoint", "version", "record", "wheel-tag"])
def test_corrupted_or_stale_wheel_is_rejected(packaged_source: Path, tmp_path: Path, damage: str) -> None:
    def mutate(payload: dict[str, bytes]) -> None:
        if damage == "missing-preset":
            del payload["trio_kit/data/presets/demo/init.json"]
        elif damage == "changed-code":
            payload["trio_kit/__init__.py"] += b"\nSTALE = True\n"
        elif damage == "extra-code":
            payload["trio_kit/untracked.py"] = b"raise RuntimeError('untracked payload')"
        elif damage == "dependency":
            payload["trio_kit-0.1.0.dist-info/METADATA"] = payload["trio_kit-0.1.0.dist-info/METADATA"].replace(b"numpy>=2.4.3,<3", b"numpy>=1")
        elif damage == "entrypoint":
            payload["trio_kit-0.1.0.dist-info/entry_points.txt"] = b"[console_scripts]\ntrio-demo = missing:main\n"
        elif damage == "wheel-tag":
            payload["trio_kit-0.1.0.dist-info/WHEEL"] = b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp311-cp311-win_amd64\n"
        elif damage == "version":
            payload["trio_kit-0.1.0.dist-info/METADATA"] = payload["trio_kit-0.1.0.dist-info/METADATA"].replace(b"Version: 0.1.0", b"Version: 0.2.0")
    path = make_wheel(packaged_source, tmp_path / "wheels", mutate=mutate, bad_record=damage == "record")
    with pytest.raises(RELEASE.ReleaseError):
        RELEASE.verify_wheels(packaged_source, [path], packages=("kit",))


def test_wheel_verifier_rejects_a_missing_distribution(packaged_source: Path, tmp_path: Path) -> None:
    path = make_wheel(packaged_source, tmp_path / "wheels")
    with pytest.raises(RELEASE.ReleaseError, match="expected 4 wheels"):
        RELEASE.verify_wheels(packaged_source, [path])


def test_dependency_versions_are_exact_and_devices_are_opt_in() -> None:
    from packaging.requirements import Requirement
    requirements = [Requirement(line) for line in (ROOT / "requirements-release.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert {r.name for r in requirements} == {"pip", "build", "setuptools", "wheel", "packaging", "pyproject_hooks", "colorama", "numpy", "scipy", "prompt-toolkit", "wcwidth"}
    assert all(len(r.specifier) == 1 and next(iter(r.specifier)).operator == "==" for r in requirements)
    for package in RELEASE.PACKAGES:
        build = tomllib.loads((ROOT / package / "pyproject.toml").read_text())["build-system"]
        assert set(build["requires"]) <= {str(r) for r in requirements}


def test_manifest_detects_tampering_missing_files_and_unlisted_payloads(tmp_path: Path) -> None:
    payload = tmp_path / "trio.whl"
    payload.write_bytes(b"original wheel")
    original = RELEASE.write_checksums(tmp_path)
    assert RELEASE.verify_checksums(tmp_path) == original
    payload.write_bytes(b"corrupt wheel")
    with pytest.raises(RELEASE.ReleaseError, match="checksum mismatch"):
        RELEASE.verify_checksums(tmp_path)
    payload.unlink()
    with pytest.raises(RELEASE.ReleaseError, match="checksum mismatch"):
        RELEASE.verify_checksums(tmp_path)
    payload.write_bytes(b"original wheel")
    (tmp_path / "unlisted.exe").write_bytes(b"extra")
    with pytest.raises(RELEASE.ReleaseError, match="complete artifact directory"):
        RELEASE.verify_checksums(tmp_path)


@pytest.mark.parametrize("entry", ["../escape", "sub/file", r"sub\file", "SHA256SUMS", ".", "..", "C:payload", "CON", "nul.txt", "file.", "bad?"])
def test_manifest_rejects_unsafe_names(tmp_path: Path, entry: str) -> None:
    (tmp_path / "SHA256SUMS").write_text("0" * 64 + "  " + entry + "\n")
    with pytest.raises(RELEASE.ReleaseError, match="unsafe checksum"):
        RELEASE.verify_checksums(tmp_path)


def test_deterministic_archives_ignore_mtime_and_input_order(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"alpha\n")
    b.write_bytes(b"beta\n")
    one, two = tmp_path / "one.zip", tmp_path / "two.zip"
    RELEASE.deterministic_zip(one, {"a": a, "b": b}, epoch=1780000000)
    import os
    os.utime(a, (1800000000, 1800000000))
    RELEASE.deterministic_zip(two, {"b": b, "a": a}, epoch=1780000000)
    assert one.read_bytes() == two.read_bytes()
    with zipfile.ZipFile(one) as archive:
        assert archive.namelist() == ["a", "b"]


def test_archive_refuses_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(RELEASE.ReleaseError, match="unsafe archive"):
        RELEASE.deterministic_zip(tmp_path / "bad.zip", {"../outside": b"x"}, epoch=RELEASE.ZIP_EPOCH)


def git(repository: Path, *args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=repository, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def test_export_uses_exact_commit_blobs_not_changed_checkout_or_crlf(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "Release test")
    git(repository, "config", "user.email", "release-test@example.invalid")
    git(repository, "config", "core.autocrlf", "false")
    (repository / "asset.txt").write_bytes(b"original\n")
    git(repository, "add", "asset.txt")
    git(repository, "commit", "-qm", "fixture")
    commit = git(repository, "rev-parse", "HEAD").decode().strip()
    (repository / "asset.txt").write_bytes(b"changed\r\n")
    (repository / "untracked.txt").write_bytes(b"never package")
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert RELEASE.export_source(repository, commit, first) == RELEASE.export_source(repository, commit, second)
    assert (first / "asset.txt").read_bytes() == b"original\n"
    assert not (first / "untracked.txt").exists()
    assert RELEASE.revision_info(repository, commit)["commit"] == commit


def test_export_rejects_symlink_git_entries_without_following_them(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "Release test")
    git(repository, "config", "user.email", "release-test@example.invalid")
    oid = git(repository, "hash-object", "-w", "--stdin", input=b"../outside").decode().strip()
    git(repository, "update-index", "--add", "--cacheinfo", f"120000,{oid},link")
    git(repository, "commit", "-qm", "symlink fixture")
    with pytest.raises(RELEASE.ReleaseError, match="unsupported or unsafe"):
        RELEASE.export_source(repository, "HEAD", tmp_path / "export")


def test_release_fails_closed_without_prepared_wheelhouse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TRIO_WHEELHOUSE", raising=False)
    with pytest.raises(RELEASE.ReleaseError, match="prepare-wheelhouse"):
        RELEASE.require_wheelhouse(None)
    assert RELEASE.main(["--output", str(tmp_path / "candidate")]) == 1
    assert not (tmp_path / "candidate").exists()


def test_release_refuses_dirty_checkout_before_creating_artifacts(tmp_path: Path) -> None:
    repository, wheelhouse = tmp_path / "repository", tmp_path / "wheels"
    repository.mkdir()
    wheelhouse.mkdir()
    git(repository, "init", "-q")
    (repository / "untracked.txt").write_text("not committed")
    with pytest.raises(RELEASE.ReleaseError, match="clean checkout"):
        RELEASE.create_candidate(repository, "HEAD", tmp_path / "candidate", wheelhouse=wheelhouse)
    assert not (tmp_path / "candidate").exists()


def test_clean_environment_removes_source_and_pip_install_redirection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    forbidden = ("PYTHONPATH", "PYTHONHOME", "PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_EXTRA_INDEX_URL", "PIP_CONSTRAINT", "PIP_REQUIREMENT", "PIP_EDITABLE", "PIP_BUILD_CONSTRAINT", "PIP_FIND_LINKS", "PYTHONINSPECT", "PYTHONSTARTUP")
    for key in forbidden:
        monkeypatch.setenv(key, "hostile")
    environment = RELEASE.clean_environment(tmp_path)
    assert not any(key in environment for key in forbidden if key != "PIP_FIND_LINKS")
    assert environment["PIP_FIND_LINKS"] == str(tmp_path.resolve())
    assert environment["PIP_NO_INDEX"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_real_offline_pip_ignores_inherited_requirement_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in ("PIP_CONSTRAINT", "PIP_REQUIREMENT", "PIP_EDITABLE", "PIP_BUILD_CONSTRAINT"):
        monkeypatch.setenv(key, str(tmp_path / "must-not-be-opened.txt"))
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--dry-run", "--no-index", "pip"],
        env=RELEASE.clean_environment(tmp_path), cwd=tmp_path,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "must-not-be-opened" not in result.stdout + result.stderr


def test_subprocess_timeout_is_a_reported_release_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 1)
    monkeypatch.setattr(RELEASE.subprocess, "run", timeout)
    with pytest.raises(RELEASE.ReleaseError, match="could not complete"):
        RELEASE.run(["worker"], cwd=tmp_path)


def test_zip_preserves_explicit_git_executable_mode_on_any_host(tmp_path: Path) -> None:
    script = tmp_path / "launch.sh"
    script.write_bytes(b"#!/bin/sh\n")
    script.chmod(0o644)
    archive_path = tmp_path / "source.zip"
    RELEASE.deterministic_zip(archive_path, {"launch.sh": script}, epoch=RELEASE.ZIP_EPOCH, file_modes={"launch.sh": 0o755})
    with zipfile.ZipFile(archive_path) as archive:
        assert (archive.getinfo("launch.sh").external_attr >> 16) & 0o777 == 0o755


def test_output_refuses_overwrite_and_unignored_checkout_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "-q")
    (repository / ".gitignore").write_text("dist/\n")
    RELEASE.validate_output_location(repository, repository / "dist" / "release")
    with pytest.raises(RELEASE.ReleaseError, match="Git-ignored"):
        RELEASE.validate_output_location(repository, repository / "accidental-output")
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("owner data")
    with pytest.raises(RELEASE.ReleaseError, match="must be empty"):
        RELEASE.validate_output_location(repository, existing)
    assert (existing / "keep.txt").read_text() == "owner data"


def test_native_midi_wheel_selection_distinguishes_python_abi_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from packaging.tags import Tag
    import packaging.tags
    monkeypatch.setattr(packaging.tags, "sys_tags", lambda: iter([Tag("cp314", "cp314", "win_amd64")]))
    release = {"info": {"version": "1.5.8"}, "urls": [
        {"packagetype": "bdist_wheel", "filename": "python_rtmidi-1.5.8-cp312-cp312-win_amd64.whl"},
        {"packagetype": "bdist_wheel", "filename": "python_rtmidi-1.5.8-cp314-cp314-manylinux_2_28_x86_64.whl"},
    ]}
    assert RELEASE.compatible_rtmidi_wheels(release) == []
    release["urls"].append({"packagetype": "bdist_wheel", "filename": "python_rtmidi-1.5.8-cp314-cp314-win_amd64.whl"})
    assert RELEASE.compatible_rtmidi_wheels(release) == ["python_rtmidi-1.5.8-cp314-cp314-win_amd64.whl"]
    release["urls"][-1]["yanked"] = True
    assert RELEASE.compatible_rtmidi_wheels(release) == []


def test_native_midi_rejects_unexpected_upstream_release() -> None:
    with pytest.raises(RELEASE.ReleaseError, match="unexpected python-rtmidi"):
        RELEASE.compatible_rtmidi_wheels({"info": {"version": "1.6.0"}, "urls": []})


def test_native_midi_source_integrity_is_checked_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "untrusted.tar.gz"
    archive.write_bytes(b"not the pinned upstream source")
    with pytest.raises(RELEASE.ReleaseError, match="source SHA-256"):
        RELEASE.extract_rtmidi_source(archive, tmp_path / "unpacked")
    assert not (tmp_path / "unpacked").exists()


@pytest.mark.parametrize("unsafe", ["../outside", "/absolute", "other-package/file", "python_rtmidi-1.5.8/../../escape"])
def test_native_midi_source_extraction_rejects_unsafe_members(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str) -> None:
    import tarfile
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        entry = tarfile.TarInfo(unsafe)
        entry.size = 1
        output.addfile(entry, io.BytesIO(b"x"))
    monkeypatch.setattr(RELEASE, "RTMIDI_SOURCE_SHA256", RELEASE.digest(archive))
    with pytest.raises(RELEASE.ReleaseError, match="unsafe python-rtmidi"):
        RELEASE.extract_rtmidi_source(archive, tmp_path / "extract")


def test_network_failure_never_becomes_a_silent_native_build_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error
    called = []
    monkeypatch.setattr(RELEASE, "run", lambda *args, **kwargs: "")
    def fail(*args, **kwargs):
        raise urllib.error.URLError("network unavailable")
    monkeypatch.setattr(RELEASE.urllib.request, "urlopen", fail)
    monkeypatch.setattr(RELEASE, "build_rtmidi_wheel", lambda *args: called.append("native build"))
    with pytest.raises(urllib.error.URLError, match="network unavailable"):
        RELEASE.prepare_wheelhouse(tmp_path / "wheels", ROOT, extras=("midi",))
    assert called == []
    assert not (tmp_path / "wheels" / "RTMIDI-PROVENANCE.json").exists()


def test_optional_native_build_toolchain_is_fully_pinned() -> None:
    from packaging.requirements import Requirement
    requirements = [Requirement(line) for line in (ROOT / "requirements-midi-build.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert {r.name for r in requirements} == {"Cython", "meson-python", "meson", "ninja", "pyproject-metadata"}
    assert all(len(r.specifier) == 1 and next(iter(r.specifier)).operator == "==" for r in requirements)


def test_wheelhouse_tag_detection_bootstraps_with_only_pip(tmp_path: Path) -> None:
    import sys
    script = """
import importlib.abc, importlib.util, pathlib, sys
class NoStandalonePackaging(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'packaging' or fullname.startswith('packaging.'):
            raise ModuleNotFoundError('No standalone packaging installed', name=fullname)
sys.meta_path.insert(0, NoStandalonePackaging())
spec=importlib.util.spec_from_file_location('release', sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.compatible_rtmidi_wheels({'info': {'version': '1.5.8'}, 'urls': []}) == []
assert 'packaging' not in sys.modules
assert 'pip._vendor.packaging.tags' in sys.modules
print('stock Python+pip bootstrap passed')
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(ROOT / "tools" / "release.py")], cwd=tmp_path, capture_output=True, text=True, timeout=30, check=True)
    assert 'bootstrap passed' in result.stdout


def test_optional_constraints_prevent_newer_stale_midi_wheel_resolution(tmp_path: Path) -> None:
    import sys
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    for version in ("1.5.8", "1.6.0"):
        prefix = f"python_rtmidi-{version}.dist-info/"
        payload = {
            prefix + "METADATA": f"Metadata-Version: 2.4\nName: python-rtmidi\nVersion: {version}\nRequires-Python: >=3.11\n".encode(),
            prefix + "WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        }
        record = io.StringIO(newline="")
        writer = csv.writer(record)
        for name, data in payload.items():
            sha = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            writer.writerow([name, "sha256=" + sha, len(data)])
        writer.writerow([prefix + "RECORD", "", ""])
        payload[prefix + "RECORD"] = record.getvalue().encode()
        with zipfile.ZipFile(wheelhouse / f"python_rtmidi-{version}-py3-none-any.whl", "w") as wheel:
            for name, data in payload.items():
                wheel.writestr(name, data)
    report = tmp_path / "resolution.json"
    result = subprocess.run([sys.executable, "-I", "-m", "pip", "install", "--dry-run", "--ignore-installed", "--no-deps",
                             "--no-index", "--find-links", str(wheelhouse), "--constraint", str(ROOT / "requirements-optional.txt"),
                             "--report", str(report), "python-rtmidi>=1.5,<2"],
                            cwd=tmp_path, env=RELEASE.clean_environment(wheelhouse), capture_output=True, text=True, timeout=30, check=True)
    resolution = json.loads(report.read_text())["install"]
    assert len(resolution) == 1
    assert resolution[0]["metadata"]["version"] == "1.5.8", result.stdout
    assert resolution[0]["download_info"]["url"].endswith("python_rtmidi-1.5.8-py3-none-any.whl")


def test_optional_constraint_versions_match_the_qualified_acquisition() -> None:
    from packaging.requirements import Requirement
    constraints = [Requirement(line) for line in (ROOT / "requirements-optional.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert {r.name for r in constraints} == {"sounddevice", "mido", "python-rtmidi", "cffi", "pycparser"}
    assert all(len(r.specifier) == 1 and next(iter(r.specifier)).operator == "==" for r in constraints)
    assert next(str(r.specifier) for r in constraints if r.name == "python-rtmidi") == "==" + RELEASE.RTMIDI_VERSION


@pytest.mark.parametrize("mode", ["upstream binary wheel", "built from pinned published sdist"])
def test_midi_provenance_rejects_competing_same_version_wheel_and_tampering(tmp_path: Path, mode: str) -> None:
    wheel = tmp_path / "python_rtmidi-1.5.8-cp314-cp314-linux_x86_64.whl"
    wheel.write_bytes(b"qualified wheel")
    provenance = {"mode": mode, "version": "1.5.8"}
    if mode == "upstream binary wheel":
        provenance["downloaded_wheels_sha256"] = {wheel.name: RELEASE.digest(wheel)}
    else:
        provenance.update(wheel=wheel.name, wheel_sha256=RELEASE.digest(wheel))
    record = tmp_path / "RTMIDI-PROVENANCE.json"
    record.write_bytes(RELEASE.json_bytes(provenance))
    assert RELEASE.validate_rtmidi_provenance(tmp_path) == provenance
    competing = tmp_path / "python_rtmidi-1.5.8-cp314-cp314-manylinux_2_28_x86_64.whl"
    competing.write_bytes(b"pip may prefer this different build")
    with pytest.raises(RELEASE.ReleaseError, match="exactly its one recorded"):
        RELEASE.validate_rtmidi_provenance(tmp_path)
    assert competing.read_bytes() == b"pip may prefer this different build"
    competing.unlink()
    wheel.write_bytes(b"changed after acquisition")
    with pytest.raises(RELEASE.ReleaseError, match="SHA-256 does not match"):
        RELEASE.validate_rtmidi_provenance(tmp_path)


def test_candidate_rejects_tampered_midi_provenance_before_build(tmp_path: Path) -> None:
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    wheel = wheels / "python_rtmidi-1.5.8-cp314-cp314-win_amd64.whl"
    wheel.write_bytes(b"original")
    (wheels / "RTMIDI-PROVENANCE.json").write_bytes(RELEASE.json_bytes({
        "mode": "built from pinned published sdist", "version": "1.5.8",
        "wheel": wheel.name, "wheel_sha256": RELEASE.digest(wheel),
    }))
    wheel.write_bytes(b"tampered")
    with pytest.raises(RELEASE.ReleaseError, match="SHA-256 does not match"):
        RELEASE.create_candidate(ROOT, "HEAD", tmp_path / "candidate", wheelhouse=wheels)
    assert not (tmp_path / "candidate").exists()


def test_midi_cache_requires_provenance_and_preserves_newer_version_cache(tmp_path: Path) -> None:
    newer = tmp_path / "python_rtmidi-1.6.0-py3-none-any.whl"
    newer.write_bytes(b"constrained out of resolution")
    assert RELEASE.validate_rtmidi_provenance(tmp_path) is None
    pinned = tmp_path / "python_rtmidi-1.5.8-py3-none-any.whl"
    pinned.write_bytes(b"no provenance")
    with pytest.raises(RELEASE.ReleaseError, match="lacks provenance"):
        RELEASE.validate_rtmidi_provenance(tmp_path)
    assert newer.read_bytes() == b"constrained out of resolution"
