"""Reddit OAuth fetcher via PRAW, with graceful fallback to the public JSON path.

This module exposes the same surface as `reddit_public.fetch_delta()` — drop-in
replacement — but uses authenticated PRAW when `oauth.json` is present in the
XDG config dir. Without OAuth, falls back to the existing public reader.

OAuth advantages:
  - 100 QPM vs the ~10 QPM rate-shaping of logged-out /new.json (10x headroom)
  - Identity scope unlocks /user/<me>/comments for Phase 5 postmortem
  - More stable: no Cloudflare anti-bot challenges on datacenter IPs

Why the fallback exists:
  - First-time users haven't registered a Reddit app yet
  - CI / unit tests should not require OAuth credentials
  - Lets `setup` work without OAuth on day 1; users can upgrade later

Config: ~/.config/subseek/oauth.json
{
  "client_id":     "<14-char string from reddit.com/prefs/apps>",
  "client_secret": "<secret from same app>",
  "username":      "<your reddit username>",
  "password":      null,                       // OPTIONAL, password-grant only
  "refresh_token": null,                       // OPTIONAL, refresh-grant
  "user_agent":    "subseek/0.1 by <your-username>"
}

If `password` is set we use password grant (script app). Else we use installed-app
flow with the refresh_token. Reddit recommends script-app for personal use.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from . import reddit_public, store


def _log(msg: str) -> None:
    sys.stderr.write(f"[reddit-oauth] {msg}\n")
    sys.stderr.flush()


# Reddit usernames are A-Za-z0-9_- with a 3-20 practical range. We accept up to
# 32 to be safe. Everything outside this pattern is rejected before URL building
# to defuse path-segment injection on the public reddit.com JSON endpoint.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


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


def oauth_config_path() -> Path:
    return store.xdg_config_dir() / "oauth.json"


def has_oauth() -> bool:
    """Return True if oauth.json is present AND has the required fields."""
    p = oauth_config_path()
    if not p.exists():
        return False
    try:
        cfg = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    required = {"client_id", "client_secret", "username"}
    return required.issubset(cfg.keys()) and all(cfg.get(k) for k in required)


def _load_oauth_config() -> dict[str, Any]:
    return json.loads(oauth_config_path().read_text())


def _build_praw_client():
    """Construct an authenticated praw.Reddit. PRAW is an optional dep
    (install via `pip install -e '.[reddit]'`); raises ImportError if missing."""
    try:
        import praw  # type: ignore
    except ImportError as e:
        raise ImportError(
            "PRAW not installed. Install with: pip install -e '.[reddit]'"
        ) from e

    cfg = _load_oauth_config()
    ua = cfg.get("user_agent") or f"subseek/0.1 by /u/{cfg['username']}"

    kwargs: dict[str, Any] = {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "user_agent": ua,
        "username": cfg["username"],
    }
    if cfg.get("password"):
        kwargs["password"] = cfg["password"]
    elif cfg.get("refresh_token"):
        kwargs["refresh_token"] = cfg["refresh_token"]
    # else: read-only mode — PRAW will accept this and auth as script app
    # for /r/<sub>/new which only needs the read scope.

    return praw.Reddit(**kwargs)


def _normalize_submission(s) -> dict[str, Any]:
    """Convert a PRAW Submission into our internal post shape (matches reddit_public.parse_post)."""
    canon = f"https://reddit.com/comments/{s.id}/"
    return {
        "id": s.id,
        "subreddit": str(s.subreddit.display_name),
        "title": s.title or "",
        "url": f"https://www.reddit.com{s.permalink}",
        "canonical_url": canon,
        "author": str(s.author) if s.author else "[deleted]",
        "created_utc": int(s.created_utc),
        "score": int(s.score or 0),
        "num_comments": int(s.num_comments or 0),
        "body": (s.selftext or "")[:1000],
        "upvote_ratio": getattr(s, "upvote_ratio", None),
        "removed": bool(getattr(s, "removed_by_category", None)) or s.selftext == "[removed]",
        "locked": bool(getattr(s, "locked", False)),
        "over_18": bool(getattr(s, "over_18", False)),
        "is_crosspost": bool(getattr(s, "crosspost_parent", None)),
    }


def fetch_delta_oauth(sub: str, last_seen_id: str | None, max_limit: int = 50) -> list[dict[str, Any]]:
    """OAuth path: walk r/<sub>/new via PRAW, stopping at last_seen_id.

    Returns posts newest-first, skipping removed/locked. Same contract as
    reddit_public.fetch_delta() so callers can be swap-agnostic.
    """
    client = _build_praw_client()
    sub_clean = sub.lstrip("r/").strip()
    collected: list[dict[str, Any]] = []
    for s in client.subreddit(sub_clean).new(limit=max_limit):
        post = _normalize_submission(s)
        if last_seen_id and post["id"] == last_seen_id:
            break
        if post["removed"] or post["locked"]:
            continue
        collected.append(post)
        if len(collected) >= max_limit:
            break
    return collected


def fetch_delta(sub: str, last_seen_id: str | None, max_limit: int = 50) -> list[dict[str, Any]]:
    """Hybrid entry point: prefer OAuth (if configured + PRAW installed),
    else fall back to the existing public JSON fetcher. Same return shape
    either way.

    Drop-in replacement for reddit_public.fetch_delta(). Existing call sites
    can `from .lib import reddit_oauth` and call `reddit_oauth.fetch_delta(...)`
    without other changes.
    """
    if has_oauth():
        try:
            return fetch_delta_oauth(sub, last_seen_id, max_limit=max_limit)
        except ImportError as e:
            _log(f"OAuth configured but PRAW missing → falling back to public JSON. ({e})")
        except Exception as e:
            # Don't crash the daily run on transient OAuth failures (token expiry,
            # 429, network blip). Degrade to the public path.
            _log(f"OAuth fetch failed → falling back to public JSON: {e}")
    return reddit_public.fetch_delta(sub, last_seen_id, max_limit=max_limit)


def fetch_user_about(username: str) -> dict[str, Any] | None:
    """Fetch a Redditor's public profile (karma + age + verified state).

    Uses OAuth if available (better rate budget); else falls back to the
    public /user/<u>/about.json endpoint. Used by author_vet.py.

    Returns None on 404 / suspended / private account.
    """
    if has_oauth():
        try:
            client = _build_praw_client()
            u = client.redditor(username)
            return {
                "name": str(u.name),
                "comment_karma": int(getattr(u, "comment_karma", 0) or 0),
                "link_karma": int(getattr(u, "link_karma", 0) or 0),
                "created_utc": int(getattr(u, "created_utc", 0) or 0),
                "is_employee": bool(getattr(u, "is_employee", False)),
                "verified": bool(getattr(u, "has_verified_email", False)),
            }
        except ImportError:
            pass  # fall through to public
        except Exception as e:
            _log(f"OAuth user fetch failed → falling back to public: {e}")

    # Public fallback. /user/<u>/about.json is unauth-readable.
    safe = _safe_username(username)
    if not safe:
        return None
    url = f"https://www.reddit.com/user/{safe}/about.json"
    data = reddit_public.fetch_json(url)
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

    Used by author_vet to detect "wrong audience" authors: e.g. >80% activity
    in r/Entrepreneur class subs = likely hustle-bro, not an operator.

    Returns {subreddit_name: count} or None on failure.
    """
    if has_oauth():
        try:
            client = _build_praw_client()
            counts: dict[str, int] = {}
            for c in client.redditor(username).comments.new(limit=limit):
                name = str(c.subreddit.display_name)
                counts[name] = counts.get(name, 0) + 1
            return counts
        except ImportError:
            pass
        except Exception as e:
            _log(f"OAuth user-comments fetch failed → falling back: {e}")

    safe = _safe_username(username)
    if not safe:
        return None
    url = f"https://www.reddit.com/user/{safe}/comments.json?limit={limit}"
    data = reddit_public.fetch_json(url)
    if not data:
        return None
    counts: dict[str, int] = {}
    for child in (data.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        sub = d.get("subreddit")
        if sub:
            counts[sub] = counts.get(sub, 0) + 1
    return counts
