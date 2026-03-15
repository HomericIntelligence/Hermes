"""Tests for the FastAPI webhook endpoints."""

from __future__ import annotations

import sys
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _build_client() -> TestClient:
    """Build a TestClient with a mocked Publisher injected into app.state."""
    from hermes.server import app
    from hermes.publisher import Publisher

    mock_publisher = MagicMock(spec=Publisher)
    mock_publisher.is_connected = True
    mock_publisher.active_subjects = []
    mock_publisher.publish = AsyncMock()

    # Inject the mock before the test client starts
    app.state.publisher = mock_publisher
    return TestClient(app, raise_server_exceptions=True)


class TestHealthEndpoint:
    def test_health_returns_200(self) -> None:
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


class TestWebhookEndpoint:
    def test_valid_payload_returns_202(self) -> None:
        client = _build_client()
        payload = {
            "event": "agent.created",
            "data": {"host": "localhost", "name": "bot"},
            "timestamp": "2026-03-15T00:00:00Z",
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 202

    def test_webhook_invalid_payload_returns_422(self) -> None:
        client = _build_client()
        response = client.post("/webhook", json={"bad": "payload"})
        assert response.status_code == 422

    def test_webhook_missing_body_returns_422(self) -> None:
        client = _build_client()
        response = client.post("/webhook", content=b"not json", headers={"Content-Type": "application/json"})
        assert response.status_code == 422

    def test_webhook_returns_event_name(self) -> None:
        client = _build_client()
        payload = {
            "event": "task.updated",
            "data": {"team_id": "t1", "task_id": "task-1"},
            "timestamp": "2026-03-15T00:00:00Z",
        }
        body = client.post("/webhook", json=payload).json()
        assert body["event"] == "task.updated"


class TestSubjectsEndpoint:
    def test_subjects_returns_list(self) -> None:
        client = _build_client()
        body = client.get("/subjects").json()
        assert "subjects" in body
        assert isinstance(body["subjects"], list)
