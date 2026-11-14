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


def make_wheel(directory: Path, name: str, *, version: str = "0.1.0", command: str | None = None, dependencies: str = "") -> Path:
    normalized = name.replace("-", "_")
    metadata = f"{normalized}-{version}.dist-info"
    contents = {
        f"{normalized}/__init__.py": f"__version__ = {version!r}\n",
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


def test_shell_syntax_when_posix_shell_available() -> None:
    if os.name != "nt":
        subprocess.run(["sh", "-n", str(ROOT / "launch.sh")], check=True, timeout=10)


def test_exact_candidate_archive_source_wheel_and_manifest_validation(tmp_path: Path) -> None:
    root = fixture_bundle(tmp_path)
    source_names = ("launch.sh", "launch.cmd", "tools/launch.py", "requirements-release.txt")
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
