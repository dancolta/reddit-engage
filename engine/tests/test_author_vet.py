"""Tests for author quality pre-gate.

Mocks the Reddit fetches (reddit_oauth.fetch_user_about / fetch_user_recent_subs)
since we can't hit the real API in CI.
"""
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reddit_engage.lib import author_vet  # noqa: E402


NOW = 1748100000


def make_about(karma=200, age_days=365, **overrides):
    base = {
        "name": "test_user",
        "comment_karma": karma,
        "link_karma": 50,
        "created_utc": NOW - age_days * 86400,
        "is_employee": False,
        "verified": True,
    }
    base.update(overrides)
    return base


def test_deleted_author_fails_immediately():
    result = author_vet.vet_author("[deleted]", now=NOW)
    assert result["verdict"] == "fail"
    assert result["reason"] == "deleted_or_private"


def test_account_too_young_fails():
    about = make_about(karma=500, age_days=10)  # 10d old, fails 30d min
    with patch.object(author_vet.reddit_oauth, "fetch_user_about", return_value=about):
        result = author_vet.vet_author("babyacct", now=NOW)
    assert result["verdict"] == "fail"
    assert result["reason"] == "account_too_young"
    assert result["account_age_days"] == 10


def test_low_karma_fails():
    about = make_about(karma=10, age_days=200)
    with patch.object(author_vet.reddit_oauth, "fetch_user_about", return_value=about):
        result = author_vet.vet_author("lurker42", now=NOW)
    assert result["verdict"] == "fail"
    assert result["reason"] == "low_karma"


def test_wrong_audience_fails():
    """OP whose comments are >80% in r/Entrepreneur class subs = drop."""
    about = make_about(karma=500, age_days=365)
    sub_hist = {"Entrepreneur": 60, "smallbusiness": 25, "startups": 12, "sales": 3}
    with patch.object(author_vet.reddit_oauth, "fetch_user_about", return_value=about):
        with patch.object(author_vet.reddit_oauth, "fetch_user_recent_subs", return_value=sub_hist):
            result = author_vet.vet_author("hustlebro", now=NOW)
    assert result["verdict"] == "fail"
    assert result["reason"] == "wrong_audience"
    assert result["wrong_audience_fraction"] >= 0.97


def test_real_operator_passes():
    """Operator OP: good karma, mature account, distributed sub activity."""
    about = make_about(karma=500, age_days=365)
    sub_hist = {"sales": 40, "RevOps": 30, "CFO": 20, "Entrepreneur": 5, "askmenover30": 5}
    with patch.object(author_vet.reddit_oauth, "fetch_user_about", return_value=about):
        with patch.object(author_vet.reddit_oauth, "fetch_user_recent_subs", return_value=sub_hist):
            result = author_vet.vet_author("real_operator", now=NOW)
    assert result["verdict"] == "pass"
    assert result["reason"] is None


def test_fetch_failure_degrades_open():
    """If Reddit returns None (404, suspended, network), default to pass —
    don't kill a real lead because the API hiccuped."""
    with patch.object(author_vet.reddit_oauth, "fetch_user_about", return_value=None):
        result = author_vet.vet_author("unreachable", now=NOW)
    assert result["verdict"] == "pass"
    assert result["reason"] == "fetch_failed"


def test_cache_hit_skips_network(tmp_path):
    """Second call within TTL must hit cache, not fetch_user_about."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    author_vet.ensure_schema(conn)

    about = make_about(karma=500, age_days=365)
    sub_hist = {"sales": 50, "RevOps": 50}

    with patch.object(author_vet.reddit_oauth, "fetch_user_about", return_value=about) as m_about:
        with patch.object(author_vet.reddit_oauth, "fetch_user_recent_subs", return_value=sub_hist) as m_subs:
            r1 = author_vet.vet_author("cache_test", conn=conn, now=NOW)
            r2 = author_vet.vet_author("cache_test", conn=conn, now=NOW + 60)
    assert r1["verdict"] == "pass"
    assert r1["from_cache"] is False
    assert r2["verdict"] == "pass"
    assert r2["from_cache"] is True
    # Network calls: exactly once (first call), not twice
    assert m_about.call_count == 1
    assert m_subs.call_count == 1


def test_cache_expires_after_ttl(tmp_path):
    """After CACHE_TTL_SECONDS (7d), refetch instead of returning stale."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    author_vet.ensure_schema(conn)
    about = make_about(karma=500, age_days=365)
    sub_hist = {"sales": 100}

    with patch.object(author_vet.reddit_oauth, "fetch_user_about", return_value=about) as m_about:
        with patch.object(author_vet.reddit_oauth, "fetch_user_recent_subs", return_value=sub_hist):
            author_vet.vet_author("stale_test", conn=conn, now=NOW)
            # 8 days later
            author_vet.vet_author("stale_test", conn=conn, now=NOW + 8 * 86400)
    assert m_about.call_count == 2  # refetched


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
