"""Tests for the merged reddit module's graceful-fallback contract.

We don't unit-test PRAW (it's a third-party lib); we test that:
  - has_oauth() correctly detects oauth.json presence + completeness
  - fetch_delta() falls back to public JSON when no oauth.json
  - fetch_delta() falls back to public JSON when OAuth raises
  - fetch_user_about() returns None on 404
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import reddit  # noqa: E402


def test_has_oauth_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    assert reddit.has_oauth() is False


def test_has_oauth_false_when_incomplete(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    (tmp_path / "oauth.json").write_text(json.dumps({"client_id": "x"}))  # missing secret + username
    assert reddit.has_oauth() is False


def test_has_oauth_true_when_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    (tmp_path / "oauth.json").write_text(json.dumps({
        "client_id": "abc",
        "client_secret": "def",
        "username": "ghi",
    }))
    assert reddit.has_oauth() is True


def test_has_oauth_false_on_malformed_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    (tmp_path / "oauth.json").write_text("not-json{{{")
    assert reddit.has_oauth() is False


def test_fetch_delta_no_oauth_falls_back_to_public(tmp_path, monkeypatch):
    """No oauth.json → must call the public-path fetcher verbatim."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    sentinel = [{"id": "abc", "title": "fixture"}]
    with patch.object(reddit, "_fetch_delta_public", return_value=sentinel) as mock_public:
        result = reddit.fetch_delta("sales", None, max_limit=10)
    mock_public.assert_called_once_with("sales", None, max_limit=10)
    assert result == sentinel


def test_fetch_delta_oauth_failure_falls_back(tmp_path, monkeypatch):
    """oauth.json present but OAuth path raises → falls back to public, doesn't crash."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    (tmp_path / "oauth.json").write_text(json.dumps({
        "client_id": "x", "client_secret": "y", "username": "z",
    }))
    sentinel = [{"id": "fb", "title": "fallback"}]
    with patch.object(reddit, "_fetch_delta_oauth", side_effect=RuntimeError("token expired")):
        with patch.object(reddit, "_fetch_delta_public", return_value=sentinel) as mock_pub:
            result = reddit.fetch_delta("sales", None, max_limit=10)
    mock_pub.assert_called_once()
    assert result == sentinel


def test_fetch_user_about_returns_none_on_404(tmp_path, monkeypatch):
    """Public fallback path: 404 should return None, not crash."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    with patch.object(reddit, "fetch_json", return_value=None):
        assert reddit.fetch_user_about("nonexistent_user") is None


def test_fetch_user_about_normalizes_public_response(tmp_path, monkeypatch):
    """Public response shape → our internal user shape."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    public_payload = {
        "data": {
            "name": "test_user",
            "comment_karma": 542,
            "link_karma": 13,
            "created_utc": 1500000000,
            "is_employee": False,
            "has_verified_email": True,
        }
    }
    with patch.object(reddit, "fetch_json", return_value=public_payload):
        result = reddit.fetch_user_about("test_user")
    assert result["comment_karma"] == 542
    assert result["verified"] is True
    assert result["created_utc"] == 1500000000


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
