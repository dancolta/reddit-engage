"""Reddit fetcher: RSS/Atom only (keyless, accountless).

Public surface (what callers use):
  - fetch_delta(sub, last_seen_id, max_limit)   : daily-delta scan
  - fetch_user_about(username)                  : OP profile vetting (now None)
  - fetch_user_recent_subs(username, limit)     : OP audience-fit histogram
  - canonical_url(post_data)                    : URL normalization
  - parse_post(child)                           : normalize a JSON listing entry
  - parse_atom_entry(entry)                     : normalize an Atom <entry>
  - fetch_json(url)                             : raw public GET with retry
  - fetch_xml(url)                              : raw RSS/Atom GET with retry
  - _safe_username(username)                    : path-injection guard

Why RSS, not JSON: as of 2026-05-29 Reddit's edge (Fastly/Varnish) returns an
instant `403 Blocked` (Retry-After: 0) for every unauthenticated `.json`
endpoint, www and old reddit alike, regardless of User-Agent. The machine IP is
fine (HTML + RSS both return 200). The RSS/Atom surface
(`/r/<sub>/new/.rss`, `/user/<x>/comments/.rss`) still returns 200 with no
credentials, so the fetcher reads those instead.

OAuth was removed in v0.2 and stays removed. The product positions on
"Free, no API keys"; reintroducing OAuth is explicitly out of scope.

RSS does NOT carry score, num_comments, upvote_ratio, or locked state. Those
fields default (score=0, num_comments=0, upvote_ratio=None, locked=False) and
the scorer degrades gracefully (see score.py). `/user/<x>/about.json` (karma +
age) is also 403, so fetch_user_about returns None and author_vet fails open.
"""
from __future__ import annotations

import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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

# Atom namespace used by Reddit RSS feeds.
_ATOM_NS = "{http://www.w3.org/2005/Atom}"

# Reddit usernames are A-Za-z0-9_- with a 3-20 practical range. We accept up to
# 32 to be safe. Anything outside this pattern is rejected before URL building
# to defuse path-segment injection on reddit.com endpoints.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _log(msg: str) -> None:
    sys.stderr.write(f"[reddit] {msg}\n")
    sys.stderr.flush()


# ─── Fetch reachability stats ─────────────────────────────────────────
# Lets a caller (cli.fetch_score) tell "the edge blocked us" apart from "the
# feeds were reachable but had nothing new". `ok` counts feed GETs that returned
# parseable XML; `failed` counts GETs that 403'd / errored. Reset per run.

_FETCH_STATS = {"ok": 0, "failed": 0}


def reset_fetch_stats() -> None:
    """Zero the per-run feed reachability counters. Call before a fetch batch."""
    _FETCH_STATS["ok"] = 0
    _FETCH_STATS["failed"] = 0


def get_fetch_stats() -> dict[str, int]:
    """Return a copy of the feed reachability counters for the current batch."""
    return dict(_FETCH_STATS)


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


# ─── Raw fetchers (JSON kept for parser-contract tests, XML is the live path) ──

def fetch_json(url: str, timeout: int = 15) -> dict[str, Any] | None:
    """Fetch JSON with retry on 429 and content-type validation.

    Reddit's anonymous JSON surface 403s as of 2026-05-29, so this is no longer
    on the live path. Retained for callers/tests that still exercise the JSON
    parse contract; fetch_xml is the path used by fetch_delta.
    """
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
                delay = _retry_after_delay(e, attempt)
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


def fetch_xml(url: str, timeout: int = 15) -> ET.Element | None:
    """Fetch an RSS/Atom feed and return its parsed root Element, or None.

    Retries on 429 with backoff (honoring Retry-After), returns None on
    403/404/network/parse errors. This is the live fetch primitive: Reddit's
    `.rss` feeds return 200 with no credentials where `.json` now 403s.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml",
    }
    req = urllib.request.Request(url, headers=headers)

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
                body = resp.read().decode("utf-8")
                root = ET.fromstring(body)
                _FETCH_STATS["ok"] += 1
                return root
        except urllib.error.HTTPError as e:
            if e.code == 429:
                delay = _retry_after_delay(e, attempt)
                _log(f"429 rate-limited, retry {attempt + 1}/{MAX_RETRIES} after {delay:.1f}s")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)
                    continue
                _log("429 retries exhausted")
                _FETCH_STATS["failed"] += 1
                return None
            elif e.code in (403, 404):
                _log(f"HTTP {e.code}: {url}")
                _FETCH_STATS["failed"] += 1
                return None
            else:
                _log(f"HTTP {e.code}: {e.reason}")
                _FETCH_STATS["failed"] += 1
                return None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            _log(f"network error: {e}")
            _FETCH_STATS["failed"] += 1
            return None
        except ET.ParseError as e:
            _log(f"XML parse error: {e}")
            _FETCH_STATS["failed"] += 1
            return None
    return None


def _retry_after_delay(err: urllib.error.HTTPError, attempt: int) -> float:
    """Compute the backoff delay for a 429, honoring Retry-After when present."""
    delay = BASE_BACKOFF * (2 ** attempt)
    retry_after = None
    if hasattr(err, "headers"):
        retry_after = err.headers.get("Retry-After")
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            pass
    return delay


# ─── JSON listing parser (kept for the parse contract + canonical tests) ──

def parse_post(child: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a Reddit JSON listing child into our post shape.

    Returns None on bad data. RSS is the live source now (see parse_atom_entry),
    but this stays as the canonical contract for the post dict shape and is
    still exercised by the canonical-URL test suite.
    """
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


# ─── Atom entry parser (the live path) ────────────────────────────────

def _atom_text(entry: ET.Element, tag: str) -> str:
    """Return stripped text of the first <tag> child in the Atom namespace, or ''."""
    el = entry.find(f"{_ATOM_NS}{tag}")
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _parse_iso8601_to_epoch(ts: str) -> int:
    """Parse an ISO8601 timestamp (e.g. '2026-05-29T10:14:46+00:00') to epoch int.

    Returns 0 on empty/unparseable input. Handles a trailing 'Z' (UTC) which
    older Python's fromisoformat rejects.
    """
    if not ts:
        return 0
    cleaned = ts.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(cleaned).timestamp())
    except (ValueError, OverflowError):
        return 0


def _clean_atom_body(raw_html: str) -> str:
    """Strip Reddit's RSS content chrome and return a plain-text body, capped 1000.

    Reddit wraps post bodies in `<!-- SC_OFF -->...<!-- SC_ON -->` and appends a
    'submitted by /u/x [link] [comments]' footer. We HTML-unescape, drop the
    footer, strip tags to text, and cap to 1000 chars to match parse_post.
    """
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    # Drop Reddit's content markers and the trailing "submitted by ... [link]
    # [comments]" chrome. After html.unescape the &#32; separators are spaces,
    # so match the literal "submitted by" through end-of-string.
    text = re.sub(r"<!--\s*SC_O(FF|N)\s*-->", "", text)
    text = re.sub(r"submitted by\b.*$", "", text, flags=re.S | re.I)
    # Strip remaining HTML tags to plain text, collapse whitespace.
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)  # second pass for entities revealed after tag strip
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1000]


def parse_atom_entry(entry: ET.Element) -> dict[str, Any] | None:
    """Normalize a Reddit Atom <entry> into the same dict shape as parse_post.

    Returns None on bad data (missing id, missing permalink). RSS does not carry
    engagement metrics, so score/num_comments default to 0, upvote_ratio to None,
    and locked/removed to False (the feed lists live posts only).

    Output keys (contract, identical to parse_post): id, subreddit, title, url,
    canonical_url, author, created_utc, score, num_comments, body, upvote_ratio,
    removed, locked, over_18, is_crosspost.
    """
    # Permalink: the <link href=...> of the entry.
    permalink = ""
    for link in entry.findall(f"{_ATOM_NS}link"):
        href = link.get("href")
        if href:
            permalink = href.strip()
            break
    if not permalink or "/comments/" not in permalink:
        return None

    # Post id: <id>t3_xxxx</id>, falling back to the permalink.
    raw_id = _atom_text(entry, "id")
    post_id = re.sub(r"^t3_", "", raw_id).strip()
    if not post_id:
        m = re.search(r"/comments/([a-z0-9]+)", permalink, re.I)
        if not m:
            return None
        post_id = m.group(1)
    # Guard: an <id> from a comment feed is t1_ (a comment), not a post. Only
    # keep ids that resolve from the t3 namespace or the post permalink.
    if not re.fullmatch(r"[A-Za-z0-9]+", post_id):
        return None

    canon = canonical_url({"id": post_id, "permalink": permalink})
    if not canon:
        return None

    # Subreddit: <category term="SaaS"> on the entry.
    subreddit = ""
    cat = entry.find(f"{_ATOM_NS}category")
    if cat is not None:
        subreddit = (cat.get("term") or "").strip()

    # Author: <author><name>/u/Name</name></author>.
    author = "[deleted]"
    author_el = entry.find(f"{_ATOM_NS}author/{_ATOM_NS}name")
    if author_el is not None and author_el.text:
        author = author_el.text.strip().lstrip("/").removeprefix("u/") or "[deleted]"

    title = _atom_text(entry, "title")
    published = _atom_text(entry, "published") or _atom_text(entry, "updated")
    created_utc = _parse_iso8601_to_epoch(published)

    content_el = entry.find(f"{_ATOM_NS}content")
    body = _clean_atom_body(content_el.text if content_el is not None else "")

    return {
        "id": post_id,
        "subreddit": subreddit,
        "title": title,
        "url": permalink,
        "canonical_url": canon,
        "author": author,
        "created_utc": created_utc,
        "score": 0,
        "num_comments": 0,
        "body": body,
        "upvote_ratio": None,
        "removed": False,
        "locked": False,
        "over_18": False,
        "is_crosspost": False,
    }


def fetch_subreddit_new(sub: str, limit: int = 25,
                        timeout: int = 15) -> list[dict[str, Any]]:
    """Fetch /r/<sub>/new/.rss and return normalized posts (newest-first).

    The Atom feed is a single page of the most recent ~25 items with no cursor,
    so there is no pagination contract. Returns [] on any fetch/parse failure.
    """
    encoded = urllib.parse.quote(sub.lstrip("r/").strip())
    url = f"https://www.reddit.com/r/{encoded}/new/.rss?limit={int(limit)}"

    root = fetch_xml(url, timeout=timeout)
    if root is None:
        return []

    posts: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        p = parse_atom_entry(entry)
        if p:
            posts.append(p)
    return posts


def _fetch_delta_public(sub: str, last_seen_id: str | None,
                        max_limit: int = 50) -> list[dict[str, Any]]:
    """RSS path for fetch_delta. The Atom feed is a single newest-first page,
    so we fetch once, stop at last_seen_id, skip removed/locked, and cap at
    max_limit. Returns newest-first."""
    posts = fetch_subreddit_new(sub, limit=min(max_limit, 100))
    collected: list[dict[str, Any]] = []
    for p in posts:
        if last_seen_id and p["id"] == last_seen_id:
            break
        if p["removed"] or p["locked"]:
            continue
        collected.append(p)
        if len(collected) >= max_limit:
            break
    return collected


# ─── Public API ──────────────────────────────────────────────────────

def fetch_delta(sub: str, last_seen_id: str | None,
                max_limit: int = 50) -> list[dict[str, Any]]:
    """Daily-delta scan: posts newer than last_seen_id from /r/<sub>/new/.rss."""
    return _fetch_delta_public(sub, last_seen_id, max_limit=max_limit)


def fetch_user_about(username: str) -> dict[str, Any] | None:
    """Fetch a Redditor's public profile (karma + age).

    `/user/<x>/about.json` returns 403 for anonymous requests as of 2026-05-29,
    and the RSS surface carries no karma/age data, so this always returns None.
    Callers (author_vet) MUST treat None as "unknown" and fail open, never
    rejecting an OP for missing karma/age. The username guard is kept so the
    contract (reject hostile usernames before any network call) still holds.
    """
    if not _safe_username(username):
        return None
    # Karma/age are no longer obtainable without OAuth, which stays removed.
    return None


def fetch_user_recent_subs(username: str, limit: int = 100) -> dict[str, int] | None:
    """Histogram of which subs a user recently commented in (recent N items).

    Rebuilt from `/user/<x>/comments/.rss`: each <entry> carries a
    <category term="<sub>"> tag naming the subreddit of the comment. Used by
    author_vet to detect "wrong audience" authors (e.g. >80% activity in
    hustle-bro subs). Returns {subreddit_name: count} or None on failure.
    """
    safe = _safe_username(username)
    if not safe:
        return None
    url = f"https://www.reddit.com/user/{safe}/comments/.rss?limit={int(limit)}"
    root = fetch_xml(url)
    if root is None:
        return None
    counts: dict[str, int] = {}
    for entry in root.findall(f"{_ATOM_NS}entry"):
        cat = entry.find(f"{_ATOM_NS}category")
        if cat is None:
            continue
        sub = (cat.get("term") or "").strip()
        if sub:
            counts[sub] = counts.get(sub, 0) + 1
    return counts
