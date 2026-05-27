"""Tests for FC-1: Firecrawl scrape client inside enrich.py."""
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


def write_fc_yaml():
    (store.xdg_config_dir() / "firecrawl.yml").write_text(
        "api_key: fc-test-key-abc123\n"
    )


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def _fc_success(markdown="# Title\n\nBody text.", title="Example Title"):
    return {
        "success": True,
        "data": {
            "markdown": markdown,
            "metadata": {"title": title},
        },
    }


# ─── No config → None, zero HTTP ─────────────────────────────────────────

def test_no_config_returns_none(monkeypatch):
    conn = fresh_db()
    called = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: called.append(1) or (200, b""))
    assert enrich.fc_scrape("https://example.com", conn) is None
    assert called == []


# ─── SSRF guard on user-pasted scrape target ─────────────────────────────

def test_ssrf_target_rejected_before_any_request(monkeypatch, capsys):
    """A user-pasted private IP must never leave _client_request scope."""
    write_fc_yaml()
    conn = fresh_db()
    called = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: called.append(1) or (200, b""))
    got = enrich.fc_scrape("https://10.0.0.1/admin", conn)
    assert got is None
    assert called == []
    err = capsys.readouterr().err
    assert "SSRF" in err or "private" in err


def test_http_non_local_scrape_target_rejected(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    called = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: called.append(1) or (200, b""))
    got = enrich.fc_scrape("http://example.com/page", conn)
    assert got is None
    assert called == []


# ─── Fresh hit caches markdown ───────────────────────────────────────────

def test_fresh_hit_caches_markdown(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    resp = _fc_success(markdown="# Acme\n\nWe sell widgets.",
                       title="Acme Co.")
    calls = []

    def fake_req(method, url, headers, body, timeout):
        calls.append({"url": url, "auth": headers.get("Authorization")})
        return 200, json.dumps(resp).encode()

    monkeypatch.setattr(enrich, "_client_request", fake_req)
    got = enrich.fc_scrape("https://acme.com/about", conn)
    assert got is not None
    assert got["url"] == "https://acme.com/about"
    assert got["title"] == "Acme Co."
    assert "Acme" in got["markdown"]
    assert len(calls) == 1
    assert calls[0]["auth"] == "Bearer fc-test-key-abc123"


# ─── Markdown truncated past 1500 chars ──────────────────────────────────

def test_markdown_truncated_to_1500_chars(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    huge = "x" * 5000
    resp = _fc_success(markdown=huge)
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (200, json.dumps(resp).encode()))
    got = enrich.fc_scrape("https://example.com", conn)
    assert len(got["markdown"]) == 1500


# ─── Cache hit skips HTTP ────────────────────────────────────────────────

def test_cache_hit_skips_request(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    cached = {"url": "https://example.com", "title": "T", "markdown": "M"}
    key = enrich.cache_key("scrape", "https://example.com")
    store.enrich_put(conn, "firecrawl", "scrape", key,
                     json.dumps(cached), ttl_seconds=3600)

    called = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: called.append(1) or (200, b""))
    got = enrich.fc_scrape("https://example.com", conn)
    assert got == cached
    assert called == []


# ─── 402 quota-exhausted (Firecrawl's payment-required signal) ───────────

def test_402_quota_negative_caches(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (402, b"payment required"))
    got = enrich.fc_scrape("https://example.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error FROM enrichment_cache WHERE provider='firecrawl'"
    ).fetchone()
    assert row["error"] == "http_402"


# ─── 429 rate limit ──────────────────────────────────────────────────────

def test_429_rate_limit(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (429, b""))
    got = enrich.fc_scrape("https://example.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error, expires_at, fetched_at FROM enrichment_cache"
    ).fetchone()
    assert row["error"] == "http_429"
    ttl = row["expires_at"] - row["fetched_at"]
    assert 86390 <= ttl <= 86410


# ─── success:false envelope ──────────────────────────────────────────────

def test_unsuccessful_envelope_negative_caches(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    resp = {"success": False, "error": "Unable to fetch URL"}
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (200, json.dumps(resp).encode()))
    got = enrich.fc_scrape("https://example.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error FROM enrichment_cache WHERE provider='firecrawl'"
    ).fetchone()
    assert row["error"] == "fc_unsuccessful"


# ─── Malformed JSON ──────────────────────────────────────────────────────

def test_malformed_json_negative_caches(monkeypatch):
    write_fc_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (200, b"<html>not json</html>"))
    got = enrich.fc_scrape("https://example.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error FROM enrichment_cache WHERE provider='firecrawl'"
    ).fetchone()
    assert row["error"] == "malformed_json"


# ─── extract_first_url helper ────────────────────────────────────────────

def test_extract_first_url_from_post_body():
    body = ("Looking for an Apollo alternative. Tried hunter, "
            "looked at https://g2.com/categories/sales-engagement "
            "and someone mentioned outreach too.")
    url = enrich.extract_first_url(body)
    assert url == "https://g2.com/categories/sales-engagement"


def test_extract_first_url_returns_none_when_no_link():
    assert enrich.extract_first_url("just plain text, no links") is None


def test_extract_first_url_strips_trailing_punctuation():
    body = "Check out https://example.com/page."
    url = enrich.extract_first_url(body)
    assert url == "https://example.com/page"


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
