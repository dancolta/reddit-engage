"""Tests for the reddit module's RSS/Atom path.

OAuth + PRAW were removed in v0.2 (see plan: OAuth removal) and stay removed.
As of 2026-05-29 Reddit's anonymous `.json` surface 403s, so the module reads
`.rss` feeds instead. Tests below cover the Atom parser, the fetch_delta entry
point, and the user-fetch paths (about is dead -> None; recent-subs rebuilt
from the comments RSS <category> tags).
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import reddit  # noqa: E402


# ─── Atom fixtures ────────────────────────────────────────────────────

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
<category term="SaaS" label="r/SaaS"/>
<title>newest submissions : SaaS</title>
<entry>
  <author><name>/u/No_Big1248</name><uri>https://www.reddit.com/user/No_Big1248</uri></author>
  <category term="SaaS" label="r/SaaS"/>
  <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class=&quot;md&quot;&gt;&lt;p&gt;HubSpot is too expensive, any alternative to it?&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; &amp;#32; submitted by &amp;#32; &lt;a href=&quot;https://www.reddit.com/user/No_Big1248&quot;&gt; /u/No_Big1248 &lt;/a&gt; &lt;br/&gt; &lt;span&gt;&lt;a href=&quot;https://www.reddit.com/r/SaaS/comments/1tqxd2g/x/&quot;&gt;[link]&lt;/a&gt;&lt;/span&gt;</content>
  <id>t3_1tqxd2g</id>
  <link href="https://www.reddit.com/r/SaaS/comments/1tqxd2g/x/" />
  <updated>2026-05-29T10:14:46+00:00</updated>
  <published>2026-05-29T10:14:46+00:00</published>
  <title>I hit a wall with HubSpot pricing</title>
</entry>
</feed>"""


def _first_entry(feed_xml: str) -> ET.Element:
    root = ET.fromstring(feed_xml)
    return root.find("{http://www.w3.org/2005/Atom}entry")


# ─── parse_atom_entry (STORY-1 / STORY-5) ─────────────────────────────

def test_parse_atom_entry_extracts_id():
    post = reddit.parse_atom_entry(_first_entry(ATOM_FEED))
    assert post is not None
    assert post["id"] == "1tqxd2g"  # t3_ stripped
    assert post["canonical_url"] == "https://reddit.com/comments/1tqxd2g/"


def test_parse_atom_entry_extracts_author():
    post = reddit.parse_atom_entry(_first_entry(ATOM_FEED))
    assert post["author"] == "No_Big1248"  # /u/ prefix stripped


def test_parse_atom_entry_extracts_subreddit_and_title():
    post = reddit.parse_atom_entry(_first_entry(ATOM_FEED))
    assert post["subreddit"] == "SaaS"
    assert post["title"] == "I hit a wall with HubSpot pricing"
    assert post["url"] == "https://www.reddit.com/r/SaaS/comments/1tqxd2g/x/"


def test_parse_atom_entry_parses_timestamp_to_epoch():
    post = reddit.parse_atom_entry(_first_entry(ATOM_FEED))
    # 2026-05-29T10:14:46+00:00 -> epoch (tz-aware, UTC)
    assert post["created_utc"] == 1780049686
    assert isinstance(post["created_utc"], int)


def test_parse_atom_entry_cleans_body():
    post = reddit.parse_atom_entry(_first_entry(ATOM_FEED))
    body = post["body"]
    assert "HubSpot is too expensive" in body
    # Chrome stripped: no HTML comments, no "submitted by" footer, no [link]
    assert "SC_OFF" not in body
    assert "submitted by" not in body.lower()
    assert "[link]" not in body
    assert "<" not in body  # tags stripped


def test_parse_atom_entry_caps_body_at_1000():
    long_text = "x " * 2000
    feed = ATOM_FEED.replace(
        "HubSpot is too expensive, any alternative to it?", long_text
    )
    post = reddit.parse_atom_entry(_first_entry(feed))
    assert len(post["body"]) <= 1000


def test_parse_atom_entry_defaults_missing_engagement_fields():
    """RSS carries no score/comments/upvote_ratio/locked. Defaults must hold."""
    post = reddit.parse_atom_entry(_first_entry(ATOM_FEED))
    assert post["score"] == 0
    assert post["num_comments"] == 0
    assert post["upvote_ratio"] is None
    assert post["locked"] is False
    assert post["removed"] is False
    assert post["over_18"] is False
    assert post["is_crosspost"] is False


def test_parse_atom_entry_rejects_entry_without_comments_link():
    """An entry whose link is not a /comments/ permalink is dropped."""
    feed = ATOM_FEED.replace(
        '<link href="https://www.reddit.com/r/SaaS/comments/1tqxd2g/x/" />',
        '<link href="https://www.reddit.com/r/SaaS/" />',
    )
    assert reddit.parse_atom_entry(_first_entry(feed)) is None


def test_parse_atom_entry_handles_z_suffix_timestamp():
    feed = ATOM_FEED.replace("2026-05-29T10:14:46+00:00", "2026-05-29T10:14:46Z")
    post = reddit.parse_atom_entry(_first_entry(feed))
    assert post["created_utc"] == 1780049686


def test_parse_atom_entry_shape_matches_parse_post_keys():
    """Contract guard: Atom output dict must have the exact same keys parse_post
    produces, so downstream (scorer, output, store) is untouched."""
    json_child = {
        "kind": "t3",
        "data": {
            "id": "abc123", "permalink": "/r/x/comments/abc123/y/",
            "subreddit": "x", "title": "t", "author": "a",
            "created_utc": 1700000000, "score": 5, "num_comments": 2,
            "selftext": "body",
        },
    }
    json_post = reddit.parse_post(json_child)
    atom_post = reddit.parse_atom_entry(_first_entry(ATOM_FEED))
    assert set(atom_post.keys()) == set(json_post.keys())


# ─── fetch_subreddit_new / fetch_delta (RSS) ──────────────────────────

def test_fetch_subreddit_new_parses_feed(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    root = ET.fromstring(ATOM_FEED)
    with patch.object(reddit, "fetch_xml", return_value=root):
        posts = reddit.fetch_subreddit_new("SaaS", limit=25)
    assert len(posts) == 1
    assert posts[0]["id"] == "1tqxd2g"


def test_fetch_subreddit_new_returns_empty_on_fetch_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    with patch.object(reddit, "fetch_xml", return_value=None):
        assert reddit.fetch_subreddit_new("SaaS") == []


def test_fetch_delta_routes_to_public(tmp_path, monkeypatch):
    """fetch_delta must call _fetch_delta_public verbatim. No fallback paths,
    no OAuth path (OAuth-removed invariant)."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    sentinel = [{"id": "abc", "title": "fixture"}]
    with patch.object(reddit, "_fetch_delta_public", return_value=sentinel) as mock_public:
        result = reddit.fetch_delta("sales", None, max_limit=10)
    mock_public.assert_called_once_with("sales", None, max_limit=10)
    assert result == sentinel


def test_fetch_delta_stops_at_last_seen(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    root = ET.fromstring(ATOM_FEED)
    with patch.object(reddit, "fetch_xml", return_value=root):
        # last_seen == the only post id -> nothing newer
        out = reddit.fetch_delta("SaaS", "1tqxd2g", max_limit=25)
    assert out == []


# ─── fetch_user_about: dead surface, fail-open contract (STORY-2) ──────

def test_fetch_user_about_returns_none():
    """about.json 403s for anonymous requests; this always returns None so
    author_vet fails open. OAuth (which would restore karma/age) stays removed."""
    assert reddit.fetch_user_about("any_user") is None


def test_fetch_user_about_returns_none_for_unsafe_username():
    """Username guard still fires before any work."""
    assert reddit.fetch_user_about("../../etc/passwd") is None


# ─── fetch_user_recent_subs: rebuilt from comments RSS <category> ──────

USER_COMMENTS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>comments by u</title>
<entry><author><name>/u/u</name></author>
  <category term="sales" label="r/sales" /><id>t1_a</id>
  <link href="https://www.reddit.com/r/sales/comments/x/a/"/>
  <title>/u/u on x</title></entry>
<entry><author><name>/u/u</name></author>
  <category term="sales" label="r/sales" /><id>t1_b</id>
  <link href="https://www.reddit.com/r/sales/comments/y/b/"/>
  <title>/u/u on y</title></entry>
<entry><author><name>/u/u</name></author>
  <category term="ops" label="r/ops" /><id>t1_c</id>
  <link href="https://www.reddit.com/r/ops/comments/z/c/"/>
  <title>/u/u on z</title></entry>
</feed>"""


def test_fetch_user_recent_subs_returns_none_on_fetch_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    with patch.object(reddit, "fetch_xml", return_value=None):
        assert reddit.fetch_user_recent_subs("nonexistent") is None


def test_fetch_user_recent_subs_builds_histogram(tmp_path, monkeypatch):
    """Aggregates comment subs from RSS <category term> into a {sub: count} dict."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    root = ET.fromstring(USER_COMMENTS_RSS)
    with patch.object(reddit, "fetch_xml", return_value=root):
        out = reddit.fetch_user_recent_subs("u")
    assert out == {"sales": 2, "ops": 1}


def test_unsafe_username_rejected(tmp_path, monkeypatch):
    """Path-injection guard fires before any HTTP, on both user-fetch paths."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    called = []
    with patch.object(reddit, "fetch_xml",
                      side_effect=lambda *a, **k: called.append(1)):
        with patch.object(reddit, "fetch_json",
                          side_effect=lambda *a, **k: called.append(1)):
            assert reddit.fetch_user_about("../../etc/passwd") is None
            assert reddit.fetch_user_recent_subs("u/../foo") is None
    assert called == []


# ─── Fetch reachability stats (STORY-4 blocked-vs-empty signal) ───────

def test_reset_fetch_stats_zeroes_counters():
    reddit._FETCH_STATS["ok"] = 5
    reddit._FETCH_STATS["failed"] = 3
    reddit.reset_fetch_stats()
    assert reddit.get_fetch_stats() == {"ok": 0, "failed": 0}


def test_fetch_xml_records_ok_on_success(tmp_path, monkeypatch):
    """A reachable feed increments `ok`, so a zero-surface run reads as a
    genuinely empty day, not a block."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    reddit.reset_fetch_stats()

    class _Resp:
        def read(self):
            return ATOM_FEED.encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with patch.object(reddit.urllib.request, "urlopen", return_value=_Resp()):
        root = reddit.fetch_xml("https://www.reddit.com/r/SaaS/new/.rss")
    assert root is not None
    assert reddit.get_fetch_stats() == {"ok": 1, "failed": 0}


def test_fetch_xml_records_failed_on_403(tmp_path, monkeypatch):
    """A 403 (edge block) increments `failed`, which the CLI maps to status
    'blocked' when no feed was reachable."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    reddit.reset_fetch_stats()
    err = reddit.urllib.error.HTTPError(
        "https://www.reddit.com/r/SaaS/new/.rss", 403, "Blocked", {}, None
    )
    with patch.object(reddit.urllib.request, "urlopen", side_effect=err):
        root = reddit.fetch_xml("https://www.reddit.com/r/SaaS/new/.rss")
    assert root is None
    assert reddit.get_fetch_stats() == {"ok": 0, "failed": 1}


# ─── OAuth-removed invariant (must stay green) ────────────────────────

def test_no_oauth_surface():
    """The module must expose no OAuth/PRAW/token machinery. Positioning is
    'Free, no API keys'; OAuth was removed in v0.2 and stays removed."""
    assert not hasattr(reddit, "get_oauth_token")
    assert not hasattr(reddit, "fetch_oauth")
    assert not hasattr(reddit, "_oauth_session")
    source = Path(reddit.__file__).read_text()
    lowered = source.lower()
    assert "oauth.reddit.com" not in lowered
    assert "praw" not in lowered
    assert "client_secret" not in lowered


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
