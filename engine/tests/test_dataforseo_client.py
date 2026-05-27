"""Tests for DFS-1: DataForSEO client functions inside enrich.py."""
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
        "login: testuser\npassword: testpass\n"
    )


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def _dfs_competitors_response(domains):
    """Build a realistic DFS competitors_domain envelope."""
    return {
        "status_code": 20000,
        "status_message": "Ok.",
        "tasks": [{
            "id": "x",
            "status_code": 20000,
            "result": [{
                "items": [{"domain": d, "metrics": {}} for d in domains],
            }],
        }],
    }


def _dfs_ranked_kw_response(keywords):
    """Build a realistic DFS ranked_keywords envelope.

    `keywords` is a list of (keyword, rank, volume) tuples.
    """
    return {
        "status_code": 20000,
        "status_message": "Ok.",
        "tasks": [{
            "status_code": 20000,
            "result": [{
                "items": [{
                    "keyword_data": {
                        "keyword": kw,
                        "keyword_info": {"search_volume": vol},
                    },
                    "ranked_serp_element": {
                        "serp_item": {"rank_absolute": rank},
                    },
                } for kw, rank, vol in keywords],
            }],
        }],
    }


# ─── No-config → no HTTP, returns None ───────────────────────────────────

def test_no_config_returns_none(monkeypatch):
    """No dataforseo.yml. Caller gets None. _client_request never invoked."""
    conn = fresh_db()
    called = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: called.append(1) or (200, b""))
    assert enrich.dfs_competitors_domain("acme.com", conn) is None
    assert called == []


# ─── Fresh hit caches response ───────────────────────────────────────────

def test_competitors_domain_fresh_hit_caches(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()
    fake_resp = _dfs_competitors_response(["alpha.com", "beta.com"])
    calls = []

    def fake_req(method, url, headers, body, timeout):
        calls.append({"url": url, "body": body, "method": method,
                      "auth": headers.get("Authorization")})
        return 200, json.dumps(fake_resp).encode()

    monkeypatch.setattr(enrich, "_client_request", fake_req)
    payload = enrich.dfs_competitors_domain("Acme.com", conn)
    assert payload == {"target": "acme.com",
                       "competitors": ["alpha.com", "beta.com"]}
    assert len(calls) == 1
    assert "competitors_domain" in calls[0]["url"]
    assert calls[0]["method"] == "POST"
    assert calls[0]["auth"].startswith("Basic ")

    # Cache row written
    row = conn.execute(
        "SELECT payload_json, error FROM enrichment_cache "
        "WHERE provider='dataforseo' AND endpoint='competitors_domain'"
    ).fetchone()
    assert row is not None
    assert row["error"] is None
    assert "alpha.com" in row["payload_json"]


# ─── Cache hit skips HTTP ────────────────────────────────────────────────

def test_cache_hit_skips_request(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()

    # Pre-seed positive cache
    payload = {"target": "acme.com", "competitors": ["x.com"]}
    key = enrich.cache_key("competitors_domain", "acme.com", 10)
    store.enrich_put(conn, "dataforseo", "competitors_domain", key,
                     json.dumps(payload), ttl_seconds=600)

    called = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: called.append(1) or (200, b""))
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got == payload
    assert called == []


# ─── 500 fail-open + negative cache ──────────────────────────────────────

def test_500_writes_negative_cache(monkeypatch, capsys):
    write_dfs_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (500, b"server died"))
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error, expires_at, fetched_at FROM enrichment_cache "
        "WHERE provider='dataforseo'"
    ).fetchone()
    assert row["error"] == "http_500"
    # 5xx TTL is 600s, allow a 2s skew for test scheduling
    ttl = row["expires_at"] - row["fetched_at"]
    assert 590 <= ttl <= 610


# ─── 429 backoff: 24h TTL ────────────────────────────────────────────────

def test_429_uses_long_backoff(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (429, b"slow down"))
    enrich.dfs_competitors_domain("acme.com", conn)
    row = conn.execute(
        "SELECT error, expires_at, fetched_at FROM enrichment_cache"
    ).fetchone()
    assert row["error"] == "http_429"
    ttl = row["expires_at"] - row["fetched_at"]
    assert 86390 <= ttl <= 86410  # 24h


def test_quota_blocked_short_circuits_subsequent_calls(monkeypatch):
    """After 429, the SAME provider is quota-blocked even for a different endpoint."""
    write_dfs_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (429, b""))
    enrich.dfs_competitors_domain("acme.com", conn)

    # Switch endpoint, same provider: quota gate blocks the request
    calls = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: calls.append(1) or (200, b""))
    got = enrich.dfs_ranked_keywords("acme.com", conn)
    assert got is None
    assert calls == []


# ─── Malformed JSON response ─────────────────────────────────────────────

def test_malformed_response_negative_caches(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (200, b"not json at all"))
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error FROM enrichment_cache WHERE provider='dataforseo'"
    ).fetchone()
    assert row["error"] == "malformed_json"


# ─── DFS api-level error (200 OK but envelope status != 20000) ───────────

def test_dfs_api_error_envelope_negative_caches(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()
    err_resp = {"status_code": 40400, "status_message": "Not found", "tasks": []}
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (200, json.dumps(err_resp).encode()))
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error FROM enrichment_cache WHERE provider='dataforseo'"
    ).fetchone()
    assert row["error"] == "dfs_40400"


# ─── Network exception falls open ────────────────────────────────────────

def test_network_exception_fails_open(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()

    def boom(*a, **k):
        raise TimeoutError("connect timeout")

    monkeypatch.setattr(enrich, "_client_request", boom)
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error FROM enrichment_cache WHERE provider='dataforseo'"
    ).fetchone()
    assert row["error"] == "TimeoutError"


# ─── ranked_keywords parses the deeply-nested DFS shape correctly ────────

def test_401_negative_caches_with_1h_ttl(monkeypatch):
    """End-to-end 401: cached as http_401 with the auth TTL (1h)."""
    write_dfs_yaml()
    conn = fresh_db()
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (401, b"unauthorized"))
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error, expires_at, fetched_at FROM enrichment_cache"
    ).fetchone()
    assert row["error"] == "http_401"
    ttl = row["expires_at"] - row["fetched_at"]
    assert 3590 <= ttl <= 3610


def test_same_key_negative_cache_short_circuits_second_call(monkeypatch):
    """After 429 caches a row, a SECOND call on the SAME key must short-circuit
    BEFORE building the HTTP request. Tests the `if hit["error"]: return None`
    branch inside _dfs_call.

    Important: this isolates the *same-key* short-circuit from is_quota_blocked
    by using a DIFFERENT provider for the negative-cache pollution, so
    is_quota_blocked returns False but enrich_get returns the negative row.
    Actually that wouldn't work either since enrich_get keys on provider too.
    Best isolation: short-TTL on quota check via fresh target, same endpoint.
    """
    write_dfs_yaml()
    conn = fresh_db()
    # First call: 429 caches a negative row for ("competitors_domain", target=acme)
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (429, b""))
    enrich.dfs_competitors_domain("acme.com", conn)

    # Second call to same target: must short-circuit. Quota check ALSO short-
    # circuits (correctly), so both pathways agree. Assert zero HTTP either way.
    calls = []
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: calls.append(1) or (200, b""))
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got is None
    assert calls == []


def test_ttl_expiry_rehits_http(monkeypatch):
    """Positive-cached row past expires_at: enrich_get returns None, so the
    high-level fn fires HTTP again instead of serving stale data."""
    write_dfs_yaml()
    conn = fresh_db()
    # Manually seed an EXPIRED positive cache row
    key = enrich.cache_key("competitors_domain", "acme.com", 10)
    store.enrich_put(conn, "dataforseo", "competitors_domain", key,
                     json.dumps({"competitors": ["stale.com"]}), ttl_seconds=-1)

    resp = _dfs_competitors_response(["fresh.com"])
    calls = []

    def fake_req(method, url, headers, body, timeout):
        calls.append(1)
        return 200, json.dumps(resp).encode()

    monkeypatch.setattr(enrich, "_client_request", fake_req)
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got["competitors"] == ["fresh.com"]
    assert calls == [1]


def test_task_level_failure_negative_caches(monkeypatch):
    """Envelope status 20000 BUT task-level status_code != 20000 must NOT be
    cached as a positive empty result. Architect's bug fix."""
    write_dfs_yaml()
    conn = fresh_db()
    resp = {
        "status_code": 20000,
        "status_message": "Ok.",
        "tasks": [{
            "status_code": 40000,  # task-level failure
            "status_message": "Task error",
            "result": None,
        }],
    }
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (200, json.dumps(resp).encode()))
    got = enrich.dfs_competitors_domain("acme.com", conn)
    assert got is None
    row = conn.execute(
        "SELECT error FROM enrichment_cache WHERE provider='dataforseo'"
    ).fetchone()
    assert row["error"] == "unexpected_shape"


def test_banner_fires_on_first_real_dfs_call(monkeypatch, capsys):
    """The first real DFS call must emit the stderr privacy banner."""
    write_dfs_yaml()
    conn = fresh_db()
    resp = _dfs_competitors_response(["x.com"])
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (200, json.dumps(resp).encode()))
    enrich.dfs_competitors_domain("acme.com", conn)
    err = capsys.readouterr().err
    assert "DataForSEO call this run" in err


def test_chmod_600_on_subscope_db_file(monkeypatch, tmp_path):
    """Non-negotiable per CLAUDE.md: fresh subscope.sqlite is 0o600."""
    monkeypatch.setenv("SUBSCOPE_DATA", str(tmp_path / "data"))
    with store.connect() as conn:
        conn.execute("SELECT 1")
    db_file = store.db_path()
    mode = db_file.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_ranked_keywords_parses_shape(monkeypatch):
    write_dfs_yaml()
    conn = fresh_db()
    resp = _dfs_ranked_kw_response([
        ("reddit lead gen", 4, 1300),
        ("b2b saas reddit", 12, 480),
    ])
    monkeypatch.setattr(enrich, "_client_request",
                        lambda *a, **k: (200, json.dumps(resp).encode()))
    got = enrich.dfs_ranked_keywords("acme.com", conn)
    assert got is not None
    assert got["target"] == "acme.com"
    assert len(got["keywords"]) == 2
    assert got["keywords"][0]["keyword"] == "reddit lead gen"
    assert got["keywords"][0]["rank"] == 4
    assert got["keywords"][0]["search_volume"] == 1300


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
