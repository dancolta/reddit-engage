"""Tests for the Obsidian pulse digest builder.

The actual MCP write happens in skills/pulse/SKILL.md (Claude-orchestrated).
What we test here is the pure markdown generator + filename helper.
"""
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subseek.lib import obsidian_sync, store  # noqa: E402


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def seed_surfaces(conn, n=3):
    """Insert N posts + surfaced rows."""
    conn.execute("INSERT INTO runs(started_at) VALUES(?)", (int(time.time()),))
    run_id = conn.execute("SELECT id FROM runs").fetchone()[0]
    now = int(time.time())
    for i in range(n):
        pid = f"p{i:03d}"
        conn.execute(
            "INSERT INTO posts(id, subreddit, title, url, canonical_url, author, "
            "created_utc, score, num_comments, body, first_seen_at, score_internal, removed) "
            "VALUES(?, ?, 'test', 'http://x/' || ?, 'http://reddit.com/' || ?, "
            "'op', ?, 5, 1, '', ?, 50, 0)",
            (pid, "sales" if i % 2 == 0 else "RevOps", pid, pid, now, now),
        )
        conn.execute(
            "INSERT INTO surfaced(post_id, surfaced_on, run_id, tier, state, surfaced_at) "
            "VALUES(?, '2026-05-25', ?, 2, 'hot', ?)",
            (pid, run_id, now - i * 3600),
        )


def test_digest_includes_frontmatter():
    conn = fresh_db()
    seed_surfaces(conn, n=3)
    digest = obsidian_sync.build_weekly_digest(conn)
    assert digest.startswith("---\n")
    assert "tags: [subseek, pulse, week-" in digest
    assert "total_surfaces: 3" in digest


def test_digest_has_sub_breakdown():
    conn = fresh_db()
    seed_surfaces(conn, n=3)
    digest = obsidian_sync.build_weekly_digest(conn)
    assert "r/sales" in digest
    assert "r/RevOps" in digest
    assert "| Subreddit | Surfaces |" in digest


def test_empty_db_doesnt_crash():
    conn = fresh_db()
    digest = obsidian_sync.build_weekly_digest(conn)
    assert "total_surfaces: 0" in digest
    assert "No surfaces this week" in digest


def test_filename_format():
    """Filename: YYYY-WNN-pulse.md"""
    fn = obsidian_sync.suggested_filename(now=dt.datetime(2026, 5, 25))
    assert fn.endswith("-pulse.md")
    assert fn.startswith("2026-W")


def test_old_surfaces_excluded_from_weekly():
    """Surfaces older than 7d don't count in 'total this week'."""
    conn = fresh_db()
    seed_surfaces(conn, n=2)  # within last 7d
    # Add an 8d-old surface
    conn.execute("INSERT INTO runs(started_at) VALUES(?)", (int(time.time()),))
    rid = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    now = int(time.time())
    conn.execute(
        "INSERT INTO posts(id, subreddit, title, url, canonical_url, author, "
        "created_utc, score, num_comments, body, first_seen_at, score_internal, removed) "
        "VALUES('old1', 'sales', 't', 'http://x/old1', 'http://reddit.com/old1', "
        "'op', ?, 5, 1, '', ?, 50, 0)", (now - 9*86400, now - 9*86400),
    )
    conn.execute(
        "INSERT INTO surfaced(post_id, surfaced_on, run_id, tier, state, surfaced_at) "
        "VALUES('old1', '2026-05-15', ?, 2, 'hot', ?)",
        (rid, now - 9*86400),
    )
    digest = obsidian_sync.build_weekly_digest(conn)
    assert "total_surfaces: 2" in digest  # not 3
