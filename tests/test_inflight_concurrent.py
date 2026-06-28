"""Concurrent integration tests for the _inflight counter.

Complements tests/test_inflight.py (synchronous TestClient) by exercising
_inflight_context under genuine async concurrency via httpx.AsyncClient +
ASGITransport. Closes #442; follow-up to #322.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.helpers import TEST_SECRET, sign_body

_AGENT_PAYLOAD = {
    "event": "agent.created",
    "data": {"host": "h", "name": "n"},
    "timestamp": "2026-04-22T00:00:00Z",
}
_BODY = json.dumps(_AGENT_PAYLOAD).encode()
_HEADERS = {
    "X-Webhook-Signature": sign_body(_BODY, TEST_SECRET),
    "Content-Type": "application/json",
}


def _make_mock_publisher(*, connected: bool = True) -> MagicMock:
    from hermes.publisher import Publisher

    mock = MagicMock(spec=Publisher)
    mock.is_connected = connected
    mock.active_subjects = []
    mock.dead_letter_count = 0
    mock.active_subjects_max = 1000
    mock.publish = AsyncMock()
    mock.disconnect = AsyncMock()
    mock.reconnect_count = 0
    mock.last_error = ""
    mock.last_reconnect_attempt_at = None
    mock.consecutive_reconnect_failures = 0
    mock.reconnect_loop_running = False
    return mock


@pytest.fixture(autouse=True)
def _refresh_inflight_lock() -> None:
    """Rebind _inflight_lock to the current event loop.

    asyncio.Lock created at module import (src/hermes/server.py:47) may be
    bound to a stale loop under asyncio_mode=auto, which silently corrupts
    locking. Re-creating the lock at test start guarantees it lives on the
    same loop as the handler coroutines.
    """
    import hermes.server as srv

    srv._inflight_lock = asyncio.Lock()


@pytest_asyncio.fixture()
async def env(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[MagicMock]:
    """Common setup: mock publisher, secret, lifted rate limit, AsyncClient-ready app.

    Yields the mock publisher so tests can replace ``publish`` per case.
    Uses monkeypatch.setenv + get_settings.cache_clear() per the established
    pattern in tests/test_rate_limit.py:42-57 — slowapi re-reads
    get_settings().webhook_rate_limit per request via the lambda in
    src/hermes/server.py:395, so an env-level override is what actually lifts
    the limit at request time.
    """
    from hermes.config import get_settings
    from hermes.rate_limit import limiter
    from hermes.server import app

    monkeypatch.setenv("WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setenv("WEBHOOK_RATE_LIMIT", "10000/minute")
    get_settings.cache_clear()
    limiter._storage.reset()  # type: ignore[attr-defined]

    publisher = _make_mock_publisher()
    app.state.publisher = publisher
    yield publisher


async def _wait_for_inflight(expected: int, timeout: float = 5.0) -> int:
    """Poll srv._inflight until it == expected; return observed value or raise.

    Does NOT acquire _inflight_lock — a plain int read is atomic in CPython,
    and avoiding the lock here prevents contention with the handler's
    increment path (src/hermes/server.py:71-72). The /health endpoint reads
    the same int without locking (src/hermes/server.py:346), so this matches
    production access semantics.
    """
    import hermes.server as srv

    async def _poll() -> int:
        while srv._inflight != expected:
            await asyncio.sleep(0.005)
        return srv._inflight

    return await asyncio.wait_for(_poll(), timeout=timeout)


def _client() -> AsyncClient:
    from hermes.server import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestInflightUnderConcurrency:
    async def test_inflight_reaches_n_with_n_concurrent_requests(
        self, env: MagicMock
    ) -> None:
        """N requests held inside publish() must all be counted simultaneously.

        Acceptance criterion: "two requests in flight simultaneously should
        show _inflight == 2" — verified here for N=5.
        """
        import hermes.server as srv

        n = 5
        gate = asyncio.Event()

        async def _blocking(*args: object, **kwargs: object) -> None:
            await gate.wait()

        env.publish = AsyncMock(side_effect=_blocking)

        async def _run_gather() -> list:
            result = await asyncio.gather(
                *(client.post("/webhook", content=_BODY, headers=_HEADERS) for _ in range(n))
            )
            return result

        async with _client() as client:
            gather_task = asyncio.create_task(_run_gather())
            await asyncio.sleep(0.01)
            try:
                peak = await _wait_for_inflight(n)
                assert peak == n, f"Expected _inflight == {n}, got {peak}"
            finally:
                gate.set()
            responses = await gather_task

        assert all(r.status_code == 202 for r in responses)
        assert srv._inflight == 0
        assert env.publish.await_count == n

    async def test_inflight_returns_to_zero_after_gather(
        self, env: MagicMock
    ) -> None:
        """After all concurrent requests resolve, _inflight is back to 0."""
        import hermes.server as srv

        async with _client() as client:
            responses = await asyncio.gather(
                *(
                    client.post("/webhook", content=_BODY, headers=_HEADERS)
                    for _ in range(10)
                )
            )

        assert all(r.status_code == 202 for r in responses)
        assert srv._inflight == 0

    async def test_inflight_peak_count_accurate_under_n_concurrent_requests(
        self, env: MagicMock
    ) -> None:
        """Counter reaches exactly N mid-flight and returns to 0 under N=20 load.

        Verifies peak-count accuracy, not lock mutual exclusion: under cooperative
        asyncio scheduling, ``_inflight += 1`` in ``_inflight_context`` has no await
        between read and write, so it cannot be interleaved and the lock is not
        exercised by simply issuing concurrent requests. What this test does prove
        is that with N=20 requests held inside publish(), the counter reaches
        exactly N (no requests dropped or double-counted) and drains back to 0 once
        all requests complete.
        """
        import hermes.server as srv

        n = 20
        gate = asyncio.Event()

        async def _blocking(*args: object, **kwargs: object) -> None:
            await gate.wait()

        env.publish = AsyncMock(side_effect=_blocking)

        async def _run_gather() -> list:
            return await asyncio.gather(
                *(client.post("/webhook", content=_BODY, headers=_HEADERS) for _ in range(n))
            )

        async with _client() as client:
            gather_task = asyncio.create_task(_run_gather())
            await asyncio.sleep(0.01)
            try:
                peak = await _wait_for_inflight(n)
                assert peak == n, f"Expected _inflight == {n}, got {peak}"
            finally:
                gate.set()
            responses = await gather_task

        assert all(r.status_code == 202 for r in responses)
        assert srv._inflight == 0
        assert env.publish.await_count == n

    async def test_health_reflects_peak_inflight_count(self, env: MagicMock) -> None:
        """The /health endpoint accurately reports peak _inflight reached during load."""
        import hermes.server as srv

        n = 3
        gate = asyncio.Event()

        async def _blocking(*args: object, **kwargs: object) -> None:
            await gate.wait()

        env.publish = AsyncMock(side_effect=_blocking)

        async def _run_gather() -> list:
            return await asyncio.gather(
                *(client.post("/webhook", content=_BODY, headers=_HEADERS) for _ in range(n))
            )

        async with _client() as client:
            gather_task = asyncio.create_task(_run_gather())
            await asyncio.sleep(0.01)
            try:
                peak = await _wait_for_inflight(n)
                health = await client.get("/health")
                health_data = health.json()
                assert health_data["inflight_requests"] == n
            finally:
                gate.set()
            responses = await gather_task

        assert all(r.status_code == 202 for r in responses)
        assert srv._inflight == 0

    async def test_inflight_decrements_correctly_on_concurrent_errors(
        self, env: MagicMock
    ) -> None:
        """Errors in concurrent requests correctly decrement _inflight.

        Uses asyncio.TimeoutError as the publish error because _handle_webhook
        catches it and returns a real 503 HTTP response (server.py line 441-451).
        RuntimeError is NOT caught by _handle_webhook, so with ASGITransport's
        default raise_app_exceptions=True it would propagate out of the ASGI
        app — making r.status_code == 503 unreachable dead code.
        """
        import hermes.server as srv

        n = 5
        gate = asyncio.Event()

        async def _blocking(*args: object, **kwargs: object) -> None:
            await gate.wait()
            raise asyncio.TimeoutError()

        env.publish = AsyncMock(side_effect=_blocking)

        async def _run_gather() -> list:
            return await asyncio.gather(
                *(client.post("/webhook", content=_BODY, headers=_HEADERS) for _ in range(n))
            )

        async with _client() as client:
            gather_task = asyncio.create_task(_run_gather())
            await asyncio.sleep(0.01)
            try:
                peak = await _wait_for_inflight(n)
                assert peak == n, f"Expected _inflight == {n}, got {peak}"
            finally:
                gate.set()
            responses = await gather_task

        assert all(r.status_code == 503 for r in responses)
        assert srv._inflight == 0
