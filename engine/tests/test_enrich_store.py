"""Tests for the enrichment_cache table + helpers (ENR-1)."""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import store  # noqa: E402


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def legacy_db_without_enrichment_table():
    """Simulate a pre-ENR-1 install: schema bootstrapped without the new table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema_without_enrich = store.SCHEMA.split("CREATE TABLE IF NOT EXISTS enrichment_cache")[0]
    conn.executescript(schema_without_enrich)
    return conn


def test_enrich_put_then_get_hits():
    conn = fresh_db()
    store.enrich_put(conn, "dataforseo", "competitors_domain", "acme.com",
                     '{"competitors": ["foo.com", "bar.com"]}', ttl_seconds=600)
    row = store.enrich_get(conn, "dataforseo", "competitors_domain", "acme.com")
    assert row is not None
    assert row["payload_json"] == '{"competitors": ["foo.com", "bar.com"]}'
    assert row["error"] is None


def test_enrich_get_miss_returns_none():
    conn = fresh_db()
    assert store.enrich_get(conn, "dataforseo", "any", "missing-key") is None


def test_enrich_get_expired_returns_none():
    conn = fresh_db()
    # TTL = -1 → already expired
    store.enrich_put(conn, "firecrawl", "scrape", "https://x.com",
                     '{"markdown": "..."}', ttl_seconds=-1)
    assert store.enrich_get(conn, "firecrawl", "scrape", "https://x.com") is None


def test_enrich_negative_cache_round_trip():
    """Negative cache: error column populated, payload is the redacted error string,
    short TTL. Caller can short-circuit during the backoff window."""
    conn = fresh_db()
    store.enrich_put(conn, "dataforseo", "competitors_domain", "acme.com",
                     '{}', ttl_seconds=3600, error="429 rate_limited")
    row = store.enrich_get(conn, "dataforseo", "competitors_domain", "acme.com")
    assert row is not None
    assert row["error"] == "429 rate_limited"


def test_enrich_put_upserts_in_place():
    conn = fresh_db()
    store.enrich_put(conn, "firecrawl", "scrape", "url1",
                     '{"v": 1}', ttl_seconds=600)
    store.enrich_put(conn, "firecrawl", "scrape", "url1",
                     '{"v": 2}', ttl_seconds=600)
    rows = conn.execute(
        "SELECT payload_json FROM enrichment_cache WHERE key_hash = 'url1'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["payload_json"] == '{"v": 2}'


def test_enrich_purge_expired_drops_only_stale():
    conn = fresh_db()
    store.enrich_put(conn, "dfs", "ep", "fresh", '{}', ttl_seconds=600)
    store.enrich_put(conn, "dfs", "ep", "stale", '{}', ttl_seconds=-1)
    purged = store.enrich_purge_expired(conn)
    assert purged == 1
    remaining = conn.execute("SELECT key_hash FROM enrichment_cache").fetchall()
    keys = {r["key_hash"] for r in remaining}
    assert keys == {"fresh"}


def test_idempotent_migration_on_legacy_db():
    """Pre-ENR-1 DB: enrichment_cache table missing. ensure_* creates it."""
    conn = legacy_db_without_enrichment_table()
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "enrichment_cache" not in tables  # confirm precondition
    store._ensure_enrichment_cache_table(conn)
    store._ensure_enrichment_cache_table(conn)  # second call no-ops
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "enrichment_cache" in tables


def test_distinct_provider_endpoint_pairs_dont_collide():
    """Same key_hash under different (provider, endpoint) must coexist."""
    conn = fresh_db()
    store.enrich_put(conn, "dataforseo", "competitors_domain", "acme",
                     '{"a": 1}', ttl_seconds=600)
    store.enrich_put(conn, "dataforseo", "serp_organic", "acme",
                     '{"b": 2}', ttl_seconds=600)
    store.enrich_put(conn, "firecrawl", "scrape", "acme",
                     '{"c": 3}', ttl_seconds=600)
    rows = conn.execute("SELECT COUNT(*) AS n FROM enrichment_cache").fetchone()
    assert rows["n"] == 3


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
