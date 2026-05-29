"""End-to-end disable-flag demonstration for dual-track surfaces (DT-3 / DT-5).

Drives the REAL cmd_fetch_score pipeline against a temp SQLite DB, mocking only
the network boundaries (Reddit fetch + author vetting). Proves the headline
contract: with authority_track.enabled=false the surfaced output reverts to
today's buyer-only behavior EXACTLY, and with it enabled the same input yields a
second authority section without changing the buyer surfaces.

No live Reddit fetch (this worktree predates the 403 fix; we never call out).
"""
import io
import json
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope import cli  # noqa: E402
from subscope.lib import author_vet, classify, enrich, reddit, slack  # noqa: E402


NOW = int(time.time())

KEYWORDS = {
    "shared": [
        "invoicing", "invoice", "bookkeeping", "accounting", "reconciliation",
        "expense", "client", "workflow", "spreadsheet", "automation",
    ],
    "operator": [],
}


def _weights(authority_enabled: bool) -> dict:
    return {
        "tier1_gates": {"post_age_hours": 48, "comment_ceiling": 100, "pain_keywords_min": 1},
        "tier2_gates": {"post_age_hours": 72, "pain_keywords_min": 1, "pain_keywords_min_wide_open": 1},
        "scoring": {
            "freshness_decay": {"zero_hours": 30, "max_points": 30},
            "upvote_velocity": {"multiplier": 4, "max_points": 20},
            "comment_velocity": {"multiplier": 6, "max_points": 15},
            "pain_keyword_match": {"points_per_keyword": 6, "max_points": 30},
            "blog_coverage_bonus": {"points_per_match": 25, "max_points": 50},
            "intent_bonus": {"question_bonus": 20, "pain_bonus": 15},
            "tier_weight": {"tier_1": 1.0, "tier_2": 1.25},
        },
        "daily_output": {
            "hard_ceiling": 12, "default_target": 10, "minimum": 0,
            "tier1_per_sub_cap": 2, "tier2_per_sub_cap": 2,
            "backfill_sub_cap_bonus": 1,
            "pattern_caps": {"default": 10},
        },
        "freshness_floor": {"enabled": False},
        "authority_track": {
            "enabled": authority_enabled,
            "cap": 4,
            "min_keyword_density": 2,
            "scoring": {"reach_weight": 1.5, "answerability_weight": 1.5,
                        "blog_weight": 1.5, "pain_weight": 0.25,
                        "freshness_max_points": 30},
        },
        "cooling": {"default_minutes": 0},
    }


def _sub() -> dict:
    return {"name": "Bookkeeping", "tier": 2, "bucket": "operator",
            "weight": 1.0, "saturation": "medium", "backing_blogs": []}


def _posts() -> list[dict]:
    """One clean BUYER post (named brand + pain) and one clean AUTHORITY post
    (brandless, on-topic, answerable question)."""
    buyer = {
        "id": "buyer1", "subreddit": "Bookkeeping",
        "title": "QuickBooks pricing is brutal, any cheaper alternative for invoicing?",
        "url": "https://reddit.com/r/Bookkeeping/comments/buyer1/x/",
        "canonical_url": "https://reddit.com/comments/buyer1/",
        "author": "buyer_op", "created_utc": NOW - 3600,
        "score": 30, "num_comments": 8, "body": "paying too much, tired of it",
        "removed": False, "locked": False, "over_18": False,
    }
    authority = {
        "id": "auth1", "subreddit": "Bookkeeping",
        "title": "How do you handle invoicing and reconciliation for retainer clients?",
        "url": "https://reddit.com/r/Bookkeeping/comments/auth1/x/",
        "canonical_url": "https://reddit.com/comments/auth1/",
        "author": "auth_op", "created_utc": NOW - 3600,
        "score": 25, "num_comments": 12, "body": "planning a clean workflow, no tool picked yet",
        "removed": False, "locked": False, "over_18": False,
    }
    return [buyer, authority]


def _run(monkeypatch, tmp_path, authority_enabled: bool) -> dict:
    monkeypatch.setenv("SUBSCOPE_DATA", str(tmp_path / f"data_{authority_enabled}"))
    # Control config entirely (so we drive authority_track.enabled directly).
    monkeypatch.setattr(cli, "_load_configs", lambda mode="default": {
        "subs": [_sub()], "keywords": KEYWORDS,
        "weights": _weights(authority_enabled), "mode": mode,
    })
    # Mock the network boundaries. No live Reddit, no author fetch.
    monkeypatch.setattr(reddit, "fetch_delta", lambda name, cursor, max_limit=25: _posts())
    monkeypatch.setattr(author_vet, "vet_author",
                        lambda author, conn=None, weights=None: {"verdict": "pass", "reason": "ok"})
    # Keep the optional layers inert (they already no-op without creds, but be explicit).
    monkeypatch.setattr(classify, "classify", lambda post: None)
    monkeypatch.setattr(enrich, "augment_scores", lambda cands, conn: None)
    monkeypatch.setattr(slack, "notify_if_configured", lambda payload: None)

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.cmd_fetch_score(no_slack=True)
    return json.loads(buf.getvalue())


def test_enabled_surfaces_both_tracks(monkeypatch, tmp_path):
    payload = _run(monkeypatch, tmp_path, authority_enabled=True)
    assert payload["buyer_count"] == 1
    assert payload["authority_count"] == 1
    tracks = {s["post_id"]: s["track"] for s in payload["surfaces"]}
    assert tracks["buyer1"] == "buyer"
    assert tracks["auth1"] == "authority"
    # Every surface carries a track field.
    assert all("track" in s for s in payload["surfaces"])
    # Two labeled sections, buyer first.
    table = payload["inline_table"]
    assert "BUYER SIGNALS (1)" in table
    assert "AUTHORITY PLAYS (1)" in table
    assert table.index("BUYER SIGNALS") < table.index("AUTHORITY PLAYS")


def test_disabled_reverts_to_buyer_only(monkeypatch, tmp_path):
    """THE disable-flag guarantee: enabled=false yields buyer-only output, and
    the authority post never surfaces on any track."""
    payload = _run(monkeypatch, tmp_path, authority_enabled=False)
    assert payload["buyer_count"] == 1
    assert payload["authority_count"] == 0
    ids = {s["post_id"] for s in payload["surfaces"]}
    assert ids == {"buyer1"}, "authority post must not surface when disabled"
    # No authority section, and no new labels at all (today's exact layout).
    table = payload["inline_table"]
    assert "AUTHORITY PLAYS" not in table
    assert "BUYER SIGNALS" not in table


def test_buyer_surfaces_identical_across_flag(monkeypatch, tmp_path):
    """Flipping the authority flag does NOT change the buyer surfaces (the buyer
    track is untouched by dual-track)."""
    on = _run(monkeypatch, tmp_path, authority_enabled=True)
    off = _run(monkeypatch, tmp_path, authority_enabled=False)
    buyer_on = [s for s in on["surfaces"] if s["track"] == "buyer"]
    buyer_off = [s for s in off["surfaces"] if s["track"] == "buyer"]
    # Same buyer posts, same order, same scores.
    assert [s["post_id"] for s in buyer_on] == [s["post_id"] for s in buyer_off]
    assert [s["score_internal"] for s in buyer_on] == [s["score_internal"] for s in buyer_off]


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
