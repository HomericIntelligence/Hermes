"""Tests for NATS subject routing logic in hermes.publisher."""

from __future__ import annotations

import sys
import os

# Ensure src is on the path when running directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hermes.publisher import Publisher


def _make_publisher() -> Publisher:
    return Publisher()


class TestAgentSubjectMapping:
    """Agent event → NATS subject routing."""

    def test_agent_created(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_agent_subject(
            {"host": "docker-desktop", "name": "researcher"},
            "agent.created",
        )
        assert subject == "hi.agents.docker-desktop.researcher.created"

    def test_agent_updated(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_agent_subject(
            {"host": "worker-01", "name": "analyst"},
            "agent.updated",
        )
        assert subject == "hi.agents.worker-01.analyst.updated"

    def test_agent_deleted(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_agent_subject(
            {"host": "worker-01", "name": "scout"},
            "agent.deleted",
        )
        assert subject == "hi.agents.worker-01.scout.deleted"

    def test_missing_host_falls_back_to_unknown(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_agent_subject({"name": "bot"}, "agent.created")
        assert subject == "hi.agents.unknown.bot.created"

    def test_missing_name_falls_back_to_unknown(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_agent_subject({"host": "myhost"}, "agent.created")
        assert subject == "hi.agents.myhost.unknown.created"

    def test_spaces_in_tokens_are_slugified(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_agent_subject(
            {"host": "my host", "name": "my agent"},
            "agent.created",
        )
        assert " " not in subject
        assert subject == "hi.agents.my-host.my-agent.created"


class TestTaskSubjectMapping:
    """Task event → NATS subject routing."""

    def test_task_updated(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_task_subject(
            {"team_id": "team-alpha", "task_id": "task-42"},
            "task.updated",
        )
        assert subject == "hi.tasks.team-alpha.task-42.updated"

    def test_task_completed(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_task_subject(
            {"team_id": "team-beta", "task_id": "t-99"},
            "task.completed",
        )
        assert subject == "hi.tasks.team-beta.t-99.completed"

    def test_missing_team_id_falls_back_to_unknown(self) -> None:
        pub = _make_publisher()
        subject = pub._parse_task_subject({"task_id": "t-1"}, "task.updated")
        assert subject == "hi.tasks.unknown.t-1.updated"

    def test_alternate_id_key(self) -> None:
        """task_id falls back to 'id' if 'task_id' is absent."""
        pub = _make_publisher()
        subject = pub._parse_task_subject(
            {"team_id": "alpha", "id": "xyz"},
            "task.updated",
        )
        assert subject == "hi.tasks.alpha.xyz.updated"
