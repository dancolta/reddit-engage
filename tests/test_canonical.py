"""Tests for URL canonicalization (stress-test outcome #3)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import reddit_public  # noqa: E402


def test_canonical_from_id():
    data = {"id": "abc123", "permalink": "/r/smallbusiness/comments/abc123/foo/"}
    assert reddit_public.canonical_url(data) == "https://reddit.com/comments/abc123/"


def test_canonical_from_t3_name():
    data = {"name": "t3_abc123", "permalink": "/r/smallbusiness/comments/abc123/foo/"}
    assert reddit_public.canonical_url(data) == "https://reddit.com/comments/abc123/"


def test_canonical_from_permalink_only():
    data = {"permalink": "/r/SaaS/comments/xyz789/title_slug/"}
    assert reddit_public.canonical_url(data) == "https://reddit.com/comments/xyz789/"


def test_canonical_strips_subreddit():
    """Two posts on different subs should never share canonical URL accidentally,
    but the same post id across host variants must produce the same canonical."""
    a = {"id": "ghi555", "permalink": "/r/smallbusiness/comments/ghi555/foo/"}
    b = {"id": "ghi555", "permalink": "/r/Entrepreneur/comments/ghi555/different_slug/"}
    # Same id = same canonical regardless of subreddit
    assert reddit_public.canonical_url(a) == reddit_public.canonical_url(b)


def test_canonical_empty_returns_empty():
    assert reddit_public.canonical_url({}) == ""
    assert reddit_public.canonical_url({"permalink": "/garbage"}) == ""


def test_parse_post_removed_detection():
    fixtures = {
        "kind": "t3",
        "data": {
            "id": "rmv001",
            "permalink": "/r/test/comments/rmv001/x/",
            "author": "[deleted]",
            "selftext": "[removed]",
            "subreddit": "test",
            "title": "x",
            "created_utc": 1700000000,
            "score": 0,
            "num_comments": 0,
        },
    }
    post = reddit_public.parse_post(fixtures)
    assert post is not None
    assert post["removed"] is True


def test_parse_post_skips_invalid():
    # kind != t3
    assert reddit_public.parse_post({"kind": "t1", "data": {}}) is None
    # no permalink
    assert reddit_public.parse_post({"kind": "t3", "data": {}}) is None
    # permalink lacks /comments/
    assert reddit_public.parse_post(
        {"kind": "t3", "data": {"permalink": "/r/x/about", "id": "abc"}}
    ) is None


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
