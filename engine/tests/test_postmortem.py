"""Tests for postmortem (reply detection + outcome scoring).

Mocks the Reddit API. Live testing requires Dan's OAuth credentials.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subseek.lib import postmortem, store  # noqa: E402


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    postmortem.ensure_schema(conn)
    return conn


def seed_surfaced(conn, post_id="abc01"):
    """Insert a surfaced post so postmortem can match against it."""
    conn.execute("INSERT INTO runs(started_at) VALUES(?)", (int(time.time()),))
    rid = conn.execute("SELECT id FROM runs").fetchone()[0]
    now = int(time.time())
    conn.execute(
        "INSERT INTO posts(id, subreddit, title, url, canonical_url, author, "
        "created_utc, score, num_comments, body, first_seen_at, score_internal, removed) "
        "VALUES(?, 'sales', 't', 'http://x/' || ?, 'http://r/' || ?, "
        "'op', ?, 5, 1, '', ?, 50, 0)",
        (post_id, post_id, post_id, now, now),
    )
    conn.execute(
        "INSERT INTO surfaced(post_id, surfaced_on, run_id, tier, state, surfaced_at) "
        "VALUES(?, '2026-05-25', ?, 2, 'hot', ?)",
        (post_id, rid, now - 10*86400),
    )


def test_no_oauth_short_circuits():
    """detect_replies returns 0-counts when no OAuth, doesn't crash."""
    conn = fresh_db()
    with patch.object(postmortem, "_own_username", return_value=None):
        result = postmortem.detect_replies(conn)
    assert result["scanned"] == 0
    assert result["new_matches"] == 0


def test_detect_replies_matches_parent_id():
    """When a fetched comment's parent_id matches a surfaced post, log it."""
    conn = fresh_db()
    seed_surfaced(conn, "abc01")
    fake_comments = [
        {"id": "c1", "permalink": "https://reddit.com/c/c1",
         "parent_id": "t3_abc01", "created_utc": int(time.time()) - 86400},
    ]
    with patch.object(postmortem, "_own_username", return_value="dancolta"):
        with patch.object(postmortem, "_fetch_own_comments", return_value=fake_comments):
            result = postmortem.detect_replies(conn)
    assert result["new_matches"] == 1
    row = conn.execute("SELECT * FROM reply_log WHERE post_id='abc01'").fetchone()
    assert row is not None
    assert row["comment_id"] == "c1"


def test_detect_replies_idempotent():
    """Second run with same comment must not duplicate the row."""
    conn = fresh_db()
    seed_surfaced(conn, "abc01")
    fake_comments = [
        {"id": "c1", "permalink": "https://reddit.com/c/c1",
         "parent_id": "t3_abc01", "created_utc": int(time.time()) - 86400},
    ]
    with patch.object(postmortem, "_own_username", return_value="dancolta"):
        with patch.object(postmortem, "_fetch_own_comments", return_value=fake_comments):
            r1 = postmortem.detect_replies(conn)
            r2 = postmortem.detect_replies(conn)
    assert r1["new_matches"] == 1
    assert r2["new_matches"] == 0
    assert r2["already_logged"] == 1


def test_detect_skips_unmatched_parents():
    """Comments that reply to posts we never surfaced are ignored."""
    conn = fresh_db()
    seed_surfaced(conn, "ours")
    fake = [
        {"id": "c1", "permalink": "...", "parent_id": "t3_NOTOURS",
         "created_utc": int(time.time()) - 86400},
    ]
    with patch.object(postmortem, "_own_username", return_value="dan"):
        with patch.object(postmortem, "_fetch_own_comments", return_value=fake):
            r = postmortem.detect_replies(conn)
    assert r["new_matches"] == 0


def test_update_outcomes_respects_7d_threshold():
    """Replies <7d old skip; ≥7d old get scored."""
    conn = fresh_db()
    seed_surfaced(conn, "old")
    seed_surfaced(conn, "fresh")
    now = int(time.time())
    conn.execute("INSERT INTO reply_log(post_id, comment_id, comment_url, replied_at) "
                 "VALUES('old', 'cold', 'u', ?)", (now - 10*86400,))
    conn.execute("INSERT INTO reply_log(post_id, comment_id, comment_url, replied_at) "
                 "VALUES('fresh', 'cfresh', 'u', ?)", (now - 1*86400,))
    fake_outcome = {"upvotes": 8, "num_replies": 2, "removed": False, "locked": False}
    with patch.object(postmortem, "_fetch_comment_outcome", return_value=fake_outcome):
        r = postmortem.update_outcomes(conn)
    assert r["scored"] == 1
    assert r["skipped_too_young"] == 1
    # Verify old got an outcome, fresh didn't
    old_row = conn.execute("SELECT outcome FROM reply_log WHERE post_id='old'").fetchone()
    fresh_row = conn.execute("SELECT outcome FROM reply_log WHERE post_id='fresh'").fetchone()
    assert old_row["outcome"] is not None
    assert fresh_row["outcome"] is None


def test_summary_aggregates_outcomes():
    """Lifetime summary aggregates upvotes/replies/removed across all scored."""
    conn = fresh_db()
    seed_surfaced(conn, "p1")
    seed_surfaced(conn, "p2")
    now = int(time.time())
    conn.execute("INSERT INTO reply_log(post_id, comment_id, comment_url, replied_at, outcome) "
                 "VALUES('p1', 'c1', 'u', ?, ?)",
                 (now, json.dumps({"upvotes": 10, "num_replies": 3, "removed": False, "locked": False})))
    conn.execute("INSERT INTO reply_log(post_id, comment_id, comment_url, replied_at, outcome) "
                 "VALUES('p2', 'c2', 'u', ?, ?)",
                 (now, json.dumps({"upvotes": 0, "num_replies": 0, "removed": True, "locked": False})))
    summ = postmortem.summary(conn)
    assert summ["total_replies"] == 2
    assert summ["scored"] == 2
    assert summ["avg_upvotes"] == 5.0
    assert summ["removed_count"] == 1


def test_summary_empty_db_doesnt_crash():
    conn = fresh_db()
    summ = postmortem.summary(conn)
    assert summ["total_replies"] == 0
    assert summ["avg_upvotes"] == 0.0
