"""Tests for ENR-2: enrich.py plumbing (probe, kill switch, banner, status)."""
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import enrich, store  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_xdg(tmp_path, monkeypatch):
    """Every test gets its own SUBSCOPE_CONFIG + SUBSCOPE_DATA dirs."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path / "cfg"))
    monkeypatch.setenv("SUBSCOPE_DATA", str(tmp_path / "data"))
    enrich.reset_cache()
    enrich.set_disabled(False)
    monkeypatch.delenv("SUBSCOPE_NO_ENRICH", raising=False)


def write_yaml(name: str, content: str):
    p = store.xdg_config_dir() / name
    p.write_text(content)


def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


# ─── Activation: detect_providers / enrichment_enabled ───────────────────

def test_detect_returns_both_false_when_no_yaml():
    assert enrich.detect_providers() == {"dataforseo": False, "firecrawl": False}


def test_detect_dfs_when_only_dfs_yaml_present():
    write_yaml("dataforseo.yml", "login: u\npassword: p\n")
    got = enrich.detect_providers()
    assert got["dataforseo"] is True
    assert got["firecrawl"] is False


def test_detect_fc_when_only_fc_yaml_present():
    write_yaml("firecrawl.yml", "api_key: fc-abc\n")
    got = enrich.detect_providers()
    assert got["dataforseo"] is False
    assert got["firecrawl"] is True


def test_detect_both_when_both_yamls_present():
    write_yaml("dataforseo.yml", "login: u\npassword: p\n")
    write_yaml("firecrawl.yml", "api_key: fc-abc\n")
    got = enrich.detect_providers()
    assert got == {"dataforseo": True, "firecrawl": True}


# ─── Kill switches ───────────────────────────────────────────────────────

def test_env_kill_switch_disables_detection():
    write_yaml("dataforseo.yml", "login: u\npassword: p\n")
    import os
    os.environ["SUBSCOPE_NO_ENRICH"] = "1"
    try:
        assert enrich.detect_providers() == {"dataforseo": False, "firecrawl": False}
    finally:
        os.environ.pop("SUBSCOPE_NO_ENRICH", None)


def test_module_kill_switch_disables_detection():
    write_yaml("firecrawl.yml", "api_key: fc-abc\n")
    enrich.set_disabled(True)
    assert enrich.detect_providers() == {"dataforseo": False, "firecrawl": False}


def test_enrichment_enabled_default():
    assert enrich.enrichment_enabled() is True


# ─── Fail-open YAML loader ───────────────────────────────────────────────

def test_load_yaml_config_missing_file_returns_none():
    assert enrich.load_yaml_config("nonexistent.yml") is None


def test_load_yaml_config_malformed_returns_none(capsys):
    write_yaml("dataforseo.yml", "login: u\npassword: [unclosed\n")
    assert enrich.load_yaml_config("dataforseo.yml") is None
    err = capsys.readouterr().err
    assert "malformed YAML" in err


def test_load_yaml_config_non_dict_returns_none(capsys):
    write_yaml("dataforseo.yml", "- just\n- a\n- list\n")
    assert enrich.load_yaml_config("dataforseo.yml") is None
    err = capsys.readouterr().err
    assert "not a mapping" in err


def test_malformed_dfs_yaml_does_not_enable_provider():
    write_yaml("dataforseo.yml", "login: u\npassword:\n  - not\n  - a\n  - string\n")
    assert enrich.detect_providers()["dataforseo"] is False


# ─── Privacy banner: once per process per provider ───────────────────────

def test_banner_fires_once_per_provider(capsys):
    enrich.show_banner_once("dataforseo")
    enrich.show_banner_once("dataforseo")
    enrich.show_banner_once("firecrawl")
    err = capsys.readouterr().err
    assert err.count("DataForSEO call") == 1
    assert err.count("Firecrawl call") == 1


def test_banner_reset_after_reset_cache(capsys):
    enrich.show_banner_once("dataforseo")
    enrich.reset_cache()
    enrich.show_banner_once("dataforseo")
    err = capsys.readouterr().err
    assert err.count("DataForSEO call") == 2


# ─── Negative-cache TTL mapping ──────────────────────────────────────────

def test_negative_cache_ttl_auth():
    assert enrich.negative_cache_ttl(401) == 3600
    assert enrich.negative_cache_ttl(403) == 3600


def test_negative_cache_ttl_rate_limit():
    assert enrich.negative_cache_ttl(429) == 86400


def test_negative_cache_ttl_5xx():
    assert enrich.negative_cache_ttl(500) == 600
    assert enrich.negative_cache_ttl(503) == 600


# ─── Quota-blocked short-circuit ─────────────────────────────────────────

def test_is_quota_blocked_false_when_no_negative_cache():
    conn = fresh_db()
    assert enrich.is_quota_blocked(conn, "dataforseo") is False


def test_is_quota_blocked_true_after_429():
    conn = fresh_db()
    store.enrich_put(conn, "dataforseo", "competitors_domain", "acme",
                     '{}', ttl_seconds=86400, error="429 rate_limited")
    assert enrich.is_quota_blocked(conn, "dataforseo") is True


def test_is_quota_blocked_ignores_expired_negative_cache():
    conn = fresh_db()
    store.enrich_put(conn, "dataforseo", "any", "k",
                     '{}', ttl_seconds=-1, error="429 rate_limited")
    assert enrich.is_quota_blocked(conn, "dataforseo") is False


def test_is_quota_blocked_isolated_per_provider():
    conn = fresh_db()
    store.enrich_put(conn, "dataforseo", "x", "k",
                     '{}', ttl_seconds=3600, error="429")
    assert enrich.is_quota_blocked(conn, "dataforseo") is True
    assert enrich.is_quota_blocked(conn, "firecrawl") is False


# ─── status() ────────────────────────────────────────────────────────────

def test_status_neither_configured():
    s = enrich.status()
    assert s["dataforseo"]["configured"] is False
    assert s["firecrawl"]["configured"] is False


def test_status_with_one_configured():
    write_yaml("dataforseo.yml", "login: u\npassword: p\n")
    s = enrich.status()
    assert s["dataforseo"]["configured"] is True
    assert s["firecrawl"]["configured"] is False


def test_status_with_db_reports_last_call_state():
    write_yaml("dataforseo.yml", "login: u\npassword: p\n")
    conn = fresh_db()
    store.enrich_put(conn, "dataforseo", "competitors_domain", "acme",
                     '{"competitors": []}', ttl_seconds=600)
    s = enrich.status(conn)
    assert s["dataforseo"]["last_call_ok"] is True
    assert s["dataforseo"]["blocked"] is False


# ─── HTTP seam: SSRF guard fires before any request ──────────────────────

def test_client_request_rejects_ssrf_target():
    """https:// to AWS metadata IP must be blocked by the private-IP guard."""
    with pytest.raises(ValueError, match="private/link-local"):
        enrich._client_request("GET", "https://169.254.169.254/latest/meta-data/",
                               headers={}, body=None)


def test_client_request_rejects_non_https_remote():
    with pytest.raises(ValueError, match="http://"):
        enrich._client_request("GET", "http://api.dataforseo.com/v3/x",
                               headers={}, body=None)


# ─── cache_key determinism ───────────────────────────────────────────────

def test_cache_key_stable_across_calls():
    a = enrich.cache_key("dataforseo", "competitors_domain", "acme.com")
    b = enrich.cache_key("dataforseo", "competitors_domain", "acme.com")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_cache_key_distinguishes_args():
    a = enrich.cache_key("dataforseo", "x", "acme.com")
    b = enrich.cache_key("dataforseo", "y", "acme.com")
    assert a != b


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
