"""Real bootstrap/venv/pip regression tests without network or audio devices.

Tiny standards-compliant wheels isolate setup failures and argument boundaries.
The release/check tooling separately runs these wrappers with the real four wheels
and source packages, including installed instrument self-tests.
"""

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
import stat
import subprocess
import sys
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("trio_launch", ROOT / "tools" / "launch.py")
assert SPEC is not None and SPEC.loader is not None
LAUNCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCH)
SMOKE_SPEC = importlib.util.spec_from_file_location("trio_launcher_smoke", ROOT / "tools" / "check_launchers.py")
assert SMOKE_SPEC is not None and SMOKE_SPEC.loader is not None
SMOKE = importlib.util.module_from_spec(SMOKE_SPEC)
SMOKE_SPEC.loader.exec_module(SMOKE)


def make_wheel(directory: Path, name: str, *, version: str = "0.1.0", command: str | None = None, dependencies: str = "", module_code: str | None = None) -> Path:
    normalized = name.replace("-", "_")
    metadata = f"{normalized}-{version}.dist-info"
    contents = {
        f"{normalized}/__init__.py": module_code if module_code is not None else f"__version__ = {version!r}\n",
        f"{metadata}/METADATA": f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n{dependencies}\n",
        f"{metadata}/WHEEL": "Wheel-Version: 1.0\nGenerator: TRIO launcher test fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    if command:
        contents[f"{metadata}/entry_points.txt"] = f"[console_scripts]\n{command} = {normalized}.cli:main\n"
        contents[f"{normalized}/cli.py"] = (
            "import json,sys\ndef main():\n"
            "    print(json.dumps({'args':sys.argv[1:],'prefix':sys.prefix,'fixture':True}))\n"
            "    return 23 if '--fixture-fail' in sys.argv else 0\n"
        )
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for path, content in contents.items():
        raw = content.encode("utf-8")
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((path, "sha256=" + digest, len(raw)))
    writer.writerow((f"{metadata}/RECORD", "", ""))
    contents[f"{metadata}/RECORD"] = record.getvalue()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{normalized}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for filename, content in contents.items():
            archive.writestr(filename, content)
    return path


def fixture_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "TRIO bundle with spaces"
    (root / "tools").mkdir(parents=True)
    for filename in ("launch.sh", "launch.cmd", "tools/launch.py"):
        shutil.copy2(ROOT / filename, root / filename)
    (root / "requirements-release.txt").write_text("# Fixture wheels have no mandatory third-party dependencies.\n", encoding="utf-8")
    (root / "requirements-optional.txt").write_text("# Ordinary fixture extras use only local fixture distributions.\n", encoding="utf-8")
    for name, command in (("kit", "trio-demo"), ("aurora", "aurora"), ("loom", "loom"), ("drift", "drift")):
        dependencies = (
            'Provides-Extra: audio\nRequires-Dist: trio-audio-fixture==1.0; extra == "audio"\n'
            'Provides-Extra: midi\nRequires-Dist: trio-midi-fixture==1.0; extra == "midi"\n'
        ) if name == "kit" else "Requires-Dist: trio-kit==0.1.0\n"
        make_wheel(root / "wheels", f"trio-{name}", command=command, dependencies=dependencies)
    return root


def invoke(root: Path, *arguments: str, extra_env: dict[str, str] | None = None, default_python: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in ("TRIO_VENV", "TRIO_WHEELHOUSE", "PYTHONHOME"):
        environment.pop(name, None)
    if default_python:
        environment.pop("TRIO_PYTHON", None)
        environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    else:
        environment["TRIO_PYTHON"] = sys.executable
    environment["PIP_NO_INDEX"] = "1"
    environment.update(extra_env or {})
    command = [str(root / "launch.cmd")] if os.name == "nt" else [str(shutil.which("sh")), str(root / "launch.sh")]
    return subprocess.run(
        [*command, "--wheelhouse", str(root / "wheels"), *arguments],
        cwd=root.parent, env=environment, capture_output=True, text=True, timeout=120, check=False,
    )


def assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_platform_wrapper_first_repeat_launch_arguments_and_exit_status(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    first = invoke(root, "aurora", "--fixture", "a path with spaces", "non-ascii-é", "")
    assert_ok(first)
    reported = json.loads(first.stdout.splitlines()[-1])
    assert reported["args"] == ["--fixture", "a path with spaces", "non-ascii-é", ""]
    assert Path(reported["prefix"]) == root / ".trio-venv"
    ready = root / ".trio-venv" / LAUNCH.READY
    before = (ready.read_bytes(), ready.stat().st_mtime_ns)
    for command in LAUNCH.COMMANDS:
        repeat = invoke(root, command, "--version")
        assert_ok(repeat)
        assert "reusing" in repeat.stderr and "setting up" not in repeat.stderr
        assert json.loads(repeat.stdout)["args"] == ["--version"]
    assert (ready.read_bytes(), ready.stat().st_mtime_ns) == before
    failed_app = invoke(root, "aurora", "--fixture-fail")
    assert failed_app.returncode == 23
    LAUNCH.command_path(root / ".trio-venv", "aurora").unlink()
    repaired = invoke(root, "aurora", "--version")
    assert_ok(repaired)
    assert "setting up" in repaired.stderr


def test_default_path_interpreter_creates_and_reuses_real_installation(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    first = invoke(root, "aurora", "--version", default_python=True)
    assert_ok(first)
    marker = LAUNCH.read_json(root / ".trio-venv" / LAUNCH.READY)
    assert marker["installed"]["python"] == list(sys.version_info[:3])
    repeat = invoke(root, "drift", "--version", default_python=True)
    assert_ok(repeat)
    assert "reusing" in repeat.stderr


def test_explicit_python_overrides_an_unusable_default_path(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    path = tmp_path / "no default python"
    path.mkdir()
    if os.name != "nt":
        (path / "dirname").symlink_to(str(shutil.which("dirname")))
    result = invoke(root, "--setup-only", "aurora", extra_env={"PATH": str(path)})
    assert_ok(result)
    assert (root / ".trio-venv" / LAUNCH.READY).is_file()


def test_bootstrap_ignores_ambient_python_import_path(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    injected = tmp_path / "ambient imports"
    injected.mkdir()
    (injected / "argparse.py").write_text("raise RuntimeError('ambient path imported')\n", encoding="utf-8")
    result = invoke(root, "--help", default_python=True, extra_env={"PYTHONPATH": str(injected)})
    assert_ok(result)
    assert "ambient path imported" not in result.stderr


def test_missing_supported_default_python_reports_requirement(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    path = tmp_path / "without python"
    path.mkdir()
    if os.name != "nt":
        (path / "dirname").symlink_to(str(shutil.which("dirname")))
    result = invoke(root, "aurora", default_python=True, extra_env={"PATH": str(path)})
    assert result.returncode == 2
    assert "needs Python 3.11 or newer" in result.stderr
    assert not (root / ".trio-venv").exists()


def test_platform_fallback_uses_real_interpreter_when_available(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    path = tmp_path / "fallback only"
    path.mkdir()
    if os.name == "nt":
        launcher = shutil.which("py")
        if launcher is None:
            # The fallback is optional. Its absence must produce the documented
            # failure; the ordinary python.exe selector is exercised above.
            result = invoke(root, "aurora", default_python=True, extra_env={"PATH": str(path)})
            assert result.returncode == 2 and "needs Python 3.11" in result.stderr
            return
        shutil.copy2(launcher, path / "py.exe")
        shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "where.exe", path / "where.exe")
        probe = subprocess.run([str(path / "py.exe"), "-3", "-c", "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"], capture_output=True, timeout=30, check=False)
        if probe.returncode:
            result = invoke(root, "aurora", default_python=True, extra_env={"PATH": str(path)})
            assert result.returncode == 2 and "needs Python 3.11" in result.stderr
            return
        # Help executes the real fallback Python without changing which matrix
        # Python supplies the isolated installation checks.
        result = invoke(root, "--help", default_python=True, extra_env={"PATH": str(path)})
        assert_ok(result)
        assert "Create/reuse an owned local TRIO environment" in result.stdout
    else:
        (path / "dirname").symlink_to(str(shutil.which("dirname")))
        (path / "python").symlink_to(sys.executable)
        result = invoke(root, "--setup-only", "aurora", default_python=True, extra_env={"PATH": str(path)})
        assert_ok(result)
        assert LAUNCH.read_json(root / ".trio-venv" / LAUNCH.READY)["installed"]["python"] == list(sys.version_info[:3])


def test_failed_optional_setup_is_unready_recoverable_and_choice_persists(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    first = invoke(root, "--extras", "audio", "aurora", "--version")
    assert first.returncode != 0
    assert "no instrument was launched" in first.stderr
    assert not (root / ".trio-venv" / LAUNCH.READY).exists()
    assert '"fixture": true' not in first.stdout
    make_wheel(root / "wheels", "trio-audio-fixture", version="1.0")
    assert_ok(invoke(root, "aurora", "--version"))
    marker = LAUNCH.read_json(root / ".trio-venv" / LAUNCH.READY)
    assert marker["extras"] == ["audio"]
    assert marker["installed"]["versions"]["trio-audio-fixture"] == "1.0"
    make_wheel(root / "wheels", "trio-midi-fixture", version="1.0")
    assert_ok(invoke(root, "--extras", "midi", "--setup-only", "loom"))
    assert LAUNCH.read_json(root / ".trio-venv" / LAUNCH.READY)["extras"] == ["audio", "midi"]
    assert_ok(invoke(root, "drift", "--version"))


def test_source_only_optional_dependency_uses_isolated_build_backend(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    # This backend wheel is available only to pip's isolated build environment.
    # The old global --no-build-isolation install fails to import it.
    backend = '''import base64, csv, hashlib, io, pathlib, zipfile
def get_requires_for_build_wheel(config_settings=None):
    return []
def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    wheel_name = "trio_audio_fixture-1.0-py3-none-any.whl"
    dist = "trio_audio_fixture-1.0.dist-info"
    contents = {
        "trio_audio_fixture/__init__.py": b"BUILD_ISOLATION_WORKED = True\\n",
        dist + "/METADATA": b"Metadata-Version: 2.3\\nName: trio-audio-fixture\\nVersion: 1.0\\n",
        dist + "/WHEEL": b"Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n",
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for name, data in contents.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, "sha256=" + digest, len(data)))
    writer.writerow((dist + "/RECORD", "", ""))
    contents[dist + "/RECORD"] = record.getvalue().encode("utf-8")
    with zipfile.ZipFile(pathlib.Path(wheel_directory) / wheel_name, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    return wheel_name
'''
    make_wheel(root / "wheels", "trio-build-helper-fixture", version="1.0", module_code=backend)
    pyproject = b'[build-system]\nrequires = ["trio-build-helper-fixture==1.0"]\nbuild-backend = "trio_build_helper_fixture"\n'
    source = root / "wheels" / "trio_audio_fixture-1.0.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        info = tarfile.TarInfo("trio_audio_fixture-1.0/pyproject.toml")
        info.size = len(pyproject)
        archive.addfile(info, io.BytesIO(pyproject))
    result = invoke(root, "--extras", "audio", "--setup-only", "aurora")
    assert_ok(result)
    marker = LAUNCH.read_json(root / ".trio-venv" / LAUNCH.READY)
    assert marker["installed"]["versions"]["trio-audio-fixture"] == "1.0"
    assert "trio-build-helper-fixture" not in marker["installed"]["versions"]
    assert marker["extras"] == ["audio"]
    repeated = invoke(root, "aurora", "--version")
    assert_ok(repeated)
    assert "reusing" in repeated.stderr


def test_missing_requested_midi_backend_gives_actionable_safe_failure(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    result = invoke(root, "--extras", "midi", "aurora", "--version")
    assert result.returncode != 0
    assert "no instrument was launched" in result.stderr
    assert "Visual Studio Build Tools" in result.stderr and "libasound2-dev" in result.stderr
    assert "compatible prebuilt wheelhouse" in result.stderr
    assert not (root / ".trio-venv" / LAUNCH.READY).exists()
    assert LAUNCH.read_json(root / ".trio-venv" / LAUNCH.OWNER)["extras"] == ["midi"]
    make_wheel(root / "wheels", "trio-midi-fixture", version="1.0")
    assert_ok(invoke(root, "aurora", "--version"))
    assert LAUNCH.read_json(root / ".trio-venv" / LAUNCH.READY)["extras"] == ["midi"]


def test_online_midi_preflight_preserves_selection_and_requires_controlled_wheelhouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_bundle(tmp_path)
    environment = root / ".trio-venv"
    # Exercise the newer-interpreter policy without running a native build or
    # contacting a network; CI also runs the real suite under Python 3.14.
    monkeypatch.setattr(LAUNCH.sys, "version_info", (3, 14, 0))
    with pytest.raises(LAUNCH.LaunchError, match=r"Python 3.13\+ MIDI setup requires") as failure:
        LAUNCH.prepare(root, environment, extras="audio,midi", wheelhouse=None, reinstall=False)
    assert "--prepare-wheelhouse wheelhouse --extras audio,midi" in str(failure.value)
    assert "No instrument was launched" in str(failure.value)
    assert LAUNCH.read_json(environment / LAUNCH.OWNER)["extras"] == ["audio", "midi"]
    assert not (environment / LAUNCH.READY).exists()
    assert not LAUNCH.venv_python(environment).exists()


def test_newer_optional_wheel_cannot_override_qualified_constraint(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    shutil.copy2(ROOT / "requirements-optional.txt", root / "requirements-optional.txt")
    make_wheel(
        root / "wheels", "trio-kit", command="trio-demo",
        dependencies='Provides-Extra: audio\nRequires-Dist: sounddevice>=0.5,<1; extra == "audio"\n',
    )
    # Public extras intentionally allow a range. A stale/newer wheelhouse must
    # still install the exact version named by release qualification.
    make_wheel(root / "wheels", "sounddevice", version="0.5.7")
    failed = invoke(root, "--extras", "audio", "--setup-only", "aurora")
    assert failed.returncode != 0
    assert not (root / ".trio-venv" / LAUNCH.READY).exists()
    make_wheel(root / "wheels", "sounddevice", version="0.5.6")
    assert_ok(invoke(root, "aurora", "--version"))
    marker = LAUNCH.read_json(root / ".trio-venv" / LAUNCH.READY)
    assert marker["installed"]["versions"]["sounddevice"] == "0.5.6"


def test_unmanaged_existing_environment_is_preserved(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    existing = root / ".trio-venv"
    existing.mkdir()
    sentinel = existing / "owner-data.txt"
    sentinel.write_text("keep", encoding="utf-8")
    result = invoke(root, "aurora", "--version")
    assert result.returncode != 0 and "unmanaged" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (existing / LAUNCH.OWNER).exists()


def test_incomplete_wheel_bundle_and_invalid_extras_fail_before_venv(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    result = invoke(root, "--extras", "surprise", "aurora")
    assert result.returncode != 0 and "--extras accepts" in result.stderr
    assert not (root / ".trio-venv").exists()
    next((root / "wheels").glob("trio_drift-*.whl")).unlink()
    result = invoke(root, "aurora")
    assert result.returncode != 0 and "exactly one trio-drift" in result.stderr
    assert not (root / ".trio-venv").exists()


def test_source_fingerprint_detects_changes_ignores_build_cache(tmp_path: Path) -> None:
    root = tmp_path
    (root / "requirements-release.txt").write_text("numpy==2.4.3\n", encoding="utf-8")
    shutil.copy2(ROOT / "requirements-optional.txt", root / "requirements-optional.txt")
    for name in LAUNCH.PACKAGES:
        path = root / name
        (path / "src" / f"trio_{name}").mkdir(parents=True)
        (path / "src" / f"trio_{name}" / "__init__.py").write_text("", encoding="utf-8")
        (path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    mode, packages, files = LAUNCH.package_inputs(root)
    assert mode == "source" and len(packages) == 4
    original = LAUNCH.fingerprint(root, files, ())
    cache = root / "kit" / "src" / "trio_kit" / "__pycache__"
    cache.mkdir()
    (cache / "__init__.cpython-311.pyc").write_bytes(b"not source")
    assert LAUNCH.fingerprint(root, LAUNCH.package_inputs(root)[2], ()) == original
    optional = root / "requirements-optional.txt"
    pinned = optional.read_text(encoding="utf-8")
    optional.write_text(pinned.replace("sounddevice==0.5.6", "sounddevice==0.5.7"), encoding="utf-8")
    assert LAUNCH.fingerprint(root, LAUNCH.package_inputs(root)[2], ()) != original
    optional.write_text(pinned, encoding="utf-8")
    (root / "kit" / "src" / "trio_kit" / "__init__.py").write_text("changed = True\n", encoding="utf-8")
    assert LAUNCH.fingerprint(root, LAUNCH.package_inputs(root)[2], ()) != original
    assert LAUNCH.fingerprint(root, files, ("audio",)) != original


def test_setup_lock_releases_after_failure(tmp_path: Path) -> None:
    environment = tmp_path / "env"
    with pytest.raises(RuntimeError, match="simulated"):
        with LAUNCH.setup_lock(environment):
            with pytest.raises(LAUNCH.LaunchError, match="Another TRIO setup"):
                with LAUNCH.setup_lock(environment):
                    pytest.fail("concurrent setup acquired the lock")
            raise RuntimeError("simulated interruption")
    with LAUNCH.setup_lock(environment):
        pass


def test_missing_wheelhouse_and_reserved_venv_path_fail_safely(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    with pytest.raises(LAUNCH.LaunchError, match="separate environment"):
        LAUNCH.prepare(root, root, extras=None, wheelhouse=None, reinstall=False)
    with pytest.raises(LAUNCH.LaunchError, match="does not exist"):
        LAUNCH.prepare(root, root / ".trio-venv", extras=None, wheelhouse=root / "absent", reinstall=False)


def test_clean_subprocess_environment_rejects_python_and_pip_install_redirection(monkeypatch: pytest.MonkeyPatch) -> None:
    controlled = (
        "PYTHONPATH", "PYTHONHOME", "PIP_TARGET", "PIP_PREFIX", "PIP_USER",
        "PIP_REQUIREMENT", "PIP_FIND_LINKS", "PIP_CONSTRAINT", "PIP_EDITABLE",
        "PIP_BUILD_CONSTRAINT", "PIP_ROOT", "PIP_FUTURE_INSTALL_OPTION",
    )
    for key in controlled:
        monkeypatch.setenv(key, "unexpected-directory")
    environment = LAUNCH.clean_environment()
    assert all(key not in environment for key in controlled)
    assert environment["PIP_CONFIG_FILE"] == os.devnull


@pytest.mark.parametrize("include_host_api", [False, True], ids=["dummy-only-rejected", "host-api-without-opening-ports"])
def test_installed_midi_probe_requires_host_api_without_constructing_ports(tmp_path: Path, include_host_api: bool) -> None:
    root = tmp_path / "probe bundle"
    root.mkdir()
    shutil.copy2(ROOT / "requirements-optional.txt", root / "requirements-optional.txt")
    environment = root / ".trio-venv"
    base_python = str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())
    subprocess.run([base_python, "-I", "-m", "venv", "--without-pip", str(environment)], check=True, timeout=60)
    python = LAUNCH.venv_python(environment)
    location = subprocess.run([str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], capture_output=True, text=True, check=True, timeout=30)
    site = Path(location.stdout.strip())
    site.mkdir(parents=True, exist_ok=True)
    host = 2 if sys.platform.startswith("linux") else 4 if sys.platform == "win32" else 1
    (site / "rtmidi.py").write_text(
        "API_LINUX_ALSA=2\nAPI_WINDOWS_MM=4\nAPI_MACOSX_CORE=1\nAPI_RTMIDI_DUMMY=6\n"
        f"def get_compiled_api(): return {[6, host] if include_host_api else [6]!r}\n"
        "def get_api_name(api): return str(api)\n"
        "def MidiIn(*args, **kwargs): raise AssertionError('must not construct a MIDI port')\n"
        "def MidiOut(*args, **kwargs): raise AssertionError('must not construct a MIDI port')\n",
        encoding="utf-8",
    )
    (site / "mido.py").write_text("def open_input(*args, **kwargs): raise AssertionError('must not open a MIDI port')\n", encoding="utf-8")
    for name, version in (("mido", "1.3.3"), ("python-rtmidi", "1.5.8")):
        metadata = site / (name.replace("-", "_") + f"-{version}.dist-info")
        metadata.mkdir()
        (metadata / "METADATA").write_text(f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n", encoding="utf-8")
    if not include_host_api:
        with pytest.raises(RuntimeError, match="expected host MIDI API"):
            SMOKE.probe_optional_backends(root, "midi")
    else:
        result = SMOKE.probe_optional_backends(root, "midi")
        assert result["rtmidi"]["host_api"] == "pass"
        assert result["ports_opened"] is False and result["streams_opened"] is False
        metadata = site / "mido-1.3.3.dist-info" / "METADATA"
        metadata.write_text(metadata.read_text(encoding="utf-8").replace("Version: 1.3.3", "Version: 1.3.4"), encoding="utf-8")
        with pytest.raises(RuntimeError, match="unqualified optional dependency version"):
            SMOKE.probe_optional_backends(root, "midi")


def test_shell_syntax_when_posix_shell_available() -> None:
    if os.name != "nt":
        subprocess.run(["sh", "-n", str(ROOT / "launch.sh")], check=True, timeout=10)


def test_exact_candidate_archive_source_wheel_and_manifest_validation(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    source_names = ("launch.sh", "launch.cmd", "tools/launch.py", "requirements-release.txt", "requirements-optional.txt")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in source_names}
    wheels = {
        f"trio-{name}": {"wheel": f"trio_{name}-0.1.0-py3-none-any.whl", "sha256": hashlib.sha256((root / "wheels" / f"trio_{name}-0.1.0-py3-none-any.whl").read_bytes()).hexdigest()}
        for name in LAUNCH.PACKAGES
    }
    record = {"commit": "1" * 40, "source_files_sha256": hashes, "wheels": wheels}
    archive_path = root / "trio-0.1.0-candidate-test.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in source_names:
            archive.writestr(name, (root / name).read_bytes())
        for item in wheels.values():
            archive.writestr("wheels/" + item["wheel"], (root / "wheels" / item["wheel"]).read_bytes())
        archive.writestr("SOURCE.json", json.dumps(record))
        archive.writestr("QUALIFICATION.json", "{}")
        archive.writestr("wheels/SHA256SUMS", "".join(f"{item['sha256']}  {item['wheel']}\n" for item in wheels.values()))
    sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (root / "SHA256SUMS").write_text(f"{sha}  {archive_path.name}\n", encoding="utf-8")
    result = SMOKE.extract_candidate(archive_path, tmp_path / "extracted candidate with spaces", root / "wheels", "1" * 40)
    assert result["source_and_wheel_hashes"] == "pass" and result["sha256"] == sha
    with pytest.raises(RuntimeError, match="commit does not match"):
        SMOKE.extract_candidate(archive_path, tmp_path / "wrong commit", root / "wheels", "2" * 40)
    (root / "wheels" / wheels["trio-kit"]["wheel"]).write_bytes(b"damaged wheel")
    with pytest.raises(RuntimeError, match="wheel hash mismatch"):
        SMOKE.extract_candidate(archive_path, tmp_path / "damaged wheel", root / "wheels", "1" * 40)


@pytest.mark.parametrize("member", ["../outside", "C:/outside", "..\\outside"])
def test_candidate_extraction_rejects_traversal(tmp_path: Path, member: str) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(member, b"bad")
    with pytest.raises(RuntimeError, match="Unsafe candidate"):
        SMOKE.extract_candidate(archive_path, tmp_path / "extract", tmp_path, None)
    assert not (tmp_path / "outside").exists()


def test_candidate_extraction_rejects_links(tmp_path: Path) -> None:
    archive_path = tmp_path / "link.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        member = zipfile.ZipInfo("linked")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, "../outside")
    with pytest.raises(RuntimeError, match="regular files"):
        SMOKE.extract_candidate(archive_path, tmp_path / "extract", tmp_path, None)
