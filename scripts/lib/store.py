"""SQLite store. Schema bootstrap + queries.

Single source of truth for dedup (surfaced.post_id PK = post is shown at most once across all time).
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id                TEXT PRIMARY KEY,
    subreddit         TEXT NOT NULL,
    title             TEXT NOT NULL,
    url               TEXT NOT NULL UNIQUE,
    canonical_url     TEXT NOT NULL UNIQUE,
    author            TEXT NOT NULL,
    created_utc       INTEGER NOT NULL,
    score             INTEGER NOT NULL DEFAULT 0,
    num_comments      INTEGER NOT NULL DEFAULT 0,
    body              TEXT,
    first_seen_at     INTEGER NOT NULL,
    score_internal    REAL NOT NULL DEFAULT 0.0,
    removed           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_posts_sub_created ON posts(subreddit, created_utc DESC);
CREATE INDEX IF NOT EXISTS idx_posts_score ON posts(score_internal DESC);

CREATE TABLE IF NOT EXISTS subreddits (
    name              TEXT PRIMARY KEY,
    tier              INTEGER NOT NULL,
    bucket            TEXT NOT NULL,
    saturation        TEXT,
    weight            REAL NOT NULL DEFAULT 1.0,
    last_cursor       TEXT,
    last_run_at       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_subreddits_tier ON subreddits(tier);

CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        INTEGER NOT NULL,
    finished_at       INTEGER,
    posts_fetched     INTEGER NOT NULL DEFAULT 0,
    posts_surfaced    INTEGER NOT NULL DEFAULT 0,
    notes             TEXT
);

CREATE TABLE IF NOT EXISTS blog_posts (
    url               TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    pain              TEXT NOT NULL,
    saas_replaced     TEXT NOT NULL,
    persona           TEXT NOT NULL,
    stack             TEXT NOT NULL,
    keywords          TEXT NOT NULL,
    last_refreshed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS post_blog_refs (
    post_id           TEXT NOT NULL,
    blog_url          TEXT NOT NULL,
    match_score       REAL NOT NULL,
    matched_keywords  TEXT,
    PRIMARY KEY (post_id, blog_url),
    FOREIGN KEY (post_id) REFERENCES posts(id),
    FOREIGN KEY (blog_url) REFERENCES blog_posts(url)
);
CREATE INDEX IF NOT EXISTS idx_post_blog_refs_post ON post_blog_refs(post_id);

CREATE TABLE IF NOT EXISTS surfaced (
    post_id           TEXT PRIMARY KEY,
    surfaced_on       TEXT NOT NULL,
    run_id            INTEGER NOT NULL,
    tier              INTEGER NOT NULL,
    notion_page_id    TEXT,
    ai_citation_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (post_id) REFERENCES posts(id),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_surfaced_date ON surfaced(surfaced_on);

CREATE TABLE IF NOT EXISTS meta (
    key               TEXT PRIMARY KEY,
    value             TEXT NOT NULL,
    updated_at        INTEGER NOT NULL
);
"""


def db_path(project_root: Path | str | None = None) -> Path:
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    return root / "db" / "reddit-engage.sqlite"


@contextmanager
def connect(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def bootstrap(path: Path | str | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def upsert_subreddit(conn: sqlite3.Connection, sub: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO subreddits(name, tier, bucket, saturation, weight)
           VALUES(?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
               tier=excluded.tier, bucket=excluded.bucket,
               saturation=excluded.saturation, weight=excluded.weight""",
        (sub["name"], sub["tier"], sub["bucket"],
         sub.get("saturation"), sub.get("weight", 1.0)),
    )


def upsert_blog_post(conn: sqlite3.Connection, blog: dict[str, Any]) -> None:
    kw = "|".join(blog.get("keywords", []))
    conn.execute(
        """INSERT INTO blog_posts(url, title, pain, saas_replaced, persona, stack, keywords, last_refreshed_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET
               title=excluded.title, pain=excluded.pain, saas_replaced=excluded.saas_replaced,
               persona=excluded.persona, stack=excluded.stack, keywords=excluded.keywords,
               last_refreshed_at=excluded.last_refreshed_at""",
        (blog["url"], blog["title"], blog["pain"], blog["saas_replaced"],
         blog["persona"], blog["stack"], kw, int(time.time())),
    )


def already_surfaced(conn: sqlite3.Connection, post_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM surfaced WHERE post_id = ?", (post_id,)).fetchone()
    return row is not None


def insert_post(conn: sqlite3.Connection, post: dict[str, Any]) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO posts
           (id, subreddit, title, url, canonical_url, author, created_utc,
            score, num_comments, body, first_seen_at, score_internal, removed)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (post["id"], post["subreddit"], post["title"], post["url"],
         post["canonical_url"], post["author"], post["created_utc"],
         post["score"], post["num_comments"], post.get("body", ""),
         int(time.time()), post.get("score_internal", 0.0),
         1 if post.get("removed") else 0),
    )


def update_score(conn: sqlite3.Connection, post_id: str, score_internal: float) -> None:
    conn.execute("UPDATE posts SET score_internal = ? WHERE id = ?", (score_internal, post_id))


def record_blog_ref(conn: sqlite3.Connection, post_id: str, blog_url: str,
                    match_score: float, matched_keywords: list[str]) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO post_blog_refs(post_id, blog_url, match_score, matched_keywords)
           VALUES(?, ?, ?, ?)""",
        (post_id, blog_url, match_score, "|".join(matched_keywords)),
    )


def mark_surfaced(conn: sqlite3.Connection, post_id: str, run_id: int, tier: int,
                  notion_page_id: str | None = None) -> None:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    conn.execute(
        """INSERT INTO surfaced(post_id, surfaced_on, run_id, tier, notion_page_id)
           VALUES(?, ?, ?, ?, ?)""",
        (post_id, today, run_id, tier, notion_page_id),
    )


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO runs(started_at) VALUES(?)", (int(time.time()),)
    )
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int,
               posts_fetched: int, posts_surfaced: int, notes: str = "") -> None:
    conn.execute(
        """UPDATE runs SET finished_at = ?, posts_fetched = ?, posts_surfaced = ?, notes = ?
           WHERE id = ?""",
        (int(time.time()), posts_fetched, posts_surfaced, notes, run_id),
    )


def update_cursor(conn: sqlite3.Connection, sub_name: str, cursor: str) -> None:
    conn.execute(
        "UPDATE subreddits SET last_cursor = ?, last_run_at = ? WHERE name = ?",
        (cursor, int(time.time()), sub_name),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO meta(key, value, updated_at) VALUES(?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, value, int(time.time())),
    )


def fetch_blog_posts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM blog_posts").fetchall()
    return [dict(r) for r in rows]


def get_sub(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM subreddits WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def stats_last_run(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else {}


def prune_old_posts(conn: sqlite3.Connection, days: int = 90) -> int:
    cutoff = int(time.time()) - days * 86400
    cur = conn.execute(
        "DELETE FROM posts WHERE first_seen_at < ? AND id NOT IN (SELECT post_id FROM surfaced)",
        (cutoff,),
    )
    return cur.rowcount
