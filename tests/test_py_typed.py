"""Verify that the PEP 561 py.typed marker is present in the hermes package."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def test_py_typed_marker_exists_in_source() -> None:
    """py.typed must exist alongside the package source files."""
    import hermes

    pkg_dir = Path(hermes.__file__).parent  # type: ignore[arg-type]
    assert (pkg_dir / "py.typed").exists(), "py.typed marker missing from hermes package"


def test_py_typed_marker_is_empty() -> None:
    """PEP 561 requires py.typed to be an empty file (zero bytes)."""
    import hermes

    pkg_dir = Path(hermes.__file__).parent  # type: ignore[arg-type]
    marker = pkg_dir / "py.typed"
    assert marker.stat().st_size == 0, "py.typed must be empty (zero bytes)"


def test_py_typed_accessible_via_importlib_resources() -> None:
    """py.typed must be accessible as a package resource (i.e. it's included)."""
    ref = importlib.resources.files("hermes").joinpath("py.typed")
    assert ref.is_file(), "py.typed is not accessible as a package resource"
