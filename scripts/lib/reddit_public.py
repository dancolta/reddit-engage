"""Raw Reddit public JSON fetcher. No auth required.

Adapted from ~/.claude/skills/last30days/scripts/lib/reddit_public.py.
Changes for reddit-engage:
- Daily-delta cursor strategy (sort=new + last-seen post ID watermark)
- URL canonicalization to https://reddit.com/comments/<t3_id>/
- Removed enrichment / time-window logic
- 429 with Retry-After honored; exponential backoff
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()


USER_AGENT = "reddit-engage/0.1 (research tool, github.com/dancolta)"
MAX_RETRIES = 3
BASE_BACKOFF = 2.0


def log(msg: str) -> None:
    sys.stderr.write(f"[reddit] {msg}\n")
    sys.stderr.flush()


def canonical_url(reddit_post_data: dict[str, Any]) -> str:
    """Canonicalize a Reddit post URL to https://reddit.com/comments/<t3_id>/.

    Post IDs are globally unique on Reddit; the subreddit slug is unnecessary
    for the canonical form. Strips host variants (old., np., www., m.), query
    strings, and trailing slashes.
    """
    raw_id = str(reddit_post_data.get("id") or reddit_post_data.get("name") or "").strip()
    raw_id = re.sub(r"^t3_", "", raw_id)
    if not raw_id:
        permalink = str(reddit_post_data.get("permalink") or "")
        m = re.search(r"/comments/([a-z0-9]+)", permalink, re.I)
        if not m:
            return ""
        raw_id = m.group(1)
    return f"https://reddit.com/comments/{raw_id}/"


def fetch_json(url: str, timeout: int = 15) -> dict[str, Any] | None:
    """Fetch JSON with retry on 429 and content-type validation."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "json" not in content_type and "text/html" in content_type:
                    log(f"anti-bot HTML response (Content-Type: {content_type})")
                    return None
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = None
                if hasattr(e, "headers"):
                    retry_after = e.headers.get("Retry-After")
                delay = BASE_BACKOFF * (2 ** attempt)
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        pass
                log(f"429 rate-limited, retry {attempt + 1}/{MAX_RETRIES} after {delay:.1f}s")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)
                    continue
                log("429 retries exhausted")
                return None
            elif e.code in (403, 404):
                log(f"HTTP {e.code}: {url}")
                return None
            else:
                log(f"HTTP {e.code}: {e.reason}")
                return None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log(f"network error: {e}")
            return None
        except json.JSONDecodeError as e:
            log(f"JSON decode error: {e}")
            return None
    return None


def parse_post(child: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a Reddit listing child into our post shape. Returns None on bad data."""
    if child.get("kind") != "t3":
        return None
    data = child.get("data", {})
    permalink = str(data.get("permalink", "")).strip()
    if not permalink or "/comments/" not in permalink:
        return None

    canon = canonical_url(data)
    if not canon:
        return None

    post_id = re.sub(r"^t3_", "", str(data.get("id", ""))).strip()
    if not post_id:
        return None

    selftext = str(data.get("selftext") or "")
    author = str(data.get("author") or "[deleted]")
    removed = bool(data.get("removed_by_category") or data.get("removed") or
                   author == "[deleted]" or selftext == "[removed]")

    return {
        "id": post_id,
        "subreddit": str(data.get("subreddit", "")).strip(),
        "title": str(data.get("title", "")).strip(),
        "url": f"https://www.reddit.com{permalink}",
        "canonical_url": canon,
        "author": author,
        "created_utc": int(data.get("created_utc") or 0),
        "score": int(data.get("score") or 0),
        "num_comments": int(data.get("num_comments") or 0),
        "body": selftext[:1000],
        "upvote_ratio": data.get("upvote_ratio"),
        "removed": removed,
        "locked": bool(data.get("locked")),
    }


def fetch_subreddit_new(sub: str, limit: int = 25, after: str | None = None,
                        timeout: int = 15) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch /r/<sub>/new.json with optional `after` cursor.

    Returns (posts, next_cursor). next_cursor is the Reddit 'after' token
    suitable for paging if we need more. For daily-delta we typically don't.
    """
    encoded = urllib.parse.quote(sub.lstrip("r/").strip())
    qs = f"limit={limit}&raw_json=1"
    if after:
        qs += f"&after={urllib.parse.quote(after)}"
    url = f"https://www.reddit.com/r/{encoded}/new.json?{qs}"

    data = fetch_json(url, timeout=timeout)
    if not data:
        return [], None

    children = data.get("data", {}).get("children", [])
    posts: list[dict[str, Any]] = []
    for child in children:
        p = parse_post(child)
        if p:
            posts.append(p)

    next_cursor = data.get("data", {}).get("after")
    return posts, next_cursor


def fetch_delta(sub: str, last_seen_id: str | None,
                max_limit: int = 50) -> list[dict[str, Any]]:
    """Fetch posts newer than last_seen_id from /r/<sub>/new.

    Hybrid cursor: walk pages until we hit last_seen_id or exhaust max_limit.
    Returns posts in newest-first order. Skips removed/locked posts.
    """
    collected: list[dict[str, Any]] = []
    after: str | None = None
    while len(collected) < max_limit:
        page_limit = min(25, max_limit - len(collected))
        posts, after = fetch_subreddit_new(sub, limit=page_limit, after=after)
        if not posts:
            break
        for p in posts:
            if last_seen_id and p["id"] == last_seen_id:
                return collected
            if p["removed"] or p["locked"]:
                continue
            collected.append(p)
        if not after:
            break
        # Be polite between paginated calls
        time.sleep(0.5)
    return collected


def fetch_top_comments(canonical_url_str: str, limit: int = 10,
                       timeout: int = 10) -> list[dict[str, Any]]:
    """Fetch top comments for saturation modifier (high-saturation Tier 2 subs).

    Returns up to `limit` top-level comments sorted by score.
    Used by score.py to check "is there an existing technical reply > 3 upvotes?".
    """
    m = re.search(r"/comments/([a-z0-9]+)", canonical_url_str, re.I)
    if not m:
        return []
    pid = m.group(1)
    url = f"https://www.reddit.com/comments/{pid}.json?limit={limit}&sort=top&raw_json=1"
    data = fetch_json(url, timeout=timeout)
    if not data or not isinstance(data, list) or len(data) < 2:
        return []

    listing = data[1].get("data", {}).get("children", [])
    comments: list[dict[str, Any]] = []
    for child in listing:
        if child.get("kind") != "t1":
            continue
        cd = child.get("data", {})
        comments.append({
            "score": int(cd.get("score") or 0),
            "body": str(cd.get("body") or "")[:500],
            "author": str(cd.get("author") or "[deleted]"),
        })
    comments.sort(key=lambda c: c["score"], reverse=True)
    return comments[:limit]
