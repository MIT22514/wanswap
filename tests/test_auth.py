"""Unit tests for the shared-secret auth used by the swap service.

Run: python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import auth  # noqa: E402


def test_correct_token_accepted():
    assert auth.auth_ok("s3cret", "s3cret") is True


def test_wrong_token_rejected():
    assert auth.auth_ok("nope", "s3cret") is False


def test_empty_supplied_rejected_when_token_set():
    for supplied in ("", None):
        assert auth.auth_ok(supplied, "s3cret") is False


def test_prefix_is_not_enough():
    """Guards against a comparison that stops at the first differing byte."""
    assert auth.auth_ok("s3cre", "s3cret") is False
    assert auth.auth_ok("s3cretx", "s3cret") is False


def test_no_token_configured_allows_everything():
    """Dev mode: an unset token disables auth rather than locking everyone out."""
    assert auth.auth_ok("anything", "") is True
    assert auth.auth_ok("", "") is True


def test_missing_token_file_reads_as_unset():
    assert auth.load_auth("/nonexistent/path/.auth") == ""
