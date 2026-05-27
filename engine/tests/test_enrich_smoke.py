"""ENR-6: end-to-end smoke. Wire DFS + Firecrawl through onboarding warmup,
populate the cache, then verify a `fetch-score`-like pipeline reads from the
cache during augment_scores and a surface gains enrichment.

Realistic harness: tmp config + data dirs, monkeypatched HTTP, synthetic
candidates fed through enrich.augment_scores. Avoids the full cli stack
(which needs subreddits.yml + reddit.fetch_delta mocking) so the smoke
stays focused on the enrichment story, not the gate machinery.
"""
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


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def test_smoke_warmup_then_scan_attaches_link_context(monkeypatch):
    """Full path: onboarding warmup populates cache, simulated scan augments.

    Steps:
      1. Write DFS + FC YAMLs (simulating finished /subscope-onboard).
      2. Mock _client_request to return canned DFS competitors + FC scrape.
      3. Call enrich.warmup_for_onboarding('https://acme.com', conn) →
         cache gets 2 rows (one DFS, one FC).
      4. Build a synthetic candidate whose body cites the same homepage URL.
      5. Call enrich.augment_scores([candidate], conn) → no HTTP, candidate
         picks up link_context from the cached FC payload.
    """
    (store.xdg_config_dir() / "dataforseo.yml").write_text(
        "login: u\npassword: p\n"
    )
    (store.xdg_config_dir() / "firecrawl.yml").write_text("api_key: fc-x\n")
    conn = fresh_db()

    dfs_resp = {
        "status_code": 20000,
        "tasks": [{
            "status_code": 20000,
            "result": [{"items": [{"domain": "rival1.com"},
                                  {"domain": "rival2.com"}]}],
        }],
    }
    fc_resp = {
        "success": True,
        "data": {
            "markdown": "# Acme\n\nWe help RevOps teams find Reddit threads where buyers are shopping.",
            "metadata": {"title": "Acme - Reddit lead-gen"},
        },
    }
    http_calls = []

    def fake_req(method, url, headers, body, timeout):
        http_calls.append(url)
        if "dataforseo" in url:
            return 200, json.dumps(dfs_resp).encode()
        if "firecrawl" in url:
            return 200, json.dumps(fc_resp).encode()
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(enrich, "_client_request", fake_req)

    # ── Phase A: onboarding warmup
    warmup_result = enrich.warmup_for_onboarding("https://acme.com", conn)
    assert warmup_result["dataforseo"]["competitors_found"] == 2
    assert warmup_result["firecrawl"]["markdown_chars"] > 0
    # Two HTTP calls, one per provider
    assert sum(1 for u in http_calls if "dataforseo" in u) == 1
    assert sum(1 for u in http_calls if "firecrawl" in u) == 1

    # Cache populated
    rows = conn.execute(
        "SELECT provider, endpoint FROM enrichment_cache"
    ).fetchall()
    keys = {(r["provider"], r["endpoint"]) for r in rows}
    assert ("dataforseo", "competitors_domain") in keys
    assert ("firecrawl", "scrape") in keys

    # ── Phase B: simulated scan augmentation
    http_calls_before_b = len(http_calls)
    candidate = {
        "post": {
            "id": "p1",
            "body": "We are looking at https://acme.com vs hubspot. Anyone tried?",
            "title": "alternatives to acme",
            "score_internal": 50.0,
        },
        "sub": {"name": "sales", "tier": 1},
        "blog_matches": [],
    }
    enrich.augment_scores([candidate], conn)

    # Phase B is cache-read only: no NEW http calls
    assert len(http_calls) == http_calls_before_b
    # Candidate gained link_context
    assert "enrichment" in candidate
    assert "link_context" in candidate["enrichment"]
    assert "Reddit lead-gen" in candidate["enrichment"]["link_context"]["title"]
    assert "Acme" in candidate["enrichment"]["link_context"]["excerpt"]


def test_smoke_partial_failure_still_emits_surface(monkeypatch):
    """If DFS 500s mid-warmup, FC still runs, Phase B still proceeds, the
    scan still completes. Fail-open at every layer."""
    (store.xdg_config_dir() / "dataforseo.yml").write_text(
        "login: u\npassword: p\n"
    )
    (store.xdg_config_dir() / "firecrawl.yml").write_text("api_key: fc-x\n")
    conn = fresh_db()

    fc_resp = {
        "success": True,
        "data": {"markdown": "fine", "metadata": {"title": "Acme"}},
    }

    def fake_req(method, url, headers, body, timeout):
        if "dataforseo" in url:
            return 500, b"down"   # DFS fails
        if "firecrawl" in url:
            return 200, json.dumps(fc_resp).encode()
        raise AssertionError(f"unexpected: {url}")

    monkeypatch.setattr(enrich, "_client_request", fake_req)

    result = enrich.warmup_for_onboarding("https://acme.com", conn)
    assert result["dataforseo"]["skipped_reason"] == "fetch_failed_or_cached_negative"
    assert result["firecrawl"]["markdown_chars"] > 0   # FC succeeded

    # Phase B still augments from the FC cache
    candidate = {
        "post": {"id": "p2", "body": "compare https://acme.com to anything",
                 "score_internal": 50.0, "title": "x"},
        "sub": {"name": "sales", "tier": 1},
        "blog_matches": [],
    }
    enrich.augment_scores([candidate], conn)
    assert "enrichment" in candidate


def test_smoke_no_keys_no_op_throughout(monkeypatch):
    """Default install (no DFS, no FC) must touch zero network and produce no
    enrichment fields. Regression guard for the default-scan no-op path."""
    conn = fresh_db()
    called = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: called.append(1) or (200, b""))

    # Warmup is a no-op with no creds
    result = enrich.warmup_for_onboarding("https://acme.com", conn)
    assert result["dataforseo"]["called"] is False
    assert result["firecrawl"]["called"] is False
    assert called == []

    # augment_scores is a no-op with no creds AND empty cache
    candidate = {
        "post": {"id": "p3", "body": "See https://example.com for info",
                 "score_internal": 50.0, "title": "x"},
        "sub": {"name": "sales", "tier": 1},
        "blog_matches": [],
    }
    enrich.augment_scores([candidate], conn)
    assert "enrichment" not in candidate
    assert called == []


def test_perf_augment_scores_under_50ms_overhead():
    """Performance guard: augment_scores on 100 candidates with EMPTY cache
    must complete in well under the 50ms budget for the no-key scan path.

    The default-state scan path (no providers configured) is what most
    users hit on day 1; it must not regress.
    """
    import time
    conn = fresh_db()
    # No YAMLs written -> detect_providers returns False -> immediate return
    candidates = [
        {"post": {"id": f"p{i}", "body": f"some https://example.com/{i}",
                  "score_internal": 50.0, "title": "x"},
         "sub": {"name": "sales", "tier": 1},
         "blog_matches": []}
        for i in range(100)
    ]
    t0 = time.perf_counter()
    enrich.augment_scores(candidates, conn)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 50, f"augment_scores took {elapsed_ms:.1f}ms (budget 50ms)"


def test_perf_augment_with_warm_cache_under_50ms():
    """With BOTH providers configured + cache warm, augment_scores reads SQLite
    100 times. Must still be <50ms for the steady-state hot path."""
    import time
    (store.xdg_config_dir() / "firecrawl.yml").write_text("api_key: fc-x\n")
    conn = fresh_db()

    # Pre-warm the cache for 50 distinct URLs
    for i in range(50):
        url = f"https://example.com/{i}"
        key = enrich.cache_key("scrape", url)
        store.enrich_put(conn, "firecrawl", "scrape", key,
                         json.dumps({"url": url, "title": "T",
                                     "markdown": "M"}),
                         ttl_seconds=3600)

    candidates = [
        {"post": {"id": f"p{i}",
                  "body": f"check https://example.com/{i % 50} for details",
                  "score_internal": 50.0, "title": "x"},
         "sub": {"name": "sales", "tier": 1},
         "blog_matches": []}
        for i in range(100)
    ]
    t0 = time.perf_counter()
    enrich.augment_scores(candidates, conn)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 50, f"hot-cache augment took {elapsed_ms:.1f}ms (budget 50ms)"
    # Sanity: at least some candidates got link_context
    enriched = sum(1 for c in candidates if "enrichment" in c)
    assert enriched > 0


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
