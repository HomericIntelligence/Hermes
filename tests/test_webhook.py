"""Tests for the FastAPI webhook endpoints."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Fixed secret used across all webhook tests
_TEST_SECRET = "test-webhook-secret-padding-xxxxx"


def _sign(body: bytes) -> str:
    """Compute HMAC-SHA256 hex digest for the given body using _TEST_SECRET."""
    return hmac_mod.new(_TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _build_client() -> TestClient:
    """Build a TestClient with a mocked Publisher and a known webhook secret."""
    from hermes.config import settings
    from hermes.publisher import Publisher
    from hermes.server import app

    mock_publisher = MagicMock(spec=Publisher)
    mock_publisher.is_connected = True
    mock_publisher.active_subjects = []
    mock_publisher.publish = AsyncMock()

    # Inject the mock before the test client starts
    app.state.publisher = mock_publisher
    # Set a known secret so tests can compute valid signatures
    settings.webhook_secret = _TEST_SECRET
    return TestClient(app, raise_server_exceptions=True)


def _build_client_disconnected() -> TestClient:
    """Build a TestClient where the Publisher reports NATS as disconnected."""
    from hermes.server import app
    from hermes.publisher import Publisher

    mock_publisher = MagicMock(spec=Publisher)
    mock_publisher.is_connected = False
    mock_publisher.active_subjects = []
    mock_publisher.publish = AsyncMock()

    app.state.publisher = mock_publisher
    return TestClient(app, raise_server_exceptions=True)


class TestHealthEndpoint:
    """Tests for the GET /health liveness endpoint."""

    def test_health_returns_200_when_connected(self) -> None:
        client = _build_client()
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self) -> None:
        client = _build_client()
        body = client.get("/health").json()
        assert body["status"] == "ok"

    def test_health_includes_nats_connected(self) -> None:
        client = _build_client()
        body = client.get("/health").json()
        assert "nats_connected" in body

    def test_health_includes_hermes_public_url(self) -> None:
        client = _build_client()
        body = client.get("/health").json()
        assert "hermes_public_url" in body

    def test_health_returns_503_when_nats_disconnected(self) -> None:
        client = _build_client_disconnected()
        response = client.get("/health")
        assert response.status_code == 503

    def test_health_returns_degraded_status_when_nats_disconnected(self) -> None:
        client = _build_client_disconnected()
        body = client.get("/health").json()
        assert body["status"] == "degraded"

    def test_health_returns_nats_connected_false_when_disconnected(self) -> None:
        client = _build_client_disconnected()
        body = client.get("/health").json()
        assert body["nats_connected"] is False


class TestReadyEndpoint:
    def test_ready_returns_200_when_connected(self) -> None:
        client = _build_client()
        response = client.get("/ready")
        assert response.status_code == 200

    def test_ready_returns_ready_true_when_connected(self) -> None:
        client = _build_client()
        body = client.get("/ready").json()
        assert body["ready"] is True

    def test_ready_returns_503_when_nats_disconnected(self) -> None:
        client = _build_client_disconnected()
        response = client.get("/ready")
        assert response.status_code == 503

    def test_ready_returns_ready_false_when_disconnected(self) -> None:
        client = _build_client_disconnected()
        body = client.get("/ready").json()
        assert body["ready"] is False

    def test_ready_includes_reason_when_disconnected(self) -> None:
        client = _build_client_disconnected()
        body = client.get("/ready").json()
        assert "reason" in body


class TestWebhookEndpoint:
    def test_valid_payload_returns_202(self) -> None:
        client = _build_client()
        payload = {
            "event": "agent.created",
            "data": {"host": "localhost", "name": "bot"},
            "timestamp": "2026-03-15T00:00:00Z",
        }
        body_bytes = json.dumps(payload).encode()
        response = client.post(
            "/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": _sign(body_bytes),
            },
        )
        assert response.status_code == 202

    def test_webhook_invalid_payload_returns_422(self) -> None:
        client = _build_client()
        body_bytes = json.dumps({"bad": "payload"}).encode()
        response = client.post(
            "/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": _sign(body_bytes),
            },
        )
        assert response.status_code == 422

    def test_webhook_missing_body_returns_422(self) -> None:
        client = _build_client()
        body_bytes = b"not json"
        response = client.post(
            "/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": _sign(body_bytes),
            },
        )
        assert response.status_code == 422

    def test_webhook_returns_event_name(self) -> None:
        client = _build_client()
        payload = {
            "event": "task.updated",
            "data": {"team_id": "t1", "task_id": "task-1"},
            "timestamp": "2026-03-15T00:00:00Z",
        }
        body_bytes = json.dumps(payload).encode()
        response = client.post(
            "/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": _sign(body_bytes),
            },
        )
        body = response.json()
        assert body["event"] == "task.updated"

    def test_webhook_bad_signature_returns_401(self) -> None:
        client = _build_client()
        payload = {
            "event": "agent.created",
            "data": {"host": "localhost", "name": "bot"},
            "timestamp": "2026-03-15T00:00:00Z",
        }
        body_bytes = json.dumps(payload).encode()
        response = client.post(
            "/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": "bad-signature",
            },
        )
        assert response.status_code == 401


class TestSettings:
    def test_hermes_host_defaults_to_localhost(self) -> None:
        from hermes.config import Settings

        s = Settings()
        assert s.hermes_host == "127.0.0.1"


class TestSubjectsEndpoint:
    def test_subjects_returns_list(self) -> None:
        client = _build_client()
        body = client.get("/subjects").json()
        assert "subjects" in body
        assert isinstance(body["subjects"], list)


class TestUnknownEventType:
    """Tests for #125: unknown event types return 422 when dead-lettering is disabled."""

    def _build_client_with_unknown_event(self, event: str) -> TestClient:
        from hermes.publisher import UnknownEventTypeError, Publisher
        from hermes.server import app
        from hermes.config import settings

        mock_publisher = MagicMock(spec=Publisher)
        mock_publisher.is_connected = True
        mock_publisher.active_subjects = []
        mock_publisher.publish = AsyncMock(side_effect=UnknownEventTypeError(event))

        app.state.publisher = mock_publisher
        settings.webhook_secret = ""
        return TestClient(app, raise_server_exceptions=True)

    def test_unknown_event_type_raises_422(self) -> None:
        client = self._build_client_with_unknown_event("foo.bar")
        payload = {"event": "foo.bar", "data": {}, "timestamp": "2026-01-01T00:00:00Z"}
        body_bytes = json.dumps(payload).encode()
        response = client.post("/webhook", content=body_bytes, headers={"Content-Type": "application/json"})
        assert response.status_code == 422

    def test_unknown_event_type_422_detail_contains_event(self) -> None:
        client = self._build_client_with_unknown_event("foo.bar")
        payload = {"event": "foo.bar", "data": {}, "timestamp": "2026-01-01T00:00:00Z"}
        body_bytes = json.dumps(payload).encode()
        response = client.post("/webhook", content=body_bytes, headers={"Content-Type": "application/json"})
        body = response.json()
        assert "foo.bar" in body["detail"]


class TestMissingFieldWarnings:
    """Tests for #98: warnings logged when agent/task data fields are missing."""

    def test_missing_host_field_logs_warning(self) -> None:
        from unittest.mock import patch
        from hermes.publisher import Publisher

        with patch("hermes.publisher.logger") as mock_log:
            pub = Publisher()
            pub._parse_agent_subject({"name": "bot"}, "agent.created")
            warned_messages = [str(call.args) for call in mock_log.warning.call_args_list]
            assert any("host" in msg for msg in warned_messages)

    def test_missing_name_field_logs_warning(self) -> None:
        from unittest.mock import patch
        from hermes.publisher import Publisher

        with patch("hermes.publisher.logger") as mock_log:
            pub = Publisher()
            pub._parse_agent_subject({"host": "myhost"}, "agent.created")
            warned_messages = [str(call.args) for call in mock_log.warning.call_args_list]
            assert any("name" in msg for msg in warned_messages)

    def test_missing_team_id_field_logs_warning(self) -> None:
        from unittest.mock import patch
        from hermes.publisher import Publisher

        with patch("hermes.publisher.logger") as mock_log:
            pub = Publisher()
            pub._parse_task_subject({"task_id": "t-1"}, "task.updated")
            warned_messages = [str(call.args) for call in mock_log.warning.call_args_list]
            assert any("team_id" in msg for msg in warned_messages)

    def test_missing_task_id_field_logs_warning(self) -> None:
        from unittest.mock import patch
        from hermes.publisher import Publisher

        with patch("hermes.publisher.logger") as mock_log:
            pub = Publisher()
            pub._parse_task_subject({"team_id": "alpha"}, "task.updated")
            warned_messages = [str(call.args) for call in mock_log.warning.call_args_list]
            assert any("task_id" in msg for msg in warned_messages)

    def test_present_host_and_name_no_warning(self) -> None:
        from unittest.mock import patch
        from hermes.publisher import Publisher

        with patch("hermes.publisher.logger") as mock_log:
            pub = Publisher()
            pub._parse_agent_subject({"host": "myhost", "name": "bot"}, "agent.created")
            assert not mock_log.warning.called
