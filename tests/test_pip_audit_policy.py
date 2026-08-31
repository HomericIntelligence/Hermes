"""Regression coverage for the locked pip audit policy (issue #769)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PIXI_MANIFEST = ROOT / "pixi.toml"
PYPROJECT = ROOT / "pyproject.toml"
PIXI_LOCK = ROOT / "pixi.lock"
CI_RUNNER = ROOT / "scripts" / "run_ci_local.sh"
REQUIRED_WORKFLOW = ROOT / ".github" / "workflows" / "_required.yml"

PIP_REQUIREMENT = ">=26.2,<27"
MINIMUM_SAFE_PIP = (26, 2)
NEXT_MAJOR_PIP = (27,)


def _canonicalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject_dev_requirement(name: str) -> str:
    document = tomllib.loads(PYPROJECT.read_text())
    dependencies = document["project"]["optional-dependencies"]["dev"]
    matches = []
    for entry in dependencies:
        match = re.fullmatch(r"(?P<name>[A-Za-z0-9_.-]+)(?P<specifier>.*)", entry)
        assert match is not None, f"cannot parse dev requirement {entry!r}"
        if _canonicalize_name(match.group("name")) == _canonicalize_name(name):
            matches.append(match.group("specifier"))
    assert len(matches) == 1, f"expected one {name!r} dev requirement, found {matches!r}"
    return matches[0]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content))
    path.chmod(0o755)


def _audit_runner_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(CI_RUNNER, scripts / CI_RUNNER.name)

    fake_engine = fake_bin / "fake-container"
    _write_executable(
        fake_engine,
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        if [ "${1:-}" = "image" ] && [ "${2:-}" = "inspect" ]; then
          exit 0
        fi
        if [ "${1:-}" != "run" ]; then
          exit 64
        fi
        shift
        while [ "$#" -gt 0 ]; do
          if [ "$1" = "bash" ] && [ "${2:-}" = "-lc" ]; then
            exec /bin/bash -c "$3"
          fi
          shift
        done
        exit 65
        """,
    )

    pixi_log = tmp_path / "pixi.log"
    _write_executable(
        fake_bin / "pixi",
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        printf '%s\n' "$*" >> "${FAKE_PIXI_LOG:?}"
        case "$*" in
          "install --locked --quiet") exit 0 ;;
          "run pip-audit") exit "${FAKE_PIP_AUDIT_EXIT:-0}" ;;
          *) exit 66 ;;
        esac
        """,
    )

    env = os.environ.copy()
    env.update(
        {
            "CONTAINER_ENGINE": str(fake_engine),
            "FAKE_PIP_AUDIT_EXIT": "47",
            "FAKE_PIXI_LOG": str(pixi_log),
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        }
    )
    return repo, env, pixi_log


def test_manifest_pip_requirements_have_one_aligned_safe_range() -> None:
    """Both supported install paths declare the same remediated pip range."""
    pixi = tomllib.loads(PIXI_MANIFEST.read_text())
    pixi_requirement = pixi["feature"]["dev"]["pypi-dependencies"]["pip"]

    assert pixi_requirement == PIP_REQUIREMENT
    assert _pyproject_dev_requirement("pip") == PIP_REQUIREMENT


def test_locked_pip_floor_covers_every_supported_environment_and_platform() -> None:
    """Each supported environment/platform pair resolves a non-vulnerable pip."""
    manifest = tomllib.loads(PIXI_MANIFEST.read_text())
    lock = yaml.safe_load(PIXI_LOCK.read_text())
    supported_platforms = set(manifest["workspace"]["platforms"])
    supported_environments = set(manifest["environments"])

    assert supported_environments <= lock["environments"].keys()
    pip_records = {
        record["pypi"]: record
        for record in lock["packages"]
        if record.get("name") == "pip" and "pypi" in record
    }
    assert pip_records, "pixi.lock has no pip package record"

    for environment in sorted(supported_environments):
        packages_by_platform = lock["environments"][environment]["packages"]
        assert set(packages_by_platform) == supported_platforms
        for platform in sorted(supported_platforms):
            matches = [
                pip_records[reference["pypi"]]
                for reference in packages_by_platform[platform]
                if reference.get("pypi") in pip_records
            ]
            assert len(matches) == 1, (
                f"{environment}/{platform} must resolve exactly one pip package, found {matches!r}"
            )
            version = tuple(int(part) for part in matches[0]["version"].split("."))
            assert MINIMUM_SAFE_PIP <= version < NEXT_MAJOR_PIP, (
                f"{environment}/{platform} resolved vulnerable or unsupported pip "
                f"{matches[0]['version']}"
            )


def test_dependency_scan_uses_exact_locked_fail_closed_audit_command() -> None:
    """The required dependency scan cannot hide install or audit failures."""
    runner = CI_RUNNER.read_text()
    match = re.search(
        r"run_security-dependency-scan\(\) \{(?P<body>.*?)\n\}",
        runner,
        flags=re.DOTALL,
    )
    assert match is not None
    body = match.group("body")

    assert 'run_in_container "pixi install --locked --quiet && pixi run pip-audit"' in body
    for suppression in ("|| true", "--ignore-vuln", "continue-on-error", "set +e"):
        assert suppression not in body


def test_dependency_scan_propagates_pip_audit_failure(tmp_path: Path) -> None:
    """A vulnerability finding keeps its non-zero status through the CI runner."""
    repo, env, pixi_log = _audit_runner_fixture(tmp_path)

    result = subprocess.run(
        ["bash", "scripts/run_ci_local.sh", "security-dependency-scan"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert pixi_log.read_text().splitlines() == [
        "install --locked --quiet",
        "run pip-audit",
    ]
    assert result.returncode == 47


def test_required_dependency_scan_step_has_no_workflow_suppression() -> None:
    """The workflow delegates to the fail-closed runner without an override."""
    workflow = yaml.safe_load(REQUIRED_WORKFLOW.read_text())
    job = workflow["jobs"]["security-dependency-scan"]
    assert "continue-on-error" not in job

    steps = [
        step
        for step in job["steps"]
        if step.get("name") == "security-dependency-scan (in container)"
    ]
    assert len(steps) == 1
    assert steps[0]["run"] == "bash scripts/run_ci_local.sh security-dependency-scan"
    assert "continue-on-error" not in steps[0]
