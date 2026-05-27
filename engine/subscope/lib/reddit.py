"""Reddit fetcher: public-JSON only.

Public surface (what callers use):
  - fetch_delta(sub, last_seen_id, max_limit)   : daily-delta scan
  - fetch_user_about(username)                  : OP profile vetting
  - fetch_user_recent_subs(username, limit)     : OP audience-fit histogram
  - canonical_url(post_data)                    : URL normalization
  - parse_post(child)                           : normalize a listing entry
  - fetch_json(url)                             : raw public GET with retry
  - _safe_username(username)                    : path-injection guard

Reddit's logged-out /new.json supports ~30-60 QPM, sufficient for the manual
`/subscope-run` pattern (a few subs per run, once or twice a day). OAuth was
removed in v0.2 because Reddit's account-creation captcha was blocking too
many users from ever reaching the value path; the postmortem reply-tracking
feature that needed OAuth went with it.
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


# ─── Constants ────────────────────────────────────────────────────────

USER_AGENT = "subscope/0.1 (research tool, github.com/dancolta)"
MAX_RETRIES = 3
BASE_BACKOFF = 2.0

# Reddit usernames are A-Za-z0-9_- with a 3-20 practical range. We accept up to
# 32 to be safe. Anything outside this pattern is rejected before URL building
# to defuse path-segment injection on reddit.com JSON endpoints.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _log(msg: str) -> None:
    sys.stderr.write(f"[reddit] {msg}\n")
    sys.stderr.flush()


# ─── Username safety ──────────────────────────────────────────────────

def _safe_username(username: str | None) -> str | None:
    """Return a username safe for URL path interpolation, or None if invalid.

    Strips a leading 'u/' or '/u/' if present. Returns None for empty input,
    None for input that fails the username regex (rejects hostile input like
    'x/about.json?dummy=', '../etc/passwd', etc.).
    """
    if not username:
        return None
    cleaned = username.lstrip("/").removeprefix("u/")
    return cleaned if _USERNAME_RE.match(cleaned) else None


# ─── URL canonicalization ─────────────────────────────────────────────

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


# ─── Public JSON fetcher ──

def fetch_json(url: str, timeout: int = 15) -> dict[str, Any] | None:
    """Fetch JSON with retry on 429 and content-type validation."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "json" not in content_type and "text/html" in content_type:
                    _log(f"anti-bot HTML response (Content-Type: {content_type})")
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
                _log(f"429 rate-limited, retry {attempt + 1}/{MAX_RETRIES} after {delay:.1f}s")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)
                    continue
                _log("429 retries exhausted")
                return None
            elif e.code in (403, 404):
                _log(f"HTTP {e.code}: {url}")
                return None
            else:
                _log(f"HTTP {e.code}: {e.reason}")
                return None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            _log(f"network error: {e}")
            return None
        except json.JSONDecodeError as e:
            _log(f"JSON decode error: {e}")
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

    # NSFW: Reddit flags posts via over_18 (post-level) and the host subreddit
    # may also be NSFW. Either one is sufficient to reject.
    over_18 = bool(data.get("over_18") or data.get("thumbnail") == "nsfw")

    # Crosspost detection: posts with crosspost_parent_list are reposts from
    # other subs. Even if the host sub is SFW, the original may not be.
    crosspost_parent = data.get("crosspost_parent_list") or []
    is_crosspost = bool(crosspost_parent)
    if is_crosspost:
        parent = crosspost_parent[0] if isinstance(crosspost_parent, list) and crosspost_parent else {}
        if parent.get("over_18"):
            over_18 = True

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
        "over_18": over_18,
        "is_crosspost": is_crosspost,
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


def _fetch_delta_public(sub: str, last_seen_id: str | None,
                        max_limit: int = 50) -> list[dict[str, Any]]:
    """Public-JSON path for fetch_delta. Walks pages until last_seen_id or
    max_limit. Skips removed/locked. Returns newest-first."""
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
        time.sleep(0.5)  # be polite between paginated calls
    return collected


# ─── Public API ──────────────────────────────────────────────────────

def fetch_delta(sub: str, last_seen_id: str | None,
                max_limit: int = 50) -> list[dict[str, Any]]:
    """Daily-delta scan: posts newer than last_seen_id from /r/<sub>/new."""
    return _fetch_delta_public(sub, last_seen_id, max_limit=max_limit)


def fetch_user_about(username: str) -> dict[str, Any] | None:
    """Fetch a Redditor's public profile (karma + age + verified state).

    Used by author_vet.py. Returns None on 404 / suspended / private account.
    """
    safe = _safe_username(username)
    if not safe:
        return None
    url = f"https://www.reddit.com/user/{safe}/about.json"
    data = fetch_json(url)
    if not data:
        return None
    d = data.get("data") or {}
    return {
        "name": d.get("name"),
        "comment_karma": int(d.get("comment_karma") or 0),
        "link_karma": int(d.get("link_karma") or 0),
        "created_utc": int(d.get("created_utc") or 0),
        "is_employee": bool(d.get("is_employee")),
        "verified": bool(d.get("has_verified_email")),
    }


def fetch_user_recent_subs(username: str, limit: int = 100) -> dict[str, int] | None:
    """Histogram of which subs a user posts/comments in (recent N items).

    Used by author_vet to detect "wrong audience" authors (e.g. >80% activity
    in hustle-bro subs). Returns {subreddit_name: count} or None on failure.
    """
    safe = _safe_username(username)
    if not safe:
        return None
    url = f"https://www.reddit.com/user/{safe}/comments.json?limit={limit}"
    data = fetch_json(url)
    if not data:
        return None
    counts: dict[str, int] = {}
    for child in (data.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        sub = d.get("subreddit")
        if sub:
            counts[sub] = counts.get(sub, 0) + 1
    return counts
