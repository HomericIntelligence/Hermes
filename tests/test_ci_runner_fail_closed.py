"""Failure-path tests for required CI runner subsets."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RUNNER = _REPO / "scripts" / "run_ci_local.sh"
_SYMLINK_CHECK = _REPO / "scripts" / "check-symlinks.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content))
    path.chmod(0o755)


def _runner_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    workflows = repo / ".github" / "workflows"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    workflows.mkdir(parents=True)
    fake_bin.mkdir()

    shutil.copy2(_RUNNER, scripts / _RUNNER.name)
    shutil.copy2(_SYMLINK_CHECK, scripts / _SYMLINK_CHECK.name)

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

    _write_executable(
        fake_bin / "pixi",
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        case "$*" in
          "install --locked --quiet") exit 0 ;;
          "run pip-audit") exit "${FAKE_PIP_AUDIT_EXIT:-0}" ;;
          "run validate") exit "${FAKE_SCHEMA_EXIT:-0}" ;;
          *) exit 0 ;;
        esac
        """,
    )

    _write_executable(
        fake_bin / "python",
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
          exit 0
        fi
        exec python3 "$@"
        """,
    )

    _write_executable(
        fake_bin / "check-jsonschema",
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        saw_workflow=0
        for argument in "$@"; do
          case "$argument" in
            *.yml|*.yaml)
              saw_workflow=1
              if grep -q '^jobs: \\[\\]$' "$argument"; then
                echo "invalid workflow fixture: $argument" >&2
                exit "${FAKE_SCHEMA_EXIT:-31}"
              fi
              ;;
          esac
        done
        if [ "$saw_workflow" -ne 1 ]; then
          echo "no workflow files reached check-jsonschema" >&2
          exit 32
        fi
        """,
    )

    env = os.environ.copy()
    env.update(
        {
            "CONTAINER_ENGINE": str(fake_engine),
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        }
    )
    return repo, env


def _run_subset(repo: Path, env: dict[str, str], subset: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/run_ci_local.sh", subset],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("extension", ["yml", "yaml"])
def test_schema_validation_rejects_invalid_workflow(tmp_path: Path, extension: str) -> None:
    """Each supported workflow suffix reaches a fail-closed schema validator."""
    repo, env = _runner_fixture(tmp_path)
    (repo / ".github" / "workflows" / f"invalid.{extension}").write_text(
        "name: invalid\non: push\njobs: []\n"
    )
    env["FAKE_SCHEMA_EXIT"] = "31"

    result = _run_subset(repo, env, "schema-validation")

    assert result.returncode != 0
    assert "invalid workflow fixture" in result.stderr


@pytest.mark.parametrize(
    ("fixture", "expected_message"),
    [
        ("broken", "broken symlink"),
        ("escaping", "symlink escapes repo"),
    ],
)
def test_symlink_check_rejects_unsafe_links(
    tmp_path: Path, fixture: str, expected_message: str
) -> None:
    """The retained subset rejects broken and repository-escaping links."""
    repo, env = _runner_fixture(tmp_path)
    link = repo / "unsafe-link"
    if fixture == "broken":
        link.symlink_to("missing-target")
    else:
        outside = tmp_path / "outside.txt"
        outside.write_text("outside\n")
        link.symlink_to(outside)

    result = _run_subset(repo, env, "symlink-check")

    assert result.returncode != 0
    assert expected_message in result.stdout


def test_dependency_scan_preserves_pip_audit_failure(tmp_path: Path) -> None:
    """A pip-audit finding fails the required dependency-scan subset."""
    repo, env = _runner_fixture(tmp_path)
    env["FAKE_PIP_AUDIT_EXIT"] = "47"

    result = _run_subset(repo, env, "security-dependency-scan")

    assert result.returncode == 47
