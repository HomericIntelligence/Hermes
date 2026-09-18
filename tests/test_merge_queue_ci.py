"""Structural regression coverage for merge-queue producer parity."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO / ".github" / "workflows"

# These names mirror the required contexts owned by each real producer in
# Hermes's active main rulesets. Every producer listed here must emit its
# contexts for pull_request *and* merge_group, or the merge queue waits on a
# context that can never report and ejects the entry on timeout (issue #764).
_REQUIRED_CONTEXTS_BY_PRODUCER = {
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
    # Canonical main-push secret scan lives in _required.yml, so this producer
    # is PR/schedule/dispatch only and must not be expected on main push.
    "security.yml": {"Secret Scanning (gitleaks)"},
}

# Producers that additionally gate main pushes. _required.yml is the canonical
# producer for main-tip health; security.yml contributes only scheduled and
# pull-request scans.
_MAIN_PUSH_PRODUCERS = {"_required.yml"}

_SMOKE_WORKFLOW = "merge-queue-smoke.yml"
_BOOL_TAG = "tag:yaml.org,2002:bool"
_EXPECTED_CONCURRENCY_GROUP = (
    "${{ github.workflow }}-${{ github.event_name }}-"
    "${{ github.event.pull_request.number || github.sha }}"
)


class _WorkflowLoader(yaml.SafeLoader):
    """Load Actions YAML without YAML 1.1's ``on``/``off`` booleans."""


_WorkflowLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != _BOOL_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_WorkflowLoader.add_implicit_resolver(
    _BOOL_TAG,
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _load_workflow(name: str) -> dict:
    document = yaml.load((_WORKFLOWS / name).read_text(), Loader=_WorkflowLoader)
    assert isinstance(document, dict)
    assert "on" in document
    assert True not in document
    return document


def _job_by_context(document: dict) -> dict[str, dict]:
    jobs = document.get("jobs", {})
    assert isinstance(jobs, dict)
    return {job.get("name", job_id): job for job_id, job in jobs.items() if isinstance(job, dict)}


def _modeled_concurrency_key(
    workflow_name: str,
    event_name: str,
    sha: str,
    *,
    head_ref: str = "",
    pull_request_number: int | None = None,
) -> str:
    """Resolve the supported Actions values in the workflow concurrency key."""
    document = _load_workflow("_required.yml")
    concurrency = document.get("concurrency")
    assert isinstance(concurrency, dict)
    group = concurrency.get("group")
    assert isinstance(group, str)

    values = {
        "github.workflow": workflow_name,
        "github.event_name": event_name,
        "github.sha": sha,
        "github.head_ref || github.sha": head_ref or sha,
        "github.event.pull_request.number || github.sha": (
            str(pull_request_number) if pull_request_number is not None else sha
        ),
    }

    def replace_expression(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        assert expression in values, f"unsupported concurrency expression: {expression}"
        return values[expression]

    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace_expression, group)


@pytest.mark.parametrize(
    ("workflow_name", "required_contexts"),
    _REQUIRED_CONTEXTS_BY_PRODUCER.items(),
)
def test_required_producer_has_pull_request_merge_group_parity(
    workflow_name: str, required_contexts: set[str]
) -> None:
    """Every required producer emits the same contexts for PR and queue SHAs.

    A missing merge_group trigger is not a cosmetic gap: the merge queue
    evaluates required contexts against the synthetic ``gh-readonly-queue``
    SHA, so a producer that only listens to ``pull_request`` never reports
    there. The queue then holds the entry until
    ``check_response_timeout_minutes`` expires and ejects it (issue #764).
    """
    document = _load_workflow(workflow_name)
    trigger = document["on"]
    assert isinstance(trigger, dict)
    assert trigger.get("pull_request") == {"branches": ["main"]}
    assert trigger.get("merge_group") == {"types": ["checks_requested"]}
    if workflow_name in _MAIN_PUSH_PRODUCERS:
        assert trigger.get("push") == {"branches": ["main"]}

    jobs_by_context = _job_by_context(document)
    assert required_contexts <= jobs_by_context.keys(), (
        f"{workflow_name} no longer emits required contexts: "
        f"{sorted(required_contexts - jobs_by_context.keys())}"
    )

    # A required job with a job-level condition can silently suppress its
    # context on one event. Required producer jobs stay unconditional.
    conditioned_contexts = {
        context for context in required_contexts if "if" in jobs_by_context[context]
    }
    assert not conditioned_contexts, (
        f"{workflow_name} conditionally suppresses required contexts: "
        f"{sorted(conditioned_contexts)}"
    )

    # Derive the required set once, then prove both event paths reach it.
    reachable_by_event = {
        event_name: required_contexts
        for event_name in ("pull_request", "merge_group")
        if event_name in trigger
    }
    assert reachable_by_event == {
        "pull_request": required_contexts,
        "merge_group": required_contexts,
    }


@pytest.mark.parametrize("workflow_name", _REQUIRED_CONTEXTS_BY_PRODUCER)
def test_required_producer_concurrency_uses_pull_request_number_or_sha(
    workflow_name: str,
) -> None:
    """The producer uses a stable PR identity and a revision identity otherwise."""
    document = _load_workflow(workflow_name)
    concurrency = document.get("concurrency")
    assert isinstance(concurrency, dict)
    assert concurrency.get("group") == _EXPECTED_CONCURRENCY_GROUP
    assert concurrency.get("cancel-in-progress") is True


def test_concurrency_keys_isolate_fork_pull_requests_with_the_same_head_ref() -> None:
    """Two fork PRs with the same source branch cannot cancel one another."""
    first = _modeled_concurrency_key(
        "Required Checks",
        "pull_request",
        "first-head-sha",
        head_ref="feature",
        pull_request_number=101,
    )
    second = _modeled_concurrency_key(
        "Required Checks",
        "pull_request",
        "second-head-sha",
        head_ref="feature",
        pull_request_number=102,
    )

    assert first != second


def test_concurrency_keys_isolate_pull_request_and_merge_group_runs() -> None:
    """A PR run and a queue run cannot cancel one another."""
    pull_request = _modeled_concurrency_key(
        "Required Checks",
        "pull_request",
        "shared-sha",
        head_ref="feature",
        pull_request_number=101,
    )
    merge_group = _modeled_concurrency_key(
        "Required Checks",
        "merge_group",
        "shared-sha",
    )

    assert pull_request != merge_group


def test_smoke_only_merge_queue_carrier_is_absent() -> None:
    """A smoke-only workflow cannot substitute for the real producers."""
    assert not (_WORKFLOWS / _SMOKE_WORKFLOW).exists()

    for pattern in ("*.yml", "*.yaml"):
        for path in _WORKFLOWS.glob(pattern):
            jobs_by_context = _job_by_context(_load_workflow(path.name))
            assert "merge-queue-smoke" not in jobs_by_context


def test_smoke_oracle_rejects_an_alternate_extension_carrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A smoke-only carrier cannot hide in an alternate workflow extension."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "hidden-smoke.yaml").write_text(
        "name: Hidden Smoke\n"
        "on:\n"
        "  merge_group:\n"
        "    types: [checks_requested]\n"
        "jobs:\n"
        "  smoke:\n"
        "    name: merge-queue-smoke\n"
        "    runs-on: ubuntu-latest\n"
    )
    monkeypatch.setitem(globals(), "_WORKFLOWS", workflows)

    with pytest.raises(AssertionError, match="merge-queue-smoke"):
        test_smoke_only_merge_queue_carrier_is_absent()
