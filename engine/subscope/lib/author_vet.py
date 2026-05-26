"""Author quality pre-gate.

Before a post is scored, we evaluate the OP's Reddit profile. Posts from
throwaway accounts, very young accounts, or accounts that mostly post in
'wrong audience' subs (r/Entrepreneur class — hustle-bros, not operators)
are dropped before they pollute the surface list.

Per reddit-community-builder agent research (Phase -1 stress test): this
single signal kills ~30% of wasted surfaces in real-world testing.

Cache: vetted_authors table caches profile snapshots for 7d so we don't
refetch the same OP across multiple posts in a single day.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from . import reddit, store


# Subs that signal "wrong audience" — hustle-bros, beginners, not real operators.
# Used to compute "wrong-audience density" in an OP's recent comment history.
WRONG_AUDIENCE_SUBS = {
    "entrepreneur", "smallbusiness", "startups", "indiehackers",
    "side_hustle", "wallstreetbets", "passiveincome", "antiwork",
    "personalfinance", "Frugal", "GetMotivated",
    "Entrepreneurialride", "EntrepreneurRideAlong",
    "FinancialPlanning", "millionaire", "millionairemakers",
}

# Account age + karma thresholds (configurable via weights.yml in future).
MIN_ACCOUNT_AGE_DAYS = 30
MIN_COMMENT_KARMA = 50
MAX_WRONG_AUDIENCE_FRACTION = 0.80  # >80% in wrong-audience subs = drop


CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS vetted_authors (
    username          TEXT PRIMARY KEY,
    fetched_at        INTEGER NOT NULL,
    comment_karma     INTEGER,
    link_karma        INTEGER,
    created_utc       INTEGER,
    sub_breakdown     TEXT,             -- JSON: {sub_name: count}
    verdict           TEXT NOT NULL,    -- 'pass' | 'fail'
    reason            TEXT              -- nullable, the fail reason
);
CREATE INDEX IF NOT EXISTS idx_vetted_authors_fetched ON vetted_authors(fetched_at);
"""


CACHE_TTL_SECONDS = 7 * 24 * 3600


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent migration. Called by vet_author() on first use."""
    conn.executescript(CACHE_SCHEMA)


def _now() -> int:
    return int(time.time())


def _wrong_audience_fraction(sub_breakdown: dict[str, int]) -> float:
    """Fraction of recent comments in wrong-audience subs."""
    total = sum(sub_breakdown.values()) or 1
    wrong = sum(
        count for sub, count in sub_breakdown.items()
        if sub.lower() in {s.lower() for s in WRONG_AUDIENCE_SUBS}
    )
    return wrong / total


def vet_author(
    username: str,
    conn: sqlite3.Connection | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Return verdict on an author.

    Returns:
      {
        "verdict": "pass" | "fail",
        "reason":  None | "<reason string>",
        "comment_karma": int,
        "account_age_days": int,
        "wrong_audience_fraction": float,
        "from_cache": bool,
      }

    Fail reasons (any one drops):
      - "deleted_or_private"     — Reddit returned no profile
      - "account_too_young"      — created < MIN_ACCOUNT_AGE_DAYS ago
      - "low_karma"              — comment_karma < MIN_COMMENT_KARMA
      - "wrong_audience"         — > MAX_WRONG_AUDIENCE_FRACTION in hustle-bro subs

    On Reddit API failure, returns `verdict="pass", reason="fetch_failed"`
    rather than dropping the post — degrade open, not closed.
    """
    now = now if now is not None else _now()
    username = username.lstrip("u/").strip()

    if username == "[deleted]":
        return _result("fail", "deleted_or_private", 0, 0, 0.0, False)

    # Cache lookup
    cached = _lookup_cache(conn, username, now) if conn else None
    if cached:
        return cached

    # Fresh fetch
    about = reddit.fetch_user_about(username)
    if not about:
        result = _result("pass", "fetch_failed", 0, 0, 0.0, False)
        _write_cache(conn, username, result, sub_breakdown={}, now=now)
        return result

    karma = int(about.get("comment_karma") or 0)
    created = int(about.get("created_utc") or 0)
    age_days = max(0, (now - created) // 86400) if created else 0

    if age_days < MIN_ACCOUNT_AGE_DAYS:
        result = _result("fail", "account_too_young", karma, age_days, 0.0, False)
        _write_cache(conn, username, result, sub_breakdown={}, now=now,
                     comment_karma=karma, created_utc=created)
        return result

    if karma < MIN_COMMENT_KARMA:
        result = _result("fail", "low_karma", karma, age_days, 0.0, False)
        _write_cache(conn, username, result, sub_breakdown={}, now=now,
                     comment_karma=karma, created_utc=created)
        return result

    # Last (most expensive) check: sub histogram
    sub_breakdown = reddit.fetch_user_recent_subs(username, limit=100) or {}
    wrong_frac = _wrong_audience_fraction(sub_breakdown)
    if wrong_frac > MAX_WRONG_AUDIENCE_FRACTION:
        result = _result("fail", "wrong_audience", karma, age_days, wrong_frac, False)
    else:
        result = _result("pass", None, karma, age_days, wrong_frac, False)

    _write_cache(conn, username, result, sub_breakdown=sub_breakdown, now=now,
                 comment_karma=karma, created_utc=created)
    return result


def _result(verdict: str, reason: str | None, karma: int, age_days: int,
            wrong_frac: float, from_cache: bool) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "reason": reason,
        "comment_karma": karma,
        "account_age_days": age_days,
        "wrong_audience_fraction": round(wrong_frac, 3),
        "from_cache": from_cache,
    }


def _lookup_cache(conn: sqlite3.Connection, username: str, now: int) -> dict[str, Any] | None:
    """Return cached verdict if fresh (< CACHE_TTL_SECONDS old), else None."""
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT fetched_at, comment_karma, created_utc, sub_breakdown, verdict, reason "
            "FROM vetted_authors WHERE username = ?",
            (username,),
        ).fetchone()
    except sqlite3.Error:
        return None

    if not row:
        return None
    if (now - int(row["fetched_at"])) > CACHE_TTL_SECONDS:
        return None

    sub_breakdown = json.loads(row["sub_breakdown"] or "{}")
    karma = int(row["comment_karma"] or 0)
    created = int(row["created_utc"] or 0)
    age_days = max(0, (now - created) // 86400) if created else 0
    wrong_frac = _wrong_audience_fraction(sub_breakdown)
    return _result(row["verdict"], row["reason"], karma, age_days, wrong_frac, True)


def _write_cache(conn: sqlite3.Connection | None, username: str, result: dict[str, Any],
                 sub_breakdown: dict[str, int] | None = None, now: int | None = None,
                 comment_karma: int | None = None, created_utc: int | None = None) -> None:
    if conn is None:
        return
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO vetted_authors(username, fetched_at, comment_karma, "
            "link_karma, created_utc, sub_breakdown, verdict, reason) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(username) DO UPDATE SET "
            "fetched_at=excluded.fetched_at, comment_karma=excluded.comment_karma, "
            "created_utc=excluded.created_utc, sub_breakdown=excluded.sub_breakdown, "
            "verdict=excluded.verdict, reason=excluded.reason",
            (
                username, now or _now(),
                comment_karma if comment_karma is not None else result.get("comment_karma", 0),
                None,
                created_utc,
                json.dumps(sub_breakdown or {}),
                result["verdict"],
                result.get("reason"),
            ),
        )
    except sqlite3.Error:
        # Cache write failure is non-fatal — vet still returns the verdict.
        pass
