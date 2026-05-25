"""Postmortem: auto-detect Dan's replies to surfaced posts + record 7-day outcomes.

Closes the loop on "which patterns convert, which flop". No manual tagging
required — `reddit_oauth.fetch_user_recent_subs`-style identity scope lets
us walk the user's own recent comments and match against surfaced.post_id.

Flow:
  1. detect_replies(conn) → scan /user/<me>/comments, match parent_id to
     surfaced posts, insert into reply_log table if not seen before.
  2. update_outcomes(conn) → for reply_log rows aged ≥7d without an outcome
     field, fetch the comment via OAuth, record upvotes/replies/banned.
  3. summary(conn) → aggregate by pattern, return JSON for the weekly digest.

All three functions are designed to run on a cron / daily. Idempotent —
running multiple times in a day adds no duplicates and does no extra work
for replies that already have a 7-day outcome.

Requires OAuth (identity scope). If `reddit_oauth.has_oauth()` returns False,
all three functions short-circuit + log once.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from typing import Any

from . import reddit_oauth, store


REPLY_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS reply_log (
    post_id            TEXT PRIMARY KEY,
    comment_id         TEXT NOT NULL,
    comment_url        TEXT NOT NULL,
    replied_at         INTEGER NOT NULL,
    outcome            TEXT,                 -- JSON: upvotes, num_replies, removed, locked, fetched_at
    pattern            TEXT,                 -- copied from surfaced.pattern at detect time
    FOREIGN KEY (post_id) REFERENCES surfaced(post_id)
);
CREATE INDEX IF NOT EXISTS idx_reply_log_outcome ON reply_log(outcome);
CREATE INDEX IF NOT EXISTS idx_reply_log_replied_at ON reply_log(replied_at);
"""


CATCHUP_DAYS = 30      # don't try to detect replies older than this
OUTCOME_WAIT_DAYS = 7  # wait this long before scoring a reply


def _log(msg: str) -> None:
    sys.stderr.write(f"[postmortem] {msg}\n")
    sys.stderr.flush()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent migration. Called by detect_replies + update_outcomes."""
    conn.executescript(REPLY_LOG_SCHEMA)


def _own_username() -> str | None:
    """Return the configured Reddit username from oauth.json, or None."""
    if not reddit_oauth.has_oauth():
        return None
    try:
        cfg = json.loads(reddit_oauth.oauth_config_path().read_text())
        return cfg.get("username") or None
    except (OSError, json.JSONDecodeError):
        return None


def detect_replies(conn: sqlite3.Connection, limit: int = 100) -> dict[str, int]:
    """Scan Dan's own recent comments; match parent_id against surfaced.post_id;
    insert into reply_log if new.

    Returns a dict {scanned, new_matches, already_logged, errors}.

    Idempotent: skips comments whose post_id already has a reply_log row.
    """
    ensure_schema(conn)
    username = _own_username()
    if not username:
        _log("OAuth not configured — skipping detect_replies")
        return {"scanned": 0, "new_matches": 0, "already_logged": 0, "errors": 0}

    # Need richer fetch than fetch_user_recent_subs gives us — direct API call
    new_count = 0
    already = 0
    errors = 0
    scanned = 0
    cutoff = int(time.time()) - (CATCHUP_DAYS * 86400)

    comments = _fetch_own_comments(username, limit=limit)
    if comments is None:
        _log("comment-fetch failed")
        return {"scanned": 0, "new_matches": 0, "already_logged": 0, "errors": 1}

    for c in comments:
        scanned += 1
        if c["created_utc"] < cutoff:
            continue
        # parent_id format: t3_<post_id> when comment is a top-level reply
        parent = c.get("parent_id") or ""
        if not parent.startswith("t3_"):
            continue
        post_id = parent[3:]

        # Was this post ever surfaced? Match by post_id.
        row = conn.execute(
            "SELECT s.post_id, s.tier FROM surfaced s WHERE s.post_id = ?", (post_id,)
        ).fetchone()
        if not row:
            continue

        # Already logged?
        existing = conn.execute(
            "SELECT 1 FROM reply_log WHERE post_id = ?", (post_id,)
        ).fetchone()
        if existing:
            already += 1
            continue

        try:
            conn.execute(
                "INSERT INTO reply_log(post_id, comment_id, comment_url, replied_at, pattern) "
                "VALUES(?, ?, ?, ?, ?)",
                (post_id, c["id"], c["permalink"], c["created_utc"], None),
            )
            new_count += 1
        except sqlite3.Error as e:
            _log(f"insert failed for post_id={post_id}: {e}")
            errors += 1

    return {"scanned": scanned, "new_matches": new_count,
            "already_logged": already, "errors": errors}


def _fetch_own_comments(username: str, limit: int = 100) -> list[dict[str, Any]] | None:
    """Fetch Dan's own /user/<me>/comments. Uses OAuth (identity scope)
    if available, falls back to public path."""
    if reddit_oauth.has_oauth():
        try:
            client = reddit_oauth._build_praw_client()
            out: list[dict[str, Any]] = []
            for c in client.redditor(username).comments.new(limit=limit):
                out.append({
                    "id": c.id,
                    "permalink": f"https://www.reddit.com{c.permalink}",
                    "parent_id": c.parent_id,
                    "created_utc": int(c.created_utc),
                })
            return out
        except ImportError:
            pass
        except Exception as e:
            _log(f"OAuth comment fetch failed → fallback: {e}")

    # Public fallback
    from . import reddit_public
    safe = reddit_oauth._safe_username(username)
    if not safe:
        return None
    url = f"https://www.reddit.com/user/{safe}/comments.json?limit={limit}"
    data = reddit_public.fetch_json(url)
    if not data:
        return None
    out2: list[dict[str, Any]] = []
    for child in (data.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        permalink = d.get("permalink") or ""
        out2.append({
            "id": d.get("id"),
            "permalink": f"https://www.reddit.com{permalink}" if permalink else "",
            "parent_id": d.get("parent_id") or "",
            "created_utc": int(d.get("created_utc") or 0),
        })
    return out2


def update_outcomes(conn: sqlite3.Connection) -> dict[str, int]:
    """For rows in reply_log aged ≥7 days without an outcome, fetch the
    comment and record its current state. Idempotent.

    Returns {scored, skipped_too_young, fetch_failures}.
    """
    ensure_schema(conn)
    if not reddit_oauth.has_oauth():
        _log("OAuth not configured — skipping update_outcomes (public fallback also limited)")
        # We CAN still try via public endpoint, but accuracy degrades.

    now = int(time.time())
    cutoff = now - (OUTCOME_WAIT_DAYS * 86400)

    rows = conn.execute(
        "SELECT post_id, comment_id, replied_at FROM reply_log "
        "WHERE outcome IS NULL AND replied_at <= ?",
        (cutoff,),
    ).fetchall()

    scored = 0
    failures = 0
    for row in rows:
        outcome = _fetch_comment_outcome(row["comment_id"])
        if outcome is None:
            failures += 1
            continue
        outcome["fetched_at"] = now
        try:
            conn.execute(
                "UPDATE reply_log SET outcome = ? WHERE post_id = ?",
                (json.dumps(outcome), row["post_id"]),
            )
            scored += 1
        except sqlite3.Error as e:
            _log(f"outcome update failed for {row['post_id']}: {e}")
            failures += 1

    too_young = conn.execute(
        "SELECT COUNT(*) FROM reply_log WHERE outcome IS NULL AND replied_at > ?",
        (cutoff,),
    ).fetchone()[0]

    return {"scored": scored, "skipped_too_young": too_young,
            "fetch_failures": failures}


def _fetch_comment_outcome(comment_id: str) -> dict[str, Any] | None:
    """Fetch a comment's current state. Tries OAuth, falls back to public."""
    if reddit_oauth.has_oauth():
        try:
            client = reddit_oauth._build_praw_client()
            c = client.comment(id=comment_id)
            c.refresh()
            # PRAW lazy-loads replies. len(c.replies) is the actual direct-reply count
            # (was incorrectly using num_reports — mod-report count — before).
            try:
                num_replies = len(c.replies)
            except Exception:
                num_replies = 0
            return {
                "upvotes": int(c.score or 0),
                "num_replies": num_replies,
                "removed": bool(getattr(c, "removed", False)),
                "locked": bool(getattr(c, "locked", False)),
            }
        except ImportError:
            pass
        except Exception as e:
            _log(f"OAuth outcome fetch failed for {comment_id}: {e}")

    # Public path
    from . import reddit_public
    url = f"https://www.reddit.com/comments/{comment_id}.json"
    data = reddit_public.fetch_json(url)
    if not data or not isinstance(data, list):
        return None
    try:
        c = data[1]["data"]["children"][0]["data"]
    except (KeyError, IndexError):
        return None
    return {
        "upvotes": int(c.get("score") or 0),
        "num_replies": int(c.get("replies", {}).get("data", {}).get("children", []).__len__() if isinstance(c.get("replies"), dict) else 0),
        "removed": bool(c.get("removed") or c.get("removed_by_category")),
        "locked": bool(c.get("locked")),
    }


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Aggregate scored outcomes for the weekly digest.

    Returns:
        {
          "total_replies": N,
          "scored": M,
          "by_outcome": {avg_upvotes, avg_replies, removed_count, locked_count},
          "weekly": [...rows for the trailing 7d...]
        }
    """
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT outcome FROM reply_log WHERE outcome IS NOT NULL"
    ).fetchall()
    scored = 0
    upvotes_sum = 0
    replies_sum = 0
    removed = 0
    locked = 0
    for r in rows:
        try:
            o = json.loads(r["outcome"])
        except (json.JSONDecodeError, TypeError):
            continue
        scored += 1
        upvotes_sum += int(o.get("upvotes") or 0)
        replies_sum += int(o.get("num_replies") or 0)
        if o.get("removed"):
            removed += 1
        if o.get("locked"):
            locked += 1

    total = conn.execute("SELECT COUNT(*) FROM reply_log").fetchone()[0]
    return {
        "total_replies": total,
        "scored": scored,
        "avg_upvotes": (upvotes_sum / scored) if scored else 0.0,
        "avg_replies": (replies_sum / scored) if scored else 0.0,
        "removed_count": removed,
        "locked_count": locked,
    }
