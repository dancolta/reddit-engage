"""Tests for the reddit module's public-JSON path.

OAuth + PRAW were removed in v0.2 (see plan: OAuth removal). The module is
now a single public-JSON fetcher; tests below cover the user-fetch path
shape + the fetch_delta entry point.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import reddit  # noqa: E402


def test_fetch_delta_routes_to_public(tmp_path, monkeypatch):
    """fetch_delta must call _fetch_delta_public verbatim. No fallback paths."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    sentinel = [{"id": "abc", "title": "fixture"}]
    with patch.object(reddit, "_fetch_delta_public", return_value=sentinel) as mock_public:
        result = reddit.fetch_delta("sales", None, max_limit=10)
    mock_public.assert_called_once_with("sales", None, max_limit=10)
    assert result == sentinel


def test_fetch_user_about_returns_none_on_404(tmp_path, monkeypatch):
    """Public fallback path: 404 should return None, not crash."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    with patch.object(reddit, "fetch_json", return_value=None):
        assert reddit.fetch_user_about("nonexistent_user") is None


def test_fetch_user_about_normalizes_public_response(tmp_path, monkeypatch):
    """Public response shape, our internal user shape."""
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


def test_fetch_user_recent_subs_returns_none_on_404(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    with patch.object(reddit, "fetch_json", return_value=None):
        assert reddit.fetch_user_recent_subs("nonexistent") is None


def test_fetch_user_recent_subs_builds_histogram(tmp_path, monkeypatch):
    """Aggregates comment subs into a {sub: count} dict."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    payload = {
        "data": {
            "children": [
                {"data": {"subreddit": "sales"}},
                {"data": {"subreddit": "sales"}},
                {"data": {"subreddit": "ops"}},
                {"data": {"subreddit": None}},  # graceful skip
            ]
        }
    }
    with patch.object(reddit, "fetch_json", return_value=payload):
        out = reddit.fetch_user_recent_subs("u")
    assert out == {"sales": 2, "ops": 1}


def test_unsafe_username_rejected(tmp_path, monkeypatch):
    """Path-injection guard fires before any HTTP."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    called = []
    with patch.object(reddit, "fetch_json",
                      side_effect=lambda *a, **k: called.append(1)):
        assert reddit.fetch_user_about("../../etc/passwd") is None
        assert reddit.fetch_user_recent_subs("u/../foo") is None
    assert called == []


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
