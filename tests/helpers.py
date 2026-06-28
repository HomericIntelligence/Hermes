"""Shared test utilities for ProjectHermes tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod
from collections.abc import Sized
from datetime import datetime, timezone

TEST_SECRET = "test-webhook-secret-padding-xxxxx"

# Canonical fixed timestamp shared by tests/conftest.py and tests/test_integration.py.
# Follow-up from #330; closes #471.
FIXED_TS = datetime(2026, 4, 22, tzinfo=timezone.utc)


def sign_body(body: bytes, secret: str) -> str:
    """Return the HMAC-SHA256 hex digest of *body* signed with *secret*."""
    return hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def wait_for_messages(
    received: Sized,
    expected: int,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.025,
) -> None:
    """Block until ``len(received) >= expected`` or raise ``asyncio.TimeoutError``.

    Replaces fixed ``asyncio.sleep(...)`` waits in NATS integration tests that
    race against callback delivery under suite-wide CPU contention (issues #428, #674).
    """

    async def _poll() -> None:
        while len(received) < expected:
            await asyncio.sleep(poll_interval)

    await asyncio.wait_for(_poll(), timeout=timeout)
