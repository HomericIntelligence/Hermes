"""Regression tests: requirements.txt must have exact pins satisfying pixi.toml bounds."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomllib  # type: ignore[no-redef]

from packaging.specifiers import SpecifierSet
from packaging.version import Version

REPO_ROOT = Path(__file__).parent.parent
REQUIREMENTS_FILE = REPO_ROOT / "requirements.txt"
PIXI_TOML_FILE = REPO_ROOT / "pixi.toml"

_EXACT_PIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[\w,]+\])?==\S+$")


def _load_requirements() -> list[str]:
    """Return non-comment, non-empty lines from requirements.txt."""
    return [
        line.strip()
        for line in REQUIREMENTS_FILE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-")


def test_requirements_txt_exists() -> None:
    assert REQUIREMENTS_FILE.exists(), (
        f"{REQUIREMENTS_FILE} not found. Run: python scripts/sync_requirements.py"
    )


def test_requirements_txt_all_exact_pins() -> None:
    """Every line in requirements.txt must be an exact == pin."""
    lines = _load_requirements()
    assert lines, "requirements.txt has no dependency lines"
    bad = [line for line in lines if not _EXACT_PIN_RE.match(line)]
    assert not bad, (
        "The following lines in requirements.txt are not exact == pins:\n"
        + "\n".join(f"  {line}" for line in bad)
    )


def test_pins_satisfy_pixi_toml_bounds() -> None:
    """Each pinned version in requirements.txt must satisfy the range in pixi.toml."""
    lines = _load_requirements()
    with PIXI_TOML_FILE.open("rb") as f:
        toml_data = tomllib.load(f)

    pypi_deps: dict[str, object] = toml_data.get("pypi-dependencies", {})

    # Build {normalized-name: specifier-string} from pixi.toml
    toml_specs: dict[str, str] = {}
    for pkg_name, spec in pypi_deps.items():
        norm = _normalize(pkg_name)
        if isinstance(spec, str):
            toml_specs[norm] = spec
        elif isinstance(spec, dict) and "version" in spec:
            toml_specs[norm] = spec["version"]

    failures: list[str] = []
    for line in lines:
        # Strip extras for lookup: "uvicorn[standard]==0.46.0" → "uvicorn"
        base, _, pinned_ver = line.partition("==")
        base_name = _normalize(re.sub(r"\[.*?\]", "", base))

        if base_name not in toml_specs:
            continue  # not a declared runtime dep; skip

        spec_str = toml_specs[base_name]
        specifier = SpecifierSet(spec_str)
        version = Version(pinned_ver)
        if version not in specifier:
            failures.append(
                f"  {base_name}=={pinned_ver} does not satisfy pixi.toml range '{spec_str}'"
            )

    assert not failures, (
        "Pinned versions violate pixi.toml bounds:\n" + "\n".join(failures)
    )
