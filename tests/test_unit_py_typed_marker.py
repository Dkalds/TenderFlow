"""Tests for PEP 561 py.typed marker in shared/ package."""

import tomllib
from pathlib import Path


def test_py_typed_marker_exists() -> None:
    """shared/py.typed must exist as a PEP 561 marker."""
    marker = Path(__file__).resolve().parent.parent / "shared" / "py.typed"
    assert marker.is_file(), f"Missing PEP 561 marker: {marker}"


def test_pyproject_includes_py_typed_in_package_data() -> None:
    """pyproject.toml must declare shared/py.typed in package-data."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert "shared" in package_data, "shared not in [tool.setuptools.package-data]"
    assert "py.typed" in package_data["shared"], "py.typed not listed for shared"
