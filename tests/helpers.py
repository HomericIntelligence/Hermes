"""Shared test helpers for ProjectHermes tests."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod


def sign_body(secret: str, body: bytes) -> str:
    """Return the HMAC-SHA256 hex digest of *body* signed with *secret*."""
    return hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
