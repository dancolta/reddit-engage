"""Tests for the cooling queue + decay state machine."""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import store  # noqa: E402


def fresh_db():
    """In-memory DB with schema bootstrapped."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def seed_run_and_post(conn, post_id="abc01"):
    conn.execute("INSERT INTO runs(started_at) VALUES(?)", (int(time.time()),))
    run_id = conn.execute("SELECT id FROM runs").fetchone()[0]
    conn.execute(
        "INSERT INTO posts(id, subreddit, title, url, canonical_url, author, "
        "created_utc, score, num_comments, body, first_seen_at, score_internal, removed) "
        "VALUES(?, 'sales', 'test', 'http://x/' || ?, 'http://reddit.com/' || ?, "
        "'op', ?, 5, 1, '', ?, 50, 0)",
        (post_id, post_id, post_id, int(time.time()), int(time.time())),
    )
    return run_id


def test_default_state_is_drafting():
    conn = fresh_db()
    run_id = seed_run_and_post(conn, "p001")
    store.mark_surfaced(conn, "p001", run_id, tier=1)
    state = conn.execute("SELECT state FROM surfaced WHERE post_id='p001'").fetchone()[0]
    assert state == "drafting"


def test_explicit_hot_state_bypasses_cooling():
    """--no-cool path: mark_surfaced(state='hot') for time-sensitive patterns."""
    conn = fresh_db()
    run_id = seed_run_and_post(conn, "p002")
    store.mark_surfaced(conn, "p002", run_id, tier=1, state="hot")
    state = conn.execute("SELECT state FROM surfaced WHERE post_id='p002'").fetchone()[0]
    assert state == "hot"


def test_flush_promotes_only_mature_drafts():
    """flush_cooling_queue(N): rows older than N minutes go 'hot'."""
    conn = fresh_db()
    run_id = seed_run_and_post(conn, "young")
    seed_run_and_post(conn, "old")
    # Insert one fresh draft + one 60-min-old draft
    now = int(time.time())
    conn.execute(
        "INSERT INTO surfaced(post_id, surfaced_on, run_id, tier, state, surfaced_at) "
        "VALUES('young', '2026-05-25', ?, 1, 'drafting', ?)",
        (run_id, now - 60),  # 1 minute old
    )
    conn.execute(
        "INSERT INTO surfaced(post_id, surfaced_on, run_id, tier, state, surfaced_at) "
        "VALUES('old', '2026-05-25', ?, 1, 'drafting', ?)",
        (run_id, now - 3600),  # 60 min old
    )
    promoted = store.flush_cooling_queue(conn, cool_minutes=30)
    assert promoted == 1  # only `old` flushed
    states = {r["post_id"]: r["state"] for r in conn.execute("SELECT post_id, state FROM surfaced")}
    assert states["young"] == "drafting"
    assert states["old"] == "hot"


def test_hot_surfaces_returns_only_hot():
    conn = fresh_db()
    run_id = seed_run_and_post(conn, "drafting_one")
    seed_run_and_post(conn, "hot_one")
    seed_run_and_post(conn, "dead_one")
    now = int(time.time())
    conn.executemany(
        "INSERT INTO surfaced(post_id, surfaced_on, run_id, tier, state, surfaced_at) "
        "VALUES(?, '2026-05-25', ?, 1, ?, ?)",
        [
            ("drafting_one", run_id, "drafting", now),
            ("hot_one", run_id, "hot", now),
            ("dead_one", run_id, "dead", now - 30*86400),
        ],
    )
    hot = store.hot_surfaces(conn)
    assert len(hot) == 1
    assert hot[0]["post_id"] == "hot_one"


def test_decay_marks_old_hot_as_dead():
    conn = fresh_db()
    run_id = seed_run_and_post(conn, "fresh_hot")
    seed_run_and_post(conn, "old_hot")
    now = int(time.time())
    conn.executemany(
        "INSERT INTO surfaced(post_id, surfaced_on, run_id, tier, state, surfaced_at) "
        "VALUES(?, '2026-05-25', ?, 1, 'hot', ?)",
        [("fresh_hot", run_id, now - 86400), ("old_hot", run_id, now - 20*86400)],
    )
    decayed = store.decay_old_surfaces(conn, days=14)
    assert decayed == 1
    states = {r["post_id"]: r["state"] for r in conn.execute("SELECT post_id, state FROM surfaced")}
    assert states["fresh_hot"] == "hot"
    assert states["old_hot"] == "dead"


def test_migration_is_idempotent():
    """Running ensure on a DB that already has the columns must not fail."""
    conn = fresh_db()
    store._ensure_surfaced_state_column(conn)
    store._ensure_surfaced_state_column(conn)  # second call no-ops
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(surfaced)")}
    assert "state" in cols
    assert "surfaced_at" in cols


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
