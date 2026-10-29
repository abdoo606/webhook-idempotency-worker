"""HMAC-SHA256 signing, as used by most payment and messaging providers."""
from __future__ import annotations

import hashlib
import hmac
import time


def sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Return ``t=<unix>,v1=<hex>``. The timestamp is part of the signed bytes,
    so a captured payload cannot be replayed forever."""
    if not secret:
        raise ValueError("secret must not be empty")
    ts = int(timestamp if timestamp is not None else time.time())
    signed = f"{ts}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def verify(payload: bytes, header: str, secret: str, tolerance_seconds: int = 300,
           now: int | None = None) -> bool:
    """Constant-time check plus a timestamp window. Returns False, never raises."""
    if not header or not secret:
        return False
    parts = dict(
        piece.split("=", 1) for piece in header.split(",") if "=" in piece
    )
    try:
        ts = int(parts["t"])
        provided = parts["v1"]
    except (KeyError, ValueError):
        return False
    current = int(now if now is not None else time.time())
    if abs(current - ts) > tolerance_seconds:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)
