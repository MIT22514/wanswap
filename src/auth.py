"""Shared-secret authentication for the swap service.

Kept in its own module, free of heavy imports, so it can be unit tested without
pulling in onnxruntime and insightface.
"""
import hmac

DEFAULT_TOKEN_PATH = "/workspace/.auth"


def load_auth(path=DEFAULT_TOKEN_PATH):
    """Read the shared token. Missing or unreadable file means "no token configured"."""
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def auth_ok(supplied, expected):
    """Constant-time comparison. An empty `expected` allows everything (dev mode only)."""
    if not expected:
        return True
    return hmac.compare_digest(str(supplied or ""), expected)
