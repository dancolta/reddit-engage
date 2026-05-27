"""Tests for ENR-4: status + surface payload exposure."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import enrich, output, store  # noqa: E402


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


def _make_surface(post_id="p1", enrichment=None):
    s = {
        "post": {
            "id": post_id, "subreddit": "sales",
            "title": "t",
            "url": "https://reddit.com/r/sales/comments/p1/t/",
            "canonical_url": "https://reddit.com/comments/p1/",
            "author": "u", "created_utc": 1748100000,
            "score": 5, "num_comments": 1, "body": "x",
        },
        "sub": {"name": "sales", "tier": 1, "saturation": None},
        "blog_matches": [],
        "score_internal": 50.0,
        "vet": None,
    }
    if enrichment is not None:
        s["enrichment"] = enrichment
    return s


# ─── enrich.status() ─────────────────────────────────────────────────────

def test_status_neither_configured_no_db():
    s = enrich.status()
    assert s["dataforseo"]["configured"] is False
    assert s["firecrawl"]["configured"] is False
    assert s["dataforseo"]["blocked"] is None
    assert s["dataforseo"]["last_call_ok"] is None


def test_status_with_db_reports_blocked_and_last_ok():
    write_dfs_yaml()
    conn = fresh_db()
    # Positive cache row → last_call_ok True
    store.enrich_put(conn, "dataforseo", "competitors_domain", "k1",
                     '{"competitors": []}', ttl_seconds=600)
    s = enrich.status(conn)
    assert s["dataforseo"]["configured"] is True
    assert s["dataforseo"]["blocked"] is False
    assert s["dataforseo"]["last_call_ok"] is True


def test_status_reports_blocked_after_429():
    write_dfs_yaml()
    conn = fresh_db()
    store.enrich_put(conn, "dataforseo", "competitors_domain", "k1",
                     "{}", ttl_seconds=86400, error="http_429")
    s = enrich.status(conn)
    assert s["dataforseo"]["blocked"] is True
    assert s["dataforseo"]["last_call_ok"] is False


def test_status_mixed_one_configured_one_not():
    write_fc_yaml()
    s = enrich.status()
    assert s["dataforseo"]["configured"] is False
    assert s["firecrawl"]["configured"] is True


# ─── render_json_payload: enrichment field present/absent ────────────────

def test_payload_omits_enrichment_when_absent():
    surfaces = [_make_surface()]
    payload = output.render_json_payload(surfaces)
    assert "enrichment" not in payload[0]


def test_payload_includes_enrichment_when_present():
    enrichment = {
        "link_context": {
            "url": "https://g2.com/compare",
            "title": "G2",
            "excerpt": "Apollo vs Outreach...",
        }
    }
    surfaces = [_make_surface(enrichment=enrichment)]
    payload = output.render_json_payload(surfaces)
    assert "enrichment" in payload[0]
    assert payload[0]["enrichment"]["link_context"]["title"] == "G2"


def test_payload_does_not_emit_empty_enrichment_dict():
    """augment_scores might set candidate["enrichment"] = {} before attaching.
    Empty dict should NOT be rendered (consumers check truthiness)."""
    surfaces = [_make_surface(enrichment={})]
    payload = output.render_json_payload(surfaces)
    assert "enrichment" not in payload[0]


def test_payload_serializes_to_json_cleanly():
    enrichment = {"link_context": {"url": "https://x.com", "title": "T",
                                    "excerpt": "M"}}
    surfaces = [_make_surface(enrichment=enrichment)]
    payload = output.render_json_payload(surfaces)
    txt = json.dumps(payload)
    parsed = json.loads(txt)
    assert parsed[0]["enrichment"]["link_context"]["url"] == "https://x.com"


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
