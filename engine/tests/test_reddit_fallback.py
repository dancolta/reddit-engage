"""SS-104: dual-host RSS 403 failover (www -> old.reddit), keyless.

Pins the failover precedence and the per-sub outcome-counter invariant:
  - 200 on a host returns immediately (later hosts not tried)
  - 403/5xx/network advances to the next host
  - 429 does NOT advance (shared per-IP bucket); it stops and is rate_limited
  - exactly ONE of ok/failed/rate_limited is counted per resilient call, so the
    ok + failed + rate_limited == subs-attempted invariant survives failover
Mocks the stat-free attempt seam (_fetch_xml_attempt); no network, no sleeps.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import reddit  # noqa: E402

_ATOM = (
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    '<entry><id>t3_x</id>'
    '<link href="https://www.reddit.com/r/s/comments/x/t/"/>'
    '<title>t</title><published>2026-01-01T00:00:00+00:00</published>'
    '<category term="s"/></entry></feed>'
)


def test_first_host_200_skips_second():
    reddit.reset_fetch_stats()
    root = ET.fromstring(_ATOM)
    calls: list[str] = []

    def fake(url, timeout=15):
        calls.append(url)
        return ("ok", root)

    with patch.object(reddit, "_fetch_xml_attempt", side_effect=fake):
        out = reddit.fetch_xml_resilient("/r/s/new/.rss")
    assert out is root
    assert len(calls) == 1                      # old.reddit never tried
    assert "www.reddit.com" in calls[0]
    s = reddit.get_fetch_stats()
    assert s["ok"] == 1 and s["fallback_used"] == 0


def test_fallback_www_403_old_200():
    reddit.reset_fetch_stats()
    root = ET.fromstring(_ATOM)

    def fake(url, timeout=15):
        return ("failed", None) if "www.reddit.com" in url else ("ok", root)

    with patch.object(reddit, "_fetch_xml_attempt", side_effect=fake):
        out = reddit.fetch_xml_resilient("/r/s/new/.rss")
    assert out is root
    s = reddit.get_fetch_stats()
    assert s["ok"] == 1 and s["failed"] == 0 and s["fallback_used"] == 1


def test_both_hosts_403_fails_once():
    reddit.reset_fetch_stats()
    with patch.object(reddit, "_fetch_xml_attempt",
                      side_effect=lambda url, timeout=15: ("failed", None)):
        out = reddit.fetch_xml_resilient("/r/s/new/.rss")
    assert out is None
    s = reddit.get_fetch_stats()
    assert s["failed"] == 1 and s["ok"] == 0 and s["rate_limited"] == 0


def test_429_does_not_advance_host():
    """The token bucket is per-IP and SHARED across hosts; a 429 on www must NOT
    burn a second request on old.reddit. It stops and reports rate_limited."""
    reddit.reset_fetch_stats()
    calls: list[str] = []

    def fake(url, timeout=15):
        calls.append(url)
        return ("rate_limited", None)

    with patch.object(reddit, "_fetch_xml_attempt", side_effect=fake):
        out = reddit.fetch_xml_resilient("/r/s/new/.rss")
    assert out is None
    assert len(calls) == 1                       # did NOT advance to old.reddit
    assert "www.reddit.com" in calls[0]
    s = reddit.get_fetch_stats()
    assert s["rate_limited"] == 1 and s["failed"] == 0 and s["ok"] == 0
    assert reddit.is_rate_limited() is True


def test_outcome_counter_invariant_with_failover():
    reddit.reset_fetch_stats()
    root = ET.fromstring(_ATOM)
    # /a: www ok ; /b: www 403 -> old ok ; /c: both fail
    plan = {
        "/a/": {"www": ("ok", root)},
        "/b/": {"www": ("failed", None), "old": ("ok", root)},
        "/c/": {"www": ("failed", None), "old": ("failed", None)},
    }

    def fake(url, timeout=15):
        host = "www" if "www.reddit.com" in url else "old"
        for path, m in plan.items():
            if path in url:
                return m[host]
        return ("failed", None)

    with patch.object(reddit, "_fetch_xml_attempt", side_effect=fake):
        reddit.fetch_xml_resilient("/r/a/new/.rss")
        reddit.fetch_xml_resilient("/r/b/new/.rss")
        reddit.fetch_xml_resilient("/r/c/new/.rss")
    s = reddit.get_fetch_stats()
    assert s["ok"] == 2 and s["failed"] == 1 and s["rate_limited"] == 0
    # exactly one outcome counted per resilient call (3 subs attempted)
    assert s["ok"] + s["failed"] + s["rate_limited"] == 3
    assert s["fallback_used"] == 1


def test_failover_hosts_are_keyless_no_auth_surface():
    # Strengthen the OAuth-removed invariant for the new failover surface.
    for h in reddit.RSS_HOSTS:
        assert "oauth" not in h
        assert "/api/v1" not in h
    assert reddit.RSS_HOSTS[0] == "www.reddit.com"
