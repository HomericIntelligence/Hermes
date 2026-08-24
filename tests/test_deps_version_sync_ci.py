"""Regression coverage for the required-CI pyproject↔pixi drift gate (#511).

The issue asks for a CI lint step comparing ``pyproject.toml
[project.dependencies]`` against ``pixi.toml [pypi-dependencies]`` so drift is
caught before merge. Enforcement lives in two places:

1. ``tests/test_check_dep_sync.py::test_main_real_repo_files_pass`` — runs the
   parity check against the real manifests inside the required ``unit-tests``
   job.
2. The required ``deps/version-sync`` job, which must invoke
   ``scripts/check_dep_sync.py`` explicitly via ``scripts/run_ci_local.sh``.

These tests pin the wiring so neither leg can silently disappear.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_REQUIRED = _REPO / ".github" / "workflows" / "_required.yml"
_RUN_CI_LOCAL = _REPO / "scripts" / "run_ci_local.sh"


def _deps_version_sync_run_steps() -> list[str]:
    """Return the ``run:`` values of every step in the deps-version-sync job."""
    document = yaml.safe_load(_REQUIRED.read_text())
    assert isinstance(document, dict)
    jobs = document.get("jobs", {})
    assert isinstance(jobs, dict)
    job = jobs.get("deps-version-sync")
    assert isinstance(job, dict), "deps-version-sync job missing from _required.yml"
    runs = [step.get("run", "") for step in job.get("steps", []) if isinstance(step, dict)]
    return runs


def test_required_workflow_has_deps_version_sync_job_running_ci_local() -> None:
    """The required workflow's deps-version-sync job delegates to run_ci_local.sh."""
    joined = "\n".join(_deps_version_sync_run_steps())
    assert "scripts/run_ci_local.sh deps-version-sync" in joined


def test_deps_version_sync_subset_runs_check_dep_sync() -> None:
    """The deps-version-sync subset in run_ci_local.sh must invoke
    scripts/check_dep_sync.py — otherwise pyproject↔pixi parity has no explicit
    required gate and drift can only be caught incidentally by unit tests."""
    script = _RUN_CI_LOCAL.read_text()
    function_start = script.index("run_deps-version-sync()")
    next_function = script.find("\nrun_", function_start + 1)
    body = script[function_start : next_function if next_function != -1 else len(script)]
    assert "check_dep_sync.py" in body, (
        "run_deps-version-sync no longer runs scripts/check_dep_sync.py; "
        "the pyproject↔pixi drift gate (#511) would be lost from required CI"
    )
