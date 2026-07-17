"""Regression coverage for merge-queue required-check workflow support."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO / ".github" / "workflows"

# These names mirror the required contexts in Hermes's active main rulesets.
# Keep this map in sync when a required context is added, removed, or renamed.
_REQUIRED_CONTEXTS_BY_WORKFLOW = {
    "_required.yml": {
        "lint",
        "unit-tests",
        "integration-tests",
        "security/dependency-scan",
        "security/secrets-scan",
        "build",
        "schema-validation",
        "deps/version-sync",
        "test",
        "package",
        "install",
        "release",
        "justfile-check",
    },
    "security.yml": {"Secret Scanning (gitleaks)"},
}


def _load_workflow(name: str) -> dict:
    document = yaml.safe_load((_WORKFLOWS / name).read_text())
    assert isinstance(document, dict)
    return document


def _trigger(document: dict) -> dict:
    # PyYAML 1.1 parses the bare GitHub Actions `on` key as boolean True.
    trigger = document.get("on", document.get(True))
    assert isinstance(trigger, dict)
    return trigger


@pytest.mark.parametrize("workflow_name", _REQUIRED_CONTEXTS_BY_WORKFLOW)
def test_required_context_workflows_handle_merge_group_checks_requested(
    workflow_name: str,
) -> None:
    """Every workflow that gates main must also run for merge-queue groups."""
    merge_group = _trigger(_load_workflow(workflow_name)).get("merge_group")
    assert merge_group == {"types": ["checks_requested"]}, (
        f"{workflow_name} must handle merge_group/checks_requested so its required "
        "contexts are emitted for merge-queue groups"
    )


@pytest.mark.parametrize(
    ("workflow_name", "required_contexts"),
    _REQUIRED_CONTEXTS_BY_WORKFLOW.items(),
)
def test_required_context_names_remain_emitted(
    workflow_name: str, required_contexts: set[str]
) -> None:
    """Merge-queue trigger changes must not drop or rename existing gates."""
    document = _load_workflow(workflow_name)
    emitted_names = {
        job.get("name", job_id)
        for job_id, job in document.get("jobs", {}).items()
        if isinstance(job, dict)
    }
    assert required_contexts <= emitted_names, (
        f"{workflow_name} no longer emits required contexts: "
        f"{sorted(required_contexts - emitted_names)}"
    )
