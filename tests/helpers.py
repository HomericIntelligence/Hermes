"""Shared test utilities for ProjectHermes tests."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
from datetime import datetime, timezone

TEST_SECRET = "test-webhook-secret-padding-xxxxx"

# Canonical fixed timestamp shared by tests/conftest.py and tests/test_integration.py.
# Follow-up from #330; closes #471.
FIXED_TS = datetime(2026, 4, 22, tzinfo=timezone.utc)


def sign_body(body: bytes, secret: str) -> str:
    """Return the HMAC-SHA256 hex digest of *body* signed with *secret*."""
    return hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
