from __future__ import annotations

import ast
import importlib
import importlib.metadata
import re
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGES = {
    "kit": ("trio-kit", "trio_kit", None),
    "aurora": ("trio-aurora", "trio_aurora", "aurora"),
    "loom": ("trio-loom", "trio_loom", "loom"),
    "drift": ("trio-drift", "trio_drift", "drift"),
}
INSTRUMENT_IMPORTS = {"trio_aurora", "trio_loom", "trio_drift"}


@pytest.mark.parametrize("folder, expected", PACKAGES.items())
def test_distribution_import_and_version_are_unique(folder: str, expected: tuple[str, str, str | None]) -> None:
    distribution, import_name, command = expected
    project = tomllib.loads((ROOT / folder / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["name"] == distribution
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.11"
    assert importlib.metadata.version(distribution) == "0.1.0"
    assert importlib.import_module(import_name).__version__ == "0.1.0"
    if command is not None:
        assert project["scripts"][command].startswith(f"{import_name}.")


def test_distribution_and_import_names_do_not_collide() -> None:
    names = [tomllib.loads((ROOT / folder / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"] for folder in PACKAGES]
    imports = [entry[1] for entry in PACKAGES.values()]

    assert len(names) == len(set(names)) == 4
    assert len(imports) == len(set(imports)) == 4


@pytest.mark.parametrize("folder", ("aurora", "loom", "drift"))
def test_instruments_do_not_import_sibling_instruments(folder: str) -> None:
    source = ROOT / folder / "src" / PACKAGES[folder][1]
    for python_file in source.rglob("*.py"):
        tree = ast.parse(python_file.read_text(encoding="utf-8"), filename=str(python_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".", maxsplit=1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = {node.module.split(".", maxsplit=1)[0]}
            else:
                continue
            assert not imported & (INSTRUMENT_IMPORTS - {PACKAGES[folder][1]}), python_file


def test_kit_dependencies_cover_shared_runtime_and_keep_devices_optional() -> None:
    project = tomllib.loads((ROOT / "kit" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = " ".join(project["dependencies"])

    for required in ("numpy", "scipy", "prompt-toolkit", "wcwidth"):
        assert required in dependencies
    assert "sounddevice" not in dependencies
    assert "mido" not in dependencies
    assert "audio" in project["optional-dependencies"]
    assert "midi" in project["optional-dependencies"]


def test_instrument_packages_depend_only_on_the_shared_kit() -> None:
    for folder in ("aurora", "loom", "drift"):
        project = tomllib.loads((ROOT / folder / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        assert project["dependencies"] == ["trio-kit>=0.1.0,<0.2.0"]


def test_all_packages_declare_factory_asset_data() -> None:
    for folder, (_, import_name, _) in PACKAGES.items():
        project = tomllib.loads((ROOT / folder / "pyproject.toml").read_text(encoding="utf-8"))
        assert project["tool"]["setuptools"]["package-data"][import_name] == [
            "py.typed",
            "data/presets/*.json",
            "data/skins/*.txt",
        ]


def test_ci_qualifies_all_required_platform_and_python_combinations_with_read_only_permissions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for operating_system in ("ubuntu-latest", "windows-latest"):
        for python_version in ("3.11", "3.14"):
            lane = re.compile(
                rf"- os: {re.escape(operating_system)}\s+python-version: \"{re.escape(python_version)}\""
            )
            assert lane.search(workflow), f"missing {operating_system} / Python {python_version} lane"
    assert re.search(r"(?m)^permissions:\s*\n\s+contents: read\s*$", workflow)
    assert not re.search(r"(?m)^\s+(?:contents|pull-requests|actions|packages): write\s*$", workflow)
