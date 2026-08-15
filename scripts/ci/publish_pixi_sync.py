#!/usr/bin/env python3
"""Trusted publisher for Dependabot pixi-sync results (Hermes).

Security boundary: this script runs only inside the workflow_run-triggered
writer workflow (dependabot-pixi-sync-writer.yml), which GitHub grants a
write-scoped token. It must NEVER check out or execute pull-request code.
The regenerated files arrive as an untrusted artifact produced by the
read-only producer (dependabot-pixi-sync.yml); this script treats them as
data, re-validates them against the trusted default-branch copy of
check_dep_sync.py, and only then creates a GitHub-signed commit on the PR
head branch.

The commit is created with the ``createCommitOnBranch`` GraphQL mutation so
the resulting commit carries a VERIFIED GitHub signature (satisfying the
fleet requirement that every commit be verified-signed).
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

GENERATOR_WORKFLOW = "Regenerate pixi.lock on Dependabot PRs"
GENERATOR_WORKFLOW_PATH = ".github/workflows/dependabot-pixi-sync.yml"
TARGET_REPOSITORY = "HomericIntelligence/Hermes"
GENERATED_FILES = ("pixi.toml", "pixi.lock")

CREATE_COMMIT_MUTATION = """
mutation PublishPixiSync($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) {
    commit {
      oid
      signature {
        state
        isSignedByGitHub
      }
    }
  }
}
"""


class PublishError(RuntimeError):
    """Fatal publisher failure; the message is surfaced verbatim in CI."""


def _string(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise PublishError(f"{description} is missing or not a non-empty string")
    return value


def _mapping(value: Any, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublishError(f"{description} is missing or not an object")
    return value


def _validate_oid(oid: str, description: str = "object ID") -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", oid):
        raise PublishError(f"{description} is not a 40-hex OID: {oid!r}")


def load_workflow_run_context(event_path: str) -> dict[str, Any]:
    """Extract and validate trusted metadata from the workflow_run webhook."""
    try:
        with open(event_path, "r", encoding="utf-8") as fh:
            event = json.load(fh)
    except (OSError, json.JSONDecodeError) as error:
        raise PublishError(f"cannot read workflow_run event: {error}") from error

    workflow_run = _mapping(event.get("workflow_run"), "workflow_run")
    if workflow_run.get("name") != GENERATOR_WORKFLOW:
        raise PublishError("workflow_run came from an unexpected workflow")
    if workflow_run.get("path") != GENERATOR_WORKFLOW_PATH:
        raise PublishError("workflow_run came from an unexpected workflow path")
    if workflow_run.get("event") != "pull_request" or workflow_run.get("conclusion") != "success":
        raise PublishError("workflow_run must be a successful pull_request run")
    actor = _mapping(workflow_run.get("actor"), "workflow_run actor")
    if actor.get("login") != "dependabot[bot]":
        raise PublishError("workflow_run actor is not Dependabot")
    head_repository = _mapping(workflow_run.get("head_repository"), "workflow_run head repository")
    if head_repository.get("full_name") != TARGET_REPOSITORY:
        raise PublishError("workflow_run head repository is not the target repository")
    repository = _mapping(workflow_run.get("repository"), "workflow_run repository")
    if repository.get("full_name") != TARGET_REPOSITORY:
        raise PublishError("workflow_run repository is not the target repository")

    head_ref = _string(workflow_run.get("head_branch"), "workflow_run head branch")
    if head_ref.startswith("refs/heads/"):
        head_ref = head_ref[len("refs/heads/"):]
    if head_ref == "main" or not head_ref:
        raise PublishError("workflow_run head branch is not a feature branch")
    head_sha = _string(workflow_run.get("head_sha"), "workflow_run head SHA")
    _validate_oid(head_sha, "workflow_run head SHA")
    return {
        "head_ref": head_ref,
        "head_sha": head_sha,
        "run_id": workflow_run.get("id"),
    }


def validate_artifact(artifact_dir: Path, pyproject_bytes: bytes) -> dict[str, bytes]:
    """Validate the artifact contains exactly the two generated files.

    pixi.toml must parse as TOML, and the local trusted copy of
    check_dep_sync.py (checked out from the default branch by the workflow)
    must report parity OK against the PR pyproject.toml carried in the
    artifact. Returns {filename: bytes}.
    """
    if not artifact_dir.is_dir():
        raise PublishError(f"artifact directory missing: {artifact_dir}")
    contents: dict[str, bytes] = {}
    for name in GENERATED_FILES:
        path = artifact_dir / name
        if not path.is_file():
            raise PublishError(f"artifact is missing {name}")
        data = path.read_bytes()
        if not data or b"\x00" in data:
            raise PublishError(f"artifact {name} is empty or contains NUL bytes")
        contents[name] = data

    # pixi.toml must parse (tomllib available on runner Python >= 3.11).
    import tomllib  # noqa: PLC0415

    try:
        tomllib.loads(contents["pixi.toml"].decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PublishError(f"artifact pixi.toml is not valid TOML: {error}") from error

    # Re-run the trusted parity gate against the artifact pixi.toml +
    # the PR pyproject.toml (packaged by the producer). The script used is
    # the trusted default-branch copy (checked out by the workflow), never
    # code from the PR.
    import importlib.util  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        (tmp_root / "pyproject.toml").write_bytes(pyproject_bytes)
        (tmp_root / "pixi.toml").write_bytes(contents["pixi.toml"])
        check_dep_sync = Path(__file__).resolve().parents[1] / "check_dep_sync.py"
        if not check_dep_sync.is_file():
            raise PublishError("trusted check_dep_sync.py is not present in the writer checkout")
        spec = importlib.util.spec_from_file_location("check_dep_sync_trusted", check_dep_sync)
        if not spec or not spec.loader:
            raise PublishError("cannot load trusted check_dep_sync.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["check_dep_sync_trusted"] = module
        spec.loader.exec_module(module)
        # check_dep_sync.py reads PYPROJECT / PIXI from its module globals;
        # setattr keeps mypy happy (ModuleType has no such attributes).
        setattr(module, "PYPROJECT", tmp_root / "pyproject.toml")
        setattr(module, "PIXI", tmp_root / "pixi.toml")
        rc = module.main()
        if rc != 0:
            raise PublishError("artifact pixi.toml fails the parity gate against PR pyproject.toml")
    return contents


def create_signed_commit(
    *,
    head_sha: str,
    head_ref: str,
    files: dict[str, bytes],
) -> str:
    """Create a GitHub-signed commit on the PR head branch via GraphQL."""
    token = _string(__import__("os").environ.get("GITHUB_TOKEN"), "GITHUB_TOKEN")
    file_changes = [
        {
            "path": name,
            "contents": base64.b64encode(data).decode("ascii"),
        }
        for name, data in files.items()
    ]
    variables = {
        "input": {
            "branch": {"repositoryNameWithOwner": TARGET_REPOSITORY, "branchName": head_ref},
            "message": {
                "headline": "chore(deps): regenerate pixi.lock for Dependabot update",
                "body": (
                    "Auto-generated by dependabot-pixi-sync writer. Syncs pixi.toml "
                    "[pypi-dependencies] ranges from pyproject.toml and regenerates "
                    "pixi.lock so the parity + locked-install gates pass on the "
                    "Dependabot PR. Signed by GitHub (createCommitOnBranch)."
                ),
            },
            "expectedHeadOid": head_sha,
            "fileChanges": {"additions": file_changes},
        }
    }
    result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f"query={CREATE_COMMIT_MUTATION}",
            "-f", f"variables={json.dumps(variables)}",
        ],
        capture_output=True,
        text=True,
        env={"PATH": __import__("os").environ.get("PATH", ""), "GITHUB_TOKEN": token},
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise PublishError(f"createCommitOnBranch failed: {detail}")
    try:
        data = json.loads(result.stdout)
        commit = _mapping(
            data.get("data", {}).get("createCommitOnBranch", {}).get("commit"), "created commit"
        )
        signature = _mapping(commit.get("signature"), "created commit signature")
    except (json.JSONDecodeError, PublishError) as error:
        raise PublishError(f"createCommitOnBranch returned an unexpected payload: {error}") from error
    if signature.get("state") != "VALID" or signature.get("isSignedByGitHub") is not True:
        raise PublishError("created commit signature is not GitHub-verified")
    oid = _string(commit.get("oid"), "created commit OID")
    _validate_oid(oid, "created commit OID")
    return oid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", required=True, help="GITHUB_EVENT_PATH (workflow_run webhook)")
    parser.add_argument("--artifact-dir", required=True, help="downloaded artifact directory")
    parser.add_argument(
        "--pyproject-path",
        required=True,
        help="PR pyproject.toml bytes packaged by the producer",
    )
    args = parser.parse_args(argv)

    try:
        context = load_workflow_run_context(args.event_path)
        pyproject = Path(args.pyproject_path).read_bytes()
        files = validate_artifact(Path(args.artifact_dir), pyproject)
        oid = create_signed_commit(
            head_sha=context["head_sha"],
            head_ref=context["head_ref"],
            files=files,
        )
    except PublishError as error:
        print(f"::error::pixi-sync publish failed: {error}", file=sys.stderr)
        return 1

    print(f"Published regenerated pixi files as signed commit {oid[:12]} on {context['head_ref']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
