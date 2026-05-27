"""Tests for ENR-3: pipeline integration (augment_scores + warmup_for_onboarding)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import enrich, store  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path / "cfg"))
    monkeypatch.setenv("SUBSCOPE_DATA", str(tmp_path / "data"))
    enrich.reset_cache()
    enrich.set_disabled(False)
    monkeypatch.delenv("SUBSCOPE_NO_ENRICH", raising=False)


def write_dfs_yaml():
    (store.xdg_config_dir() / "dataforseo.yml").write_text(
        "login: u\npassword: p\n"
    )


def write_fc_yaml():
    (store.xdg_config_dir() / "firecrawl.yml").write_text("api_key: fc-x\n")


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def _make_candidate(post_id="p1", body="Looking for an Apollo alternative."):
    return {
        "post": {"id": post_id, "body": body, "title": "test", "score_internal": 50.0},
        "sub": {"name": "sales", "tier": 1},
        "blog_matches": [],
    }


# ─── augment_scores: no-op paths ─────────────────────────────────────────

def test_augment_noop_when_no_providers(monkeypatch):
    conn = fresh_db()
    cand = _make_candidate(body="See https://g2.com/compare")
    enrich.augment_scores([cand], conn)
    assert "enrichment" not in cand


def test_augment_noop_when_disabled(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    # Pre-seed FC cache so we'd otherwise attach
    payload = {"url": "https://g2.com/compare", "title": "G2", "markdown": "compare page"}
    key = enrich.cache_key("scrape", "https://g2.com/compare")
    store.enrich_put(conn, "firecrawl", "scrape", key,
                     json.dumps(payload), ttl_seconds=3600)

    enrich.set_disabled(True)
    cand = _make_candidate(body="See https://g2.com/compare")
    enrich.augment_scores([cand], conn)
    assert "enrichment" not in cand


def test_augment_noop_when_post_has_no_link():
    write_fc_yaml()
    conn = fresh_db()
    cand = _make_candidate(body="No links in this body")
    enrich.augment_scores([cand], conn)
    assert "enrichment" not in cand


# ─── augment_scores: positive attachment ─────────────────────────────────

def test_augment_attaches_link_context_from_cache():
    write_fc_yaml()
    conn = fresh_db()
    payload = {
        "url": "https://g2.com/compare",
        "title": "G2 Compare",
        "markdown": "Apollo vs Outreach: a feature matrix...",
    }
    key = enrich.cache_key("scrape", "https://g2.com/compare")
    store.enrich_put(conn, "firecrawl", "scrape", key,
                     json.dumps(payload), ttl_seconds=3600)

    cand = _make_candidate(body="Looking at https://g2.com/compare for sales tools")
    enrich.augment_scores([cand], conn)
    assert "enrichment" in cand
    assert cand["enrichment"]["link_context"]["title"] == "G2 Compare"
    assert "Apollo" in cand["enrichment"]["link_context"]["excerpt"]


def test_augment_skips_expired_cache_row():
    write_fc_yaml()
    conn = fresh_db()
    payload = {"url": "https://x.com", "title": "T", "markdown": "M"}
    key = enrich.cache_key("scrape", "https://x.com")
    store.enrich_put(conn, "firecrawl", "scrape", key,
                     json.dumps(payload), ttl_seconds=-1)  # already expired

    cand = _make_candidate(body="Visit https://x.com")
    enrich.augment_scores([cand], conn)
    assert "enrichment" not in cand


def test_augment_skips_negative_cache_row():
    write_fc_yaml()
    conn = fresh_db()
    key = enrich.cache_key("scrape", "https://x.com")
    store.enrich_put(conn, "firecrawl", "scrape", key,
                     "{}", ttl_seconds=3600, error="http_402")
    cand = _make_candidate(body="Visit https://x.com")
    enrich.augment_scores([cand], conn)
    assert "enrichment" not in cand


def test_augment_never_calls_http(monkeypatch):
    """Phase B's hard rule: no network calls inside augment_scores."""
    write_fc_yaml()
    conn = fresh_db()
    called = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: called.append(1) or (200, b""))

    cand = _make_candidate(body="Some link https://example.com here")
    enrich.augment_scores([cand], conn)
    assert called == []


# ─── warmup_for_onboarding ───────────────────────────────────────────────

def test_warmup_skips_when_no_creds():
    conn = fresh_db()
    result = enrich.warmup_for_onboarding("https://acme.com", conn)
    assert result["dataforseo"]["called"] is False
    assert result["dataforseo"]["skipped_reason"] == "no_credentials"
    assert result["firecrawl"]["called"] is False
    assert result["firecrawl"]["skipped_reason"] == "no_credentials"


def test_warmup_calls_dfs_when_dfs_only(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()
    resp = {
        "status_code": 20000,
        "tasks": [{
            "status_code": 20000,
            "result": [{"items": [{"domain": "rival1.com"},
                                  {"domain": "rival2.com"}]}],
        }],
    }
    calls = []

    def fake_req(method, url, headers, body, timeout):
        calls.append(url)
        return 200, json.dumps(resp).encode()

    monkeypatch.setattr(enrich, "_client_request", fake_req)
    result = enrich.warmup_for_onboarding("https://acme.com/pricing", conn)
    assert result["dataforseo"]["called"] is True
    assert result["dataforseo"]["competitors_found"] == 2
    assert result["firecrawl"]["called"] is False
    # Domain extracted correctly (no scheme, no path)
    assert any("dataforseo_labs" in u for u in calls)


def test_warmup_extracts_domain_from_url():
    """Pure logic test: domain normalization for DFS call."""
    # Indirect test via warmup output — confirm www. stripped + path stripped
    write_dfs_yaml()
    conn = fresh_db()
    cache_keys_seen = []

    def fake_req(method, url, headers, body, timeout):
        # Body is JSON list with target
        decoded = json.loads(body.decode())
        cache_keys_seen.append(decoded[0]["target"])
        return 200, json.dumps({
            "status_code": 20000,
            "tasks": [{"status_code": 20000, "result": [{"items": []}]}],
        }).encode()

    import pytest as _pt
    with _pt.MonkeyPatch.context() as m:
        m.setattr(enrich, "_client_request", fake_req)
        enrich.warmup_for_onboarding("https://www.Acme.com/path/to/page", conn)
    assert cache_keys_seen == ["acme.com"]


def test_warmup_calls_both_when_both_creds(monkeypatch):
    write_dfs_yaml()
    write_fc_yaml()
    conn = fresh_db()

    def fake_req(method, url, headers, body, timeout):
        if "dataforseo" in url:
            return 200, json.dumps({
                "status_code": 20000,
                "tasks": [{"status_code": 20000,
                           "result": [{"items": [{"domain": "x.com"}]}]}],
            }).encode()
        if "firecrawl" in url:
            return 200, json.dumps({
                "success": True,
                "data": {"markdown": "# Acme\n\nbody",
                         "metadata": {"title": "Acme"}},
            }).encode()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(enrich, "_client_request", fake_req)
    result = enrich.warmup_for_onboarding("https://acme.com", conn)
    assert result["dataforseo"]["called"] is True
    assert result["firecrawl"]["called"] is True
    assert result["firecrawl"]["markdown_chars"] > 0


def test_warmup_disabled_via_env(monkeypatch):
    write_dfs_yaml()
    write_fc_yaml()
    monkeypatch.setenv("SUBSCOPE_NO_ENRICH", "1")
    conn = fresh_db()
    result = enrich.warmup_for_onboarding("https://acme.com", conn)
    assert result["dataforseo"]["called"] is False
    assert result["dataforseo"]["skipped_reason"] == "enrichment_disabled"


def test_warmup_handles_dfs_failure_gracefully(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (500, b"down"))
    result = enrich.warmup_for_onboarding("https://acme.com", conn)
    assert result["dataforseo"]["called"] is True
    assert result["dataforseo"]["skipped_reason"] == "fetch_failed_or_cached_negative"


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
